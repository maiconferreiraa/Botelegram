import sqlite3
from decimal import Decimal
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_name="financeiro.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.criar_tabela_transacoes() # Renomeado para clareza
        self.criar_tabela_usuarios()   # --- NOVO --- Adicionado para normalizar
        self.migrar_colunas_antigas()  # Renomeado

    def criar_tabela_transacoes(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS transacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, 
                tipo TEXT,
                valor_num REAL,
                valor_txt TEXT,
                categoria TEXT,
                metodo TEXT,
                cartao TEXT,
                data TEXT,
                FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
            )
        """)
        self.conn.commit()

    # --- NOVO ---
    # É uma prática muito melhor ter uma tabela separada para usuários
    def criar_tabela_usuarios(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id INTEGER PRIMARY KEY,
                nome TEXT
            )
        """)
        self.conn.commit()

    def migrar_colunas_antigas(self):
        # Migra user_id da tabela antiga se necessário
        try:
            self.cursor.execute("SELECT user_id FROM transacoes LIMIT 1")
        except sqlite3.OperationalError:
            try:
                self.cursor.execute("ALTER TABLE transacoes ADD COLUMN user_id INTEGER")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass # Coluna já existe por algum motivo

        # Migra nome da tabela antiga (se existir) para a tabela nova
        try:
            self.cursor.execute("SELECT nome FROM transacoes LIMIT 1")
            # Se a coluna 'nome' existe na tabela transacoes, migra os dados
            self.cursor.execute("""
                INSERT OR IGNORE INTO usuarios (user_id, nome)
                SELECT user_id, nome FROM transacoes WHERE nome IS NOT NULL AND nome != ''
                GROUP BY user_id
            """)
            # (Opcional: Remover a coluna 'nome' de 'transacoes' após migração)
            # self.cursor.execute("ALTER TABLE transacoes DROP COLUMN nome")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass # Coluna 'nome' não existe em transacoes, tudo bem.


    def add_transacao(self, user_id, tipo, valor_num, valor_txt, categoria, metodo="dinheiro", cartao=None, nome=""):
        # --- CORRIGIDO ---
        # 1. Garante que o usuário existe na tabela 'usuarios'
        self.cursor.execute("""
            INSERT INTO usuarios (user_id, nome) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET nome = excluded.nome
        """, (user_id, nome))
        
        # 2. Insere a transação
        self.cursor.execute("""
            INSERT INTO transacoes (user_id, tipo, valor_num, valor_txt, categoria, metodo, cartao, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, tipo, float(valor_num), valor_txt, categoria, metodo, cartao, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()

    def get_soma(self, user_id, tipo, inicio=None, fim=None):
        query = "SELECT SUM(valor_num) FROM transacoes WHERE tipo=? AND user_id=?"
        params = [tipo, user_id]
        if inicio:
            query += " AND date(data) >= date(?)"
            params.append(inicio.strftime("%Y-%m-%d"))
        if fim:
            query += " AND date(data) <= date(?)"
            params.append(fim.strftime("%Y-%m-%d"))
        self.cursor.execute(query, params)
        result = self.cursor.fetchone()[0]
        return Decimal(result or 0)

    # --- CORREÇÃO PRINCIPAL ---
    def get_todas(self, user_id=None, tipo=None, inicio=None, fim=None):
        # *** CORRIGIDO: Seleciona 'valor_num' (o número) em vez de 'valor_txt' (o texto) ***
        query = "SELECT id, tipo, valor_num, categoria, metodo, cartao, data FROM transacoes WHERE 1=1"
        params = []
        if tipo:
            query += " AND tipo=?"
            params.append(tipo)
        if user_id:
            query += " AND user_id=?"
            params.append(user_id)
        if inicio:
            query += " AND date(data) >= date(?)"
            params.append(inicio.strftime("%Y-%m-%d"))
        if fim:
            query += " AND date(data) <= date(?)"
            params.append(fim.strftime("%Y-%m-%d"))
        
        # Ordena por ID decrescente para mostrar os mais novos primeiro
        # O bot.py vai filtrar os valores "0", e agora a lista estará completa
        query += " ORDER BY id DESC" 
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    # --- CORREÇÃO DE BUG ---
    def limpar_transacoes(self, user_id=None, opcao=None):
        now = datetime.now()
        if opcao == "ultimo":
            # Busca ordenada por ID DESC (mais novo primeiro)
            transacoes = self.get_todas(user_id=user_id) 
            if transacoes:
                # *** CORRIGIDO: Pega o [0] (mais novo) em vez de [-1] (mais antigo) ***
                ultima_id = transacoes[0][0] 
                self.cursor.execute("DELETE FROM transacoes WHERE id=?", (ultima_id,))
        elif opcao == "dia":
            hoje = now.strftime("%Y-%m-%d")
            self.cursor.execute("DELETE FROM transacoes WHERE user_id=? AND date(data)=?", (user_id, hoje))
        elif opcao == "semana":
            # Pega segunda-feira da semana atual
            semana_inicio = now - timedelta(days=now.weekday())
            self.cursor.execute("DELETE FROM transacoes WHERE user_id=? AND date(data)>=?", (user_id, semana_inicio.strftime("%Y-%m-%d")))
        elif opcao == "mes":
            primeiro_dia_mes = now.replace(day=1).strftime("%Y-%m-%d")
            self.cursor.execute("DELETE FROM transacoes WHERE user_id=? AND date(data)>=?", (user_id, primeiro_dia_mes))
        elif opcao == "tudo" and user_id is not None: # Adicionada proteção
            self.cursor.execute("DELETE FROM transacoes WHERE user_id=?", (user_id,))
        self.conn.commit()

    # --- CORREÇÃO DE EFICIÊNCIA ---
    def listar_usuarios(self):
        # Busca na nova tabela de usuários, que é muito mais rápida e correta
        self.cursor.execute("SELECT user_id, nome FROM usuarios ORDER BY nome ASC")
        return [(row[0], row[1] or f"Usuário {row[0]}") for row in self.cursor.fetchall()]

    # =========================
    # Funções para gráficos
    # =========================
    def gastos_por_categoria(self, user_id=None, inicio=None, fim=None):
        query = "SELECT categoria, SUM(valor_num) FROM transacoes WHERE tipo='gasto'"
        params = []
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if inicio:
            query += " AND date(data) >= date(?)"
            params.append(inicio.strftime("%Y-%m-%d"))
        if fim:
            query += " AND date(data) <= date(?)"
            params.append(fim.strftime("%Y-%m-%d"))
        query += " GROUP BY categoria HAVING SUM(valor_num) > 0" # Adicionado filtro
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def series_mensais(self, user_id=None, meses=6):
        hoje = datetime.now()
        labels = []
        entradas_vals = []
        gastos_vals = []

        for i in reversed(range(meses)):
            # Cálculo de mês mais robusto
            mes_alvo = hoje.month - i
            ano_alvo = hoje.year
            if mes_alvo <= 0:
                mes_alvo += 12
                ano_alvo -= 1
            
            primeiro_dia = datetime(ano_alvo, mes_alvo, 1)
            
            # Encontra o último dia do mês
            prox_mes = mes_alvo + 1
            prox_ano = ano_alvo
            if prox_mes > 12:
                prox_mes = 1
                prox_ano += 1
            
            ultimo_dia = datetime(prox_ano, prox_mes, 1) - timedelta(days=1)
            
            labels.append(primeiro_dia.strftime("%b/%Y"))

            soma_entrada = self.get_soma(user_id, "entrada", inicio=primeiro_dia, fim=ultimo_dia)
            soma_gasto = self.get_soma(user_id, "gasto", inicio=primeiro_dia, fim=ultimo_dia)

            entradas_vals.append(float(soma_entrada))
            gastos_vals.append(float(soma_gasto))

        return labels, entradas_vals, gastos_vals

    def get_gastos_por_cartao(self, user_id=None):
        query = "SELECT cartao, SUM(valor_num) FROM transacoes WHERE tipo='gasto' AND cartao IS NOT NULL"
        params = []
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        query += " GROUP BY cartao HAVING SUM(valor_num) > 0" # Adicionado filtro
        self.cursor.execute(query, params)
        return self.cursor.fetchall()


# Cria o objeto global do banco
db = Database()