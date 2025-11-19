import os
import json
from datetime import datetime, timedelta
from decimal import Decimal
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
# Import novo para corrigir o aviso "UserWarning"
from google.cloud.firestore_v1.base_query import FieldFilter 
import pytz

# Configuração de Fuso Horário
LOCAL_TIMEZONE = pytz.timezone('America/Sao_Paulo')

class Database:
    def __init__(self):
        if not firebase_admin._apps:
            json_config = os.environ.get('FIREBASE_CREDENTIALS')
            if not json_config:
                raise ValueError("Erro: A variável FIREBASE_CREDENTIALS não está configurada.")
            
            cred_dict = json.loads(json_config)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        self.collection_transacoes = self.db.collection('transacoes')
        self.collection_usuarios = self.db.collection('usuarios')
        self.collection_config = self.db.collection('app_config')

    # --- USUÁRIOS ---
    def listar_usuarios(self):
        docs = self.collection_usuarios.stream()
        return [int(doc.id) for doc in docs]

    def listar_usuarios_com_nome(self):
        docs = self.collection_usuarios.stream()
        lista = []
        for doc in docs:
            dados = doc.to_dict()
            try:
                uid = int(doc.id)
                nome = dados.get('nome', f"Usuário {uid}")
                lista.append((uid, nome))
            except: pass
        return lista

    # --- TRANSAÇÕES ---
    def add_transacao(self, user_id, tipo, valor_num, valor_txt, categoria, descricao, metodo="dinheiro", cartao=None, nome=""):
        self.collection_usuarios.document(str(user_id)).set({
            'user_id': user_id,
            'nome': nome
        }, merge=True)

        dados = {
            'user_id': user_id,
            'tipo': tipo,
            'valor_num': float(valor_num), 
            'valor_txt': valor_txt,
            'categoria': categoria,
            'descricao': descricao,
            'metodo': metodo,
            'cartao': cartao,
            'data': datetime.now()
        }
        self.collection_transacoes.add(dados)

    # --- LEITURA DE DADOS ---
    def get_soma(self, user_id, tipo, inicio=None, fim=None):
        # Correção dos Warnings: Usando FieldFilter
        query = self.collection_transacoes
        query = query.where(filter=FieldFilter('user_id', '==', user_id))
        query = query.where(filter=FieldFilter('tipo', '==', tipo))
        
        if inicio: query = query.where(filter=FieldFilter('data', '>=', inicio))
        if fim: query = query.where(filter=FieldFilter('data', '<=', fim))

        docs = query.stream()
        total = 0.0
        for doc in docs:
            total += doc.to_dict().get('valor_num', 0.0)
        
        return Decimal(f"{total:.2f}")

    def get_todas(self, user_id=None, tipo=None, inicio=None, fim=None):
        query = self.collection_transacoes
        
        if user_id: query = query.where(filter=FieldFilter('user_id', '==', user_id))
        if tipo: query = query.where(filter=FieldFilter('tipo', '==', tipo))
        if inicio: query = query.where(filter=FieldFilter('data', '>=', inicio))
        if fim: query = query.where(filter=FieldFilter('data', '<=', fim))
            
        docs = query.stream()
        
        resultados = []
        for doc in docs:
            d = doc.to_dict()
            dt = d.get('data')
            if dt and hasattr(dt, 'timestamp'):
                 dt = datetime.fromtimestamp(dt.timestamp())

            linha = [
                doc.id,             # 0
                d.get('tipo'),      # 1
                d.get('valor_num'), # 2
                d.get('categoria'), # 3
                d.get('metodo'),    # 4
                d.get('cartao'),    # 5
                dt,                 # 6
                d.get('descricao')  # 7
            ]
            resultados.append(linha)
            
        resultados.sort(key=lambda x: x[6] if x[6] else datetime.min, reverse=True)
        return resultados

    def gastos_por_categoria(self, user_id=None, inicio=None, fim=None):
        transacoes = self.get_todas(user_id, tipo='gasto', inicio=inicio, fim=fim)
        agrupado = {}
        for t in transacoes:
            cat = t[3]
            val = t[2] 
            if cat not in agrupado: agrupado[cat] = 0.0
            agrupado[cat] += float(val)
        return [(k, v) for k, v in agrupado.items()]

    def get_gastos_por_cartao(self, user_id=None):
        transacoes = self.get_todas(user_id, tipo='gasto')
        agrupado = {}
        for t in transacoes:
            cartao = t[5]
            val = t[2]
            if cartao: 
                if cartao not in agrupado: agrupado[cartao] = 0.0
                agrupado[cartao] += float(val)
        return [(k, v) for k, v in agrupado.items()]

    def series_mensais(self, user_id=None, meses=6):
        hoje = datetime.now(); labels = []; entradas_vals = []; gastos_vals = []
        for i in reversed(range(meses)):
            mes_alvo = hoje.month - i; ano_alvo = hoje.year
            if mes_alvo <= 0: mes_alvo += 12; ano_alvo -= 1
            primeiro_dia = datetime(ano_alvo, mes_alvo, 1, 0, 0, 0)
            prox_mes = mes_alvo + 1; prox_ano = ano_alvo
            if prox_mes > 12: prox_mes = 1; prox_ano += 1
            ultimo_dia = datetime(prox_ano, prox_mes, 1, 23, 59, 59) - timedelta(days=1)

            labels.append(primeiro_dia.strftime("%b/%Y"))
            soma_entrada = self.get_soma(user_id, "entrada", inicio=primeiro_dia, fim=ultimo_dia)
            soma_gasto = self.get_soma(user_id, "gasto", inicio=primeiro_dia, fim=ultimo_dia)
            entradas_vals.append(float(soma_entrada))
            gastos_vals.append(float(soma_gasto))
        return labels, entradas_vals, gastos_vals

    def limpar_transacoes(self, user_id=None, opcao=None):
        query = self.collection_transacoes.where(filter=FieldFilter('user_id', '==', user_id))
        now = datetime.now()
        
        if opcao == "ultimo":
            todos = self.get_todas(user_id) 
            if todos:
                id_recente = todos[0][0] 
                self.collection_transacoes.document(id_recente).delete()
            return

        elif opcao == "dia":
            inicio = now.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.where(filter=FieldFilter('data', '>=', inicio))
        elif opcao == "semana":
            semana_inicio = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.where(filter=FieldFilter('data', '>=', semana_inicio))
        elif opcao == "mes":
            primeiro_dia = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            query = query.where(filter=FieldFilter('data', '>=', primeiro_dia))

        batch = self.db.batch()
        docs = query.stream()
        count = 0
        for doc in docs:
            batch.delete(doc.reference)
            count += 1
            if count >= 400: 
                batch.commit()
                batch = self.db.batch()
                count = 0
        if count > 0:
            batch.commit()

    # --- CONFIG ---
    def get_config(self, key):
        doc = self.collection_config.document(key).get()
        if doc.exists:
            return doc.to_dict().get('value')
        return None

    def set_config(self, key, value):
        self.collection_config.document(key).set({'value': value})

# Instância Global
db = Database()