import psycopg2 # Substitui o sqlite3
import os       # Para ler a DATABASE_URL
from decimal import Decimal
from datetime import datetime, timedelta

class Database:
    def __init__(self):
        self.db_url = os.environ.get('DATABASE_URL')
        if not self.db_url:
            raise ValueError("Erro: A variável de ambiente DATABASE_URL não foi configurada.")
        
        # Cria todas as tabelas no início
        self.criar_tabela_usuarios()
        self.criar_tabela_transacoes()
        self.criar_tabela_config() # <-- NOVA TABELA

    def _get_connection(self):
        """Helper para obter uma nova conexão (thread-safe)."""
        try:
            conn = psycopg2.connect(self.db_url)
            return conn, conn.cursor()
        except Exception as e:
            print(f"Erro ao conectar no PostgreSQL: {e}")
            return None, None

    def _close_connection(self, conn, cursor):
        """Helper para fechar conexões."""
        if cursor: cursor.close()
        if conn: conn.close()
        
    def criar_tabela_usuarios(self):
        conn, cursor = None, None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id BIGINT PRIMARY KEY,
                    nome TEXT
                )
            """)
            conn.commit()
        except Exception as e:
            print(f"Erro ao criar tabela usuarios: {e}")
        finally:
            self._close_connection(conn, cursor)

    def criar_tabela_transacoes(self):
        conn, cursor = None, None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transacoes (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    tipo TEXT,
                    valor_num DECIMAL(10, 2),
                    valor_txt TEXT,
                    categoria TEXT,
                    metodo TEXT,
                    cartao TEXT,
                    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
                )
            """)
            conn.commit()
        except Exception as e:
            print(f"Erro ao criar tabela transacoes: {e}")
        finally:
            self._close_connection(conn, cursor)
            
    # --- NOVO: Tabela de Configuração ---
    def criar_tabela_config(self):
        conn, cursor = None, None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()
        except Exception as e:
            print(f"Erro ao criar tabela app_config: {e}")
        finally:
            self._close_connection(conn, cursor)

    # --- NOVO: Pegar valor de configuração ---
    def get_config(self, key):
        conn, cursor = None, None
        result = None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return None
            cursor.execute("SELECT value FROM app_config WHERE key = %s", (key,))
            row = cursor.fetchone()
            if row:
                result = row[0]
        except Exception as e:
            print(f"Erro em get_config: {e}")
        finally:
            self._close_connection(conn, cursor)
        return result

    # --- NOVO: Definir valor de configuração ---
    def set_config(self, key, value):
        conn, cursor = None, None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return
            cursor.execute("""
                INSERT INTO app_config (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, value))
            conn.commit()
        except Exception as e:
            print(f"Erro em set_config: {e}")
        finally:
            self._close_connection(conn, cursor)
    
    # --- Restante das suas funções (sem alteração, apenas convertidas para PostgreSQL) ---

    def add_transacao(self, user_id, tipo, valor_num, valor_txt, categoria, metodo="dinheiro", cartao=None, nome=""):
        conn, cursor = None, None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return
            cursor.execute("""
                INSERT INTO usuarios (user_id, nome) VALUES (%s, %s)
                ON CONFLICT(user_id) DO UPDATE SET nome = EXCLUDED.nome
            """, (user_id, nome))
            cursor.execute("""
                INSERT INTO transacoes (user_id, tipo, valor_num, valor_txt, categoria, metodo, cartao, data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, tipo, float(valor_num), valor_txt, categoria, metodo, cartao, datetime.now()))
            conn.commit()
        except Exception as e:
            print(f"Erro em add_transacao: {e}")
            if conn: conn.rollback()
        finally:
            self._close_connection(conn, cursor)

    def get_soma(self, user_id, tipo, inicio=None, fim=None):
        conn, cursor = None, None
        result = None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return Decimal(0)
            query = "SELECT SUM(valor_num) FROM transacoes WHERE tipo=%s AND user_id=%s"
            params = [tipo, user_id]
            if inicio:
                query += " AND data::date >= %s::date"
                params.append(inicio.strftime("%Y-%m-%d"))
            if fim:
                query += " AND data::date <= %s::date"
                params.append(fim.strftime("%Y-%m-%d"))
            cursor.execute(query, params)
            result = cursor.fetchone()[0]
        except Exception as e:
            print(f"Erro em get_soma: {e}")
        finally:
            self._close_connection(conn, cursor)
        return Decimal(result or 0)

    def get_todas(self, user_id=None, tipo=None, inicio=None, fim=None):
        conn, cursor = None, None
        results = []
        try:
            conn, cursor = self._get_connection()
            if not cursor: return []
            query = "SELECT id, tipo, valor_num, categoria, metodo, cartao, data FROM transacoes WHERE 1=1"
            params = []
            if tipo: query += " AND tipo=%s"; params.append(tipo)
            if user_id: query += " AND user_id=%s"; params.append(user_id)
            if inicio: query += " AND data::date >= %s::date"; params.append(inicio.strftime("%Y-%m-%d"))
            if fim: query += " AND data::date <= %s::date"; params.append(fim.strftime("%Y-%m-%d"))
            query += " ORDER BY id DESC" 
            cursor.execute(query, params)
            results = cursor.fetchall()
        except Exception as e:
            print(f"Erro em get_todas: {e}")
        finally:
            self._close_connection(conn, cursor)
        return results

    def limpar_transacoes(self, user_id=None, opcao=None):
        conn, cursor = None, None
        try:
            conn, cursor = self._get_connection()
            if not cursor: return
            now = datetime.now()
            if opcao == "ultimo":
                transacoes = self.get_todas(user_id=user_id) 
                if transacoes:
                    ultima_id = transacoes[0][0] 
                    cursor.execute("DELETE FROM transacoes WHERE id=%s", (ultima_id,))
            elif opcao == "dia":
                hoje = now.strftime("%Y-%m-%d")
                cursor.execute("DELETE FROM transacoes WHERE user_id=%s AND data::date = %s::date", (user_id, hoje))
            elif opcao == "semana":
                semana_inicio = now - timedelta(days=now.weekday())
                cursor.execute("DELETE FROM transacoes WHERE user_id=%s AND data::date >= %s::date", (user_id, semana_inicio.strftime("%Y-%m-%d")))
            elif opcao == "mes":
                primeiro_dia_mes = now.replace(day=1).strftime("%Y-%m-%d")
                cursor.execute("DELETE FROM transacoes WHERE user_id=%s AND data::date >= %s::date", (user_id, primeiro_dia_mes))
            elif opcao == "tudo" and user_id is not None:
                cursor.execute("DELETE FROM transacoes WHERE user_id=%s", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"Erro em limpar_transacoes: {e}")
            if conn: conn.rollback()
        finally:
            self._close_connection(conn, cursor)

    def listar_usuarios(self):
        conn, cursor = None, None
        results = []
        try:
            conn, cursor = self._get_connection()
            if not cursor: return []
            cursor.execute("SELECT user_id, nome FROM usuarios ORDER BY nome ASC")
            results = [(row[0], row[1] or f"Usuário {row[0]}") for row in cursor.fetchall()]
        except Exception as e:
            print(f"Erro em listar_usuarios: {e}")
        finally:
            self._close_connection(conn, cursor)
        return results

    def gastos_por_categoria(self, user_id=None, inicio=None, fim=None):
        conn, cursor = None, None
        results = []
        try:
            conn, cursor = self._get_connection()
            if not cursor: return []
            query = "SELECT categoria, SUM(valor_num) FROM transacoes WHERE tipo='gasto'"
            params = []
            if user_id is not None: query += " AND user_id=%s"; params.append(user_id)
            if inicio: query += " AND data::date >= %s::date"; params.append(inicio.strftime("%Y-%m-%d"))
            if fim: query += " AND data::date <= %s::date"; params.append(fim.strftime("%Y-%m-%d"))
            query += " GROUP BY categoria HAVING SUM(valor_num) > 0"
            cursor.execute(query, params)
            results = cursor.fetchall()
        except Exception as e:
            print(f"Erro em gastos_por_categoria: {e}")
        finally:
            self._close_connection(conn, cursor)
        return results

    def series_mensais(self, user_id=None, meses=6):
        hoje = datetime.now(); labels = []; entradas_vals = []; gastos_vals = []
        for i in reversed(range(meses)):
            mes_alvo = hoje.month - i; ano_alvo = hoje.year
            if mes_alvo <= 0: mes_alvo += 12; ano_alvo -= 1
            primeiro_dia = datetime(ano_alvo, mes_alvo, 1)
            prox_mes = mes_alvo + 1; prox_ano = ano_alvo
            if prox_mes > 12: prox_mes = 1; prox_ano += 1
            ultimo_dia = datetime(prox_ano, prox_mes, 1) - timedelta(days=1)
            labels.append(primeiro_dia.strftime("%b/%Y"))
            soma_entrada = self.get_soma(user_id, "entrada", inicio=primeiro_dia, fim=ultimo_dia)
            soma_gasto = self.get_soma(user_id, "gasto", inicio=primeiro_dia, fim=ultimo_dia)
            entradas_vals.append(float(soma_entrada))
            gastos_vals.append(float(soma_gasto))
        return labels, entradas_vals, gastos_vals

    def get_gastos_por_cartao(self, user_id=None):
        conn, cursor = None, None
        results = []
        try:
            conn, cursor = self._get_connection()
            if not cursor: return []
            query = "SELECT cartao, SUM(valor_num) FROM transacoes WHERE tipo='gasto' AND cartao IS NOT NULL"
            params = []
            if user_id is not None: query += " AND user_id=%s"; params.append(user_id)
            query += " GROUP BY cartao HAVING SUM(valor_num) > 0"
            cursor.execute(query, params)
            results = cursor.fetchall()
        except Exception as e:
            print(f"Erro em get_gastos_por_cartao: {e}")
        finally:
            self._close_connection(conn, cursor)
        return results

# Cria o objeto global do banco (agora conectando ao PostgreSQL)
db = Database()