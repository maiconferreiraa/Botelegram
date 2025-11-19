import os
import json
from datetime import datetime, timedelta
from decimal import Decimal
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import pytz

# Configuração de Fuso Horário
LOCAL_TIMEZONE = pytz.timezone('America/Sao_Paulo')

class Database:
    def __init__(self):
        # Verifica se já foi inicializado para evitar erro de dupla inicialização
        if not firebase_admin._apps:
            json_config = os.environ.get('FIREBASE_CREDENTIALS')
            if not json_config:
                raise ValueError("Erro: A variável FIREBASE_CREDENTIALS não está configurada no Render.")
            
            # O Render armazena como string, convertemos de volta para dicionário
            cred_dict = json.loads(json_config)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        self.collection_transacoes = self.db.collection('transacoes')
        self.collection_usuarios = self.db.collection('usuarios')
        self.collection_config = self.db.collection('app_config')

    # --- USUÁRIOS ---
    def listar_usuarios(self):
        """Retorna lista apenas com os IDs dos usuários (int)."""
        docs = self.collection_usuarios.stream()
        return [int(doc.id) for doc in docs]

    def listar_usuarios_com_nome(self):
        """Retorna lista de tuplas (id, nome)."""
        docs = self.collection_usuarios.stream()
        lista = []
        for doc in docs:
            dados = doc.to_dict()
            # doc.id é string no firebase, convertemos para int
            lista.append((int(doc.id), dados.get('nome', f"Usuário {doc.id}")))
        return lista

    # --- TRANSAÇÕES (ADICIONAR) ---
    def add_transacao(self, user_id, tipo, valor_num, valor_txt, categoria, descricao, metodo="dinheiro", cartao=None, nome=""):
        # 1. Salvar/Atualizar Usuário
        self.collection_usuarios.document(str(user_id)).set({
            'user_id': user_id,
            'nome': nome
        }, merge=True)

        # 2. Salvar Transação
        dados = {
            'user_id': user_id,
            'tipo': tipo,
            'valor_num': float(valor_num), # Firebase não aceita Decimal nativo do Python
            'valor_txt': valor_txt,
            'categoria': categoria,
            'descricao': descricao,
            'metodo': metodo,
            'cartao': cartao,
            'data': datetime.now() # O Firebase converte isso para Timestamp
        }
        self.collection_transacoes.add(dados)

    # --- LEITURA DE DADOS (GET) ---
    def get_soma(self, user_id, tipo, inicio=None, fim=None):
        # No Firestore, agregações (SUM) client-side exigem ler os docs. 
        # Para uso pessoal, isso é ok. Para escala, usaria contadores.
        query = self.collection_transacoes.where('user_id', '==', user_id).where('tipo', '==', tipo)
        
        if inicio:
            query = query.where('data', '>=', inicio)
        if fim:
            query = query.where('data', '<=', fim)

        docs = query.stream()
        total = 0.0
        for doc in docs:
            total += doc.to_dict().get('valor_num', 0.0)
        
        return Decimal(str(total)) # Converte de volta para Decimal para o bot.py

    def get_todas(self, user_id=None, tipo=None, inicio=None, fim=None):
        """
        Retorna uma lista de listas simulando o formato SQL:
        [id, user_id, valor_num, categoria, metodo, cartao, data, descricao]
        Índices esperados pelo bot.py:
        0=id, 1=tipo(não usado aqui no select original mas mantendo ordem), 
        2=valor, 3=cat, 4=metodo, 5=cartao, 6=data, 7=descricao
        """
        query = self.collection_transacoes
        
        if user_id:
            query = query.where('user_id', '==', user_id)
        if tipo:
            query = query.where('tipo', '==', tipo)
        if inicio:
            query = query.where('data', '>=', inicio)
        if fim:
            query = query.where('data', '<=', fim)
            
        # Ordenação no Firestore requer índices compostos se usar Filtro + Ordenação.
        # Vamos ordenar em memória Python para evitar erros de índice no começo.
        docs = query.stream()
        
        resultados = []
        for doc in docs:
            d = doc.to_dict()
            
            # Tratamento da data (converte timestamp firebase para datetime python)
            dt = d.get('data')
            if dt and hasattr(dt, 'timestamp'):
                 # Converte para datetime naive ou timezone aware
                 dt = datetime.fromtimestamp(dt.timestamp())

            # Mapeia Dict -> Lista (para enganar o bot.py que acha que é SQL)
            # Estrutura SQL original: id, tipo, valor_num, categoria, metodo, cartao, data, descricao
            linha = [
                doc.id,             # 0: ID (agora é uma hash string)
                d.get('tipo'),      # 1
                d.get('valor_num'), # 2
                d.get('categoria'), # 3
                d.get('metodo'),    # 4
                d.get('cartao'),    # 5
                dt,                 # 6
                d.get('descricao')  # 7
            ]
            resultados.append(linha)
            
        # Ordenar por data decrescente (mais recente primeiro)
        resultados.sort(key=lambda x: x[6] if x[6] else datetime.min, reverse=True)
        
        return resultados

    def gastos_por_categoria(self, user_id=None, inicio=None, fim=None):
        """Simula: GROUP BY categoria"""
        transacoes = self.get_todas(user_id, tipo='gasto', inicio=inicio, fim=fim)
        
        agrupado = {}
        for t in transacoes:
            cat = t[3] # Indice 3 é categoria
            val = t[2] # Indice 2 é valor
            if cat not in agrupado: agrupado[cat] = 0.0
            agrupado[cat] += float(val)
            
        # Retorna lista de tuplas [(Cat, Valor)]
        return [(k, v) for k, v in agrupado.items()]

    def get_gastos_por_cartao(self, user_id=None):
        """Simula: GROUP BY cartao"""
        # Pega todas as transações de gasto desse usuário
        query = self.collection_transacoes.where('user_id', '==', user_id).where('tipo', '==', 'gasto')
        docs = query.stream()
        
        agrupado = {}
        for doc in docs:
            d = doc.to_dict()
            cartao = d.get('cartao')
            val = d.get('valor_num', 0.0)
            
            if cartao: # Só se tiver cartão definido
                if cartao not in agrupado: agrupado[cartao] = 0.0
                agrupado[cartao] += val
                
        return [(k, v) for k, v in agrupado.items()]

    def series_mensais(self, user_id=None, meses=6):
        # Mesma lógica do SQL, mas chamando o get_soma adaptado
        hoje = datetime.now(); labels = []; entradas_vals = []; gastos_vals = []
        for i in reversed(range(meses)):
            mes_alvo = hoje.month - i; ano_alvo = hoje.year
            if mes_alvo <= 0: mes_alvo += 12; ano_alvo -= 1
            primeiro_dia = datetime(ano_alvo, mes_alvo, 1)
            prox_mes = mes_alvo + 1; prox_ano = ano_alvo
            if prox_mes > 12: prox_mes = 1; prox_ano += 1
            ultimo_dia = datetime(prox_ano, prox_mes, 1) - timedelta(days=1)
            # Ajusta hora para pegar o dia inteiro no filtro
            primeiro_dia = primeiro_dia.replace(hour=0, minute=0, second=0)
            ultimo_dia = ultimo_dia.replace(hour=23, minute=59, second=59)

            labels.append(primeiro_dia.strftime("%b/%Y"))
            soma_entrada = self.get_soma(user_id, "entrada", inicio=primeiro_dia, fim=ultimo_dia)
            soma_gasto = self.get_soma(user_id, "gasto", inicio=primeiro_dia, fim=ultimo_dia)
            entradas_vals.append(float(soma_entrada))
            gastos_vals.append(float(soma_gasto))
        return labels, entradas_vals, gastos_vals

    def limpar_transacoes(self, user_id=None, opcao=None):
        query = self.collection_transacoes.where('user_id', '==', user_id)
        now = datetime.now()
        
        # Para deletar, precisamos buscar os docs primeiro
        docs_to_delete = []
        
        if opcao == "ultimo":
            # Pega todos, ordena e deleta o primeiro (ineficiente mas funciona)
            todos = self.get_todas(user_id) # Já vem ordenado reverso
            if todos:
                id_recente = todos[0][0] # Pega o ID
                self.collection_transacoes.document(id_recente).delete()
            return

        elif opcao == "dia":
            inicio = now.replace(hour=0, minute=0, second=0)
            query = query.where('data', '>=', inicio)
        elif opcao == "semana":
            semana_inicio = now - timedelta(days=now.weekday())
            semana_inicio = semana_inicio.replace(hour=0, minute=0, second=0)
            query = query.where('data', '>=', semana_inicio)
        elif opcao == "mes":
            primeiro_dia = now.replace(day=1, hour=0, minute=0, second=0)
            query = query.where('data', '>=', primeiro_dia)
        elif opcao == "tudo":
            pass # Já filtrou por user_id

        # Executa a query para achar os docs
        batch = self.db.batch()
        docs = query.stream()
        count = 0
        for doc in docs:
            batch.delete(doc.reference)
            count += 1
            if count >= 400: # Limite de batch do firebase é 500
                batch.commit()
                batch = self.db.batch()
                count = 0
        if count > 0:
            batch.commit()

    # --- CONFIG (HASH DO GIT) ---
    def get_config(self, key):
        doc = self.collection_config.document(key).get()
        if doc.exists:
            return doc.to_dict().get('value')
        return None

    def set_config(self, key, value):
        self.collection_config.document(key).set({'value': value})

# Instância Global
db = Database()