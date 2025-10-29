# -*- coding: utf-8 -*-
import os
import re
import io
import decimal
from decimal import Decimal
from datetime import datetime, timedelta
import asyncio

# Imports do Bot
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

# Imports dos Gráficos/Relatórios
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from openpyxl import Workbook
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- Import do Flask e Thread (Necessário para Render/Replit) ---
from flask import Flask
from threading import Thread
# ----------------------------------------

from db import db # importa a instância do db.py

# =======================
# CONFIGURAÇÃO ADMIN
# =======================
ADMIN_USER_ID = 853716041 # substitua pelo seu ID do Telegram

# ===================================================================
# --- MAPEAMENTO DE CATEGORIAS (Como definido anteriormente) ---
# ===================================================================
MAPEAMENTO_CATEGORIAS = {
    # --- GASTOS ---
    "Alimentação": ["supermercado", "mercado", "lanche", "churrasco", "restaurante", "ifood", "rappi", "padaria", "açougue", "hortifruti", "pizza", "comida", "jantar", "almoço", "café", "bebida"],
    "Transporte": ["gasolina", "uber", "99", "estacionamento", "ipva", "seguro", "carro", "manutenção", "onibus", "metrô", "passagem", "combustível", "pedagio", "taxi", "aplicativo", "app"],
    "Moradia": ["aluguel", "condomínio", "iptu", "luz", "água", "internet", "gás", "diarista", "faxina", "energia", "net", "claro", "vivo", "oi", "tim", "conserto", "reparo"],
    "Construção/Reforma": ["construção", "reforma", "material", "pedreiro", "tinta", "cimento", "leroy", "telhanorte", "ferramenta", "obra", "ferragens"],
    "Casa/Decoração": ["casa", "decoração", "móvel", "utensílio", "cama", "mesa", "banho", "eletrodoméstico", "manutenção", "casa", "jardinagem", "ikea", "tokstok"],
    "Saúde": ["farmácia", "remédio", "médico", "consulta", "plano", "saude", "exame", "dentista", "hospital", "terapia", "psicologo"],
    "Lazer/Entretenimento": ["lazer", "cinema", "show", "bar", "festa", "viagem", "hotel", "streaming", "netflix", "spotify", "hobby", "jogo", "steam", "passeio", "presente", "ingresso", "assinatura", "disney", "hbo"],
    "Educação": ["escola", "faculdade", "curso", "livro", "material", "escolar", "udemy", "mensalidade", "papelaria"],
    "Vestuário/Cuidados": ["roupa", "sapato", "tênis", "acessório", "vestido", "calça", "beleza", "cabelereiro", "cosmético", "perfume", "barbeiro"],
    "Dívidas/Contas": ["fatura", "empréstimo", "juros", "boleto", "imposto", "taxa", "ir", "multa", "cartorio"],
    "Pets": ["pet", "ração", "veterinário", "petshop", "cachorro", "gato"],
    # --- ENTRADAS ---
    "Salário": ["salário", "salario", "pagamento", "holerite"],
    "Vendas": ["venda", "cliente", "recebimento", "comissao"],
    "Investimentos": ["investimento", "ação", "ações", "b3", "fundo", "tesouro", "cdb", "cripto", "resgate", "dividendo", "jcp"],
    "Outras Entradas": ["entrada", "ganhei", "recebi", "pix", "reembolso", "presente"]
}

# =======================
# --- FUNÇÃO HELPER (Como definido anteriormente) ---
# =======================
def encontrar_categoria_por_palavra(palavras: list):
    for palavra in palavras:
        for categoria_pai, keywords in MAPEAMENTO_CATEGORIAS.items():
            if palavra in keywords: return categoria_pai
    return None

# =======================
# Função para formatar valores BR
# =======================
def formatar_valor(valor):
    try: valor_decimal = Decimal(valor)
    except (decimal.InvalidOperation, TypeError, ValueError): valor_decimal = Decimal("0.00")
    return f"{valor_decimal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# =======================
# Interpretação de mensagens (MODIFICADA)
# =======================
def interpretar_mensagem(texto: str):
    texto = texto.lower().strip()
    match = re.search(r"(\d[\d.,]*)", texto)
    if match:
        valor_txt = match.group(1).strip(); valor_num = Decimal("0.00")
        if not valor_txt: return {"acao": "desconhecido"}
        try: valor_num = Decimal(valor_txt.replace(".", "").replace(",", "."))
        except decimal.InvalidOperation: return {"acao": "desconhecido"}
        if valor_num <= 0: return {"acao": "desconhecido"}

        palavras = texto.split()
        palavras_texto = [p for p in palavras if valor_txt not in p]

        # --- Lógica de Cartão ---
        cartao = None; metodo = "dinheiro"; cartoes_lista = ["nubank", "santander", "inter", "caixa"]; stop_words_cartao = cartoes_lista + ["cartão", "cartao"]
        for c in cartoes_lista:
            if c in palavras_texto: cartao = c.capitalize(); metodo = "cartao"; break
        if cartao is None:
            idx = -1
            if "cartão" in palavras_texto: idx = palavras_texto.index("cartão")
            elif "cartao" in palavras_texto: idx = palavras_texto.index("cartao")
            if idx != -1:
                metodo = "cartao"; nome_cartao_palavras = []
                temp_stop_words = stop_words_cartao + list(MAPEAMENTO_CATEGORIAS.keys())
                for i in range(idx + 1, len(palavras_texto)):
                    if palavras_texto[i] not in temp_stop_words: nome_cartao_palavras.append(palavras_texto[i])
                    else: break
                if nome_cartao_palavras: cartao = " ".join(nome_cartao_palavras).capitalize()
                else: cartao = "Cartão"
        # --- Fim Cartão ---

        # --- Determina Tipo e Categoria ---
        entradas_keywords = [kw for cat, kws in MAPEAMENTO_CATEGORIAS.items() if cat in ["Salário", "Vendas", "Outras Entradas", "Investimentos"] for kw in kws]
        is_entrada = any(p in entradas_keywords for p in palavras_texto)

        if is_entrada:
            categoria_mapeada = encontrar_categoria_por_palavra(palavras_texto)
            categoria_final = categoria_mapeada if categoria_mapeada else "Entrada"
            return {"acao": "add", "tipo": "entrada", "valor_num": valor_num, "valor_txt": valor_txt, "categoria": categoria_final.capitalize(), "metodo": metodo, "cartao": cartao}
        else:
            categoria_mapeada = encontrar_categoria_por_palavra(palavras_texto)
            categoria_final = None
            if categoria_mapeada:
                categoria_final = categoria_mapeada
            else:
                stop_words_fallback = stop_words_cartao
                if cartao: stop_words_fallback.extend(cartao.lower().split())
                categoria_primeira_palavra = next((p for p in palavras_texto if p.isalpha() and p not in stop_words_fallback), "Outros")
                categoria_final = categoria_primeira_palavra.capitalize()
            return {"acao": "add", "tipo": "gasto", "valor_num": valor_num, "valor_txt": valor_txt, "categoria": categoria_final.capitalize(), "metodo": metodo, "cartao": cartao}
    return {"acao": "desconhecido"}


# ==========================================================
# --- MODIFICAÇÃO 1: Adicionar botão ao Teclado Flutuante ---
# ==========================================================
def teclado_flutuante(user_id):
    entradas = db.get_soma(user_id, "entrada"); gastos = db.get_soma(user_id, "gasto"); saldo = entradas - gastos
    status = "🟢😀 Finanças Saudáveis"
    if saldo < 0: status = "🔴😟 Saldo Negativo"
    elif entradas > 0 and (gastos / entradas) > Decimal("0.7"): status = "🟠🤔 Gastos altos!"
    teclado = [
        [status],
        ["🧾 Saldo Geral", "💳 Gastos por Cartão"],
        ["💰 Ver Entradas (Tudo)", "💸 Ver Saídas (Tudo)"],
        ["🧾 Filtrar Extrato", "📊 Filtrar por Categoria"], # <-- BOTÃO ADICIONADO AQUI
        ["📊 Gráfico Pizza", "📊 Gráfico Barras"],
        ["📑 Gerar PDF", "📊 Gerar XLSX", "🔄 Resetar Valores"]
    ]
    if user_id == ADMIN_USER_ID: teclado.append(["👁️ Ver Usuários"])
    return ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=False)

def teclado_admin_usuario_selecionado():
    teclado = [["💰 Entradas", "💸 Saídas"], ["🧾 Saldo Geral"], ["📑 Gerar PDF", "📊 Gerar XLSX"], ["⬅️ Voltar"]]
    return ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=False)

def teclado_filtros_periodo():
    teclado = [["Hoje", "Esta Semana", "Este Mês"], ["Mês Passado", "Este Ano"], ["Cancelar"]]
    return ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=True)

# =======================
# Funções de Gráficos, PDF, XLSX, etc. (Sem alterações)
# =======================
def grafico_gastos_pizza(user_id=None, inicio=None, fim=None):
    rows = db.gastos_por_categoria(user_id=user_id, inicio=inicio, fim=fim)
    if not rows: return None
    labels = [r[0] for r in rows]; valores = [float(r[1]) for r in rows]; fig, ax = plt.subplots()
    ax.pie(valores, labels=labels, autopct="%1.1f%%", startangle=90); ax.set_title("Gastos por Categoria")
    buf = io.BytesIO(); plt.savefig(buf, format="png", bbox_inches="tight"); buf.seek(0); plt.close(fig); return buf

def grafico_mensal_barras(user_id=None, meses=6):
    labels, entradas_vals, gastos_vals = db.series_mensais(user_id=user_id, meses=meses)
    if not labels: return None
    x = list(range(len(labels))); fig, ax = plt.subplots(); width = 0.4
    ax.bar([i - width/2 for i in x], entradas_vals, width=width, label="Entradas", align="center")
    ax.bar([i + width/2 for i in x], gastos_vals, width=width, label="Gastos", align="center")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=45); ax.set_ylabel("R$")
    ax.set_title("Entradas x Gastos por Mês"); ax.legend(); fig.tight_layout()
    buf = io.BytesIO(); plt.savefig(buf, format="png", bbox_inches="tight"); buf.seek(0); plt.close(fig); return buf

def gerar_pdf(user_id=None, filename="relatorio.pdf", inicio=None, fim=None):
    doc = SimpleDocTemplate(filename); styles = getSampleStyleSheet(); story = []
    entradas = db.get_soma(user_id, "entrada", inicio=inicio, fim=fim); gastos = db.get_soma(user_id, "gasto", inicio=inicio, fim=fim); saldo = entradas - gastos
    story.append(Paragraph("📑 Relatório Financeiro", styles["Title"])); story.append(Spacer(1, 20))
    story.append(Paragraph(f"Entradas: R$ {formatar_valor(entradas)}", styles["Normal"])); story.append(Paragraph(f"Gastos: R$ {formatar_valor(gastos)}", styles["Normal"]))
    story.append(Paragraph(f"Saldo: R$ {formatar_valor(saldo)}", styles["Normal"])); story.append(Spacer(1, 20))
    story.append(Paragraph("💰 Entradas:", styles["Heading2"]))
    trans_e = db.get_todas(user_id=user_id, tipo="entrada", inicio=inicio, fim=fim)
    for t in trans_e: story.append(Paragraph(f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}", styles["Normal"]))
    story.append(Spacer(1, 20)); story.append(Paragraph("💸 Saídas:", styles["Heading2"]))
    trans_s = db.get_todas(user_id=user_id, tipo="gasto", inicio=inicio, fim=fim)
    for t in trans_s: story.append(Paragraph(f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}", styles["Normal"]))
    doc.build(story); return filename

def gerar_xlsx(user_id=None, filename="relatorio.xlsx", inicio=None, fim=None):
    wb = Workbook(); ws = wb.active; ws.title = "Relatório"; ws.append(["Tipo", "Valor", "Categoria", "Método", "Cartão", "Data"])
    transacoes = db.get_todas(user_id=user_id, inicio=inicio, fim=fim)
    for t in transacoes:
        try: valor_num = Decimal(t[2])
        except (decimal.InvalidOperation, TypeError, ValueError): valor_num = Decimal("0.00")
        ws.append([t[1], valor_num, t[3], t[4], t[5] or "Dinheiro", t[6]])
    entradas = db.get_soma(user_id, "entrada", inicio=inicio, fim=fim); gastos = db.get_soma(user_id, "gasto", inicio=inicio, fim=fim); saldo = entradas - gastos
    ws.append([]); ws.append(["Entradas", entradas]); ws.append(["Gastos", gastos]); ws.append(["Saldo", saldo])
    num_format = 'R$ #,##0.00'; max_row = ws.max_row
    for cell in ws['B']: cell.number_format = num_format
    ws[f'B{max_row-2}'].number_format = num_format; ws[f'B{max_row-1}'].number_format = num_format; ws[f'B{max_row}'].number_format = num_format
    wb.save(filename); return filename

def gastos_por_cartao(user_id):
    rows = db.get_gastos_por_cartao(user_id=user_id)
    if not rows: return "💳 Gastos por Cartão:\nNenhum gasto registrado."
    texto = "💳 Gastos por Cartão:\n";
    for r in rows: texto += f"▪️ {r[0]}: R$ {formatar_valor(r[1])}\n"
    return texto

def verificar_alerta(user_id):
    entradas = db.get_soma(user_id, "entrada"); gastos = db.get_soma(user_id, "gasto"); saldo = entradas - gastos
    status = None
    if saldo < 0: status = "🔴😟 Saldo Negativo"
    elif entradas > 0 and (gastos / entradas) > Decimal("0.7"): status = "🟠🤔 Gastos altos!"
    if status: return (f"{status}\n💰 Entradas: R$ {formatar_valor(entradas)}\n💸 Gastos: R$ {formatar_valor(gastos)}\n📌 Saldo: R$ {formatar_valor(saldo)}")
    return None

async def enviar_extrato_filtrado(update: Update, context: ContextTypes.DEFAULT_TYPE, inicio: datetime, fim: datetime, titulo_periodo: str):
    user_id = update.message.from_user.id
    entradas = db.get_todas(user_id, tipo="entrada", inicio=inicio, fim=fim)
    saidas = db.get_todas(user_id, tipo="gasto", inicio=inicio, fim=fim)
    entradas_filtradas = [t for t in entradas if Decimal(t[2]) > 0]; saidas_filtradas = [t for t in saidas if Decimal(t[2]) > 0]
    total_entradas = db.get_soma(user_id, "entrada", inicio=inicio, fim=fim); total_gastos = db.get_soma(user_id, "gasto", inicio=inicio, fim=fim); saldo_periodo = total_entradas - total_gastos
    texto = f"🧾 Extrato Filtrado: *{titulo_periodo}*\n\n"
    if not entradas_filtradas and not saidas_filtradas: texto += "Nenhuma transação neste período."
    else:
        if entradas_filtradas:
            texto += "--- *Entradas* ---\n";
            for t in entradas_filtradas: texto += f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[6]}\n"
            texto += "\n"
        if saidas_filtradas:
            texto += "--- *Saídas* ---\n"
            for t in saidas_filtradas: texto += f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}\n"
            texto += "\n"
        texto += "--- *Resumo do Período* ---\n"; texto += f"💰 Total Entradas: R$ {formatar_valor(total_entradas)}\n"; texto += f"💸 Total Gastos: R$ {formatar_valor(total_gastos)}\n"; texto += f"📌 Saldo Período: R$ {formatar_valor(saldo_periodo)}\n"
    await update.message.reply_text(texto, parse_mode='Markdown', reply_markup=teclado_flutuante(user_id))

# ==========================================================
# --- MODIFICAÇÃO 2: Nova Função de Filtragem por Categoria ---
# ==========================================================
async def enviar_extrato_por_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE, categoria_desejada: str):
    """Busca transações no DB e filtra pela categoria em Python."""
    user_id = update.message.from_user.id
    # Normaliza a categoria digitada para comparação
    categoria_lower = categoria_desejada.lower().strip()

    # 1. Buscar TODAS as transações do usuário
    #    (get_todas já retorna ordenado por ID DESC - mais novos primeiro)
    entradas_todas = db.get_todas(user_id, tipo="entrada")
    saidas_todas = db.get_todas(user_id, tipo="gasto")

    # 2. Filtrar pela categoria (em Python) e remover valores zero
    #    Índice t[3] é a coluna 'categoria' no retorno de get_todas
    #    Índice t[2] é a coluna 'valor_num'
    entradas_filtradas = [t for t in entradas_todas if t[3].lower() == categoria_lower and Decimal(t[2]) > 0]
    saidas_filtradas = [t for t in saidas_todas if t[3].lower() == categoria_lower and Decimal(t[2]) > 0]

    # 3. Calcular somas APENAS das transações filtradas
    total_entradas = sum(Decimal(t[2]) for t in entradas_filtradas)
    total_gastos = sum(Decimal(t[2]) for t in saidas_filtradas)
    saldo_categoria = total_entradas - total_gastos # Saldo específico desta categoria

    # 4. Construir a mensagem
    # Usa capitalize() para mostrar o nome da categoria com a primeira letra maiúscula
    texto = f"🧾 Extrato Filtrado: *Categoria: {categoria_desejada.capitalize()}*\n\n"

    if not entradas_filtradas and not saidas_filtradas:
        texto += "Nenhuma transação encontrada para esta categoria."
        await update.message.reply_text(texto, parse_mode='Markdown', reply_markup=teclado_flutuante(user_id))
        return

    # Seção de Entradas (se houver)
    if entradas_filtradas:
        texto += "--- *Entradas* ---\n"
        for t in entradas_filtradas:
            # Indices: 2=valor, 3=categoria, 6=data
            texto += f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[6]}\n"
        texto += "\n"

    # Seção de Saídas (se houver)
    if saidas_filtradas:
        texto += "--- *Saídas* ---\n"
        for t in saidas_filtradas:
             # Indices: 2=valor, 3=categoria, 5=cartao, 6=data
            texto += f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}\n"
        texto += "\n"

    # Resumo da Categoria
    texto += f"--- *Resumo da Categoria: {categoria_desejada.capitalize()}* ---\n"
    texto += f"💰 Total Entradas: R$ {formatar_valor(total_entradas)}\n"
    texto += f"💸 Total Gastos: R$ {formatar_valor(total_gastos)}\n"
    texto += f"📌 Saldo Categoria: R$ {formatar_valor(saldo_categoria)}\n"

    await update.message.reply_text(texto, parse_mode='Markdown', reply_markup=teclado_flutuante(user_id))

# =======================
# Handlers
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; user_name = update.message.from_user.first_name
    await update.message.reply_text(f"Olá, {user_name}! Bem-vindo(a).\n"
                                     "Digite valor + descrição (ex: '150 mercado').\n"
                                     "Use o teclado para outras opções:",
                                     reply_markup=teclado_flutuante(user_id))

# ==========================================================
# --- MODIFICAÇÃO 3: Adicionar lógica ao Responder ---
# ==========================================================
async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; user_name = update.message.from_user.first_name
    msg = update.message.text

    # --- NOVO BLOCO 1: Capturar resposta do filtro por categoria ---
    if 'aguardando_filtro_categoria' in context.user_data:
        del context.user_data['aguardando_filtro_categoria'] # Limpa o estado
        categoria_digitada = msg.strip()
        # Validação simples para evitar chamar a função com "Cancelar"
        if categoria_digitada.lower() != "cancelar":
            await enviar_extrato_por_categoria(update, context, categoria_digitada)
        else:
             await update.message.reply_text("Filtro por categoria cancelado.", reply_markup=teclado_flutuante(user_id))
        return # Impede que o resto da função seja executado
    # --- Fim Novo Bloco 1 ---

    # --- Handlers Voltar/Cancelar padrão ---
    if msg == "⬅️ Voltar" and user_id == ADMIN_USER_ID:
        if "admin_selecionado" in context.user_data: del context.user_data["admin_selecionado"]
        await update.message.reply_text("Voltando...", reply_markup=teclado_flutuante(user_id)); return
    if msg == "Cancelar":
        # Cancela filtro de período ou categoria (se houver)
        if 'aguardando_filtro' in context.user_data: del context.user_data['aguardando_filtro']
        # Adicionado para cancelar o filtro de categoria também
        if 'aguardando_filtro_categoria' in context.user_data: del context.user_data['aguardando_filtro_categoria']
        await update.message.reply_text("Ação cancelada.", reply_markup=teclado_flutuante(user_id)); return

    # --- Bloco Admin (Sem alterações) ---
    if user_id == ADMIN_USER_ID and "admin_selecionado" in context.user_data:
        selecionado_id, selecionado_nome = context.user_data["admin_selecionado"]
        if 'aguardando_filtro' in context.user_data: del context.user_data['aguardando_filtro']
        if msg == "💰 Entradas":
            transacoes = db.get_todas(user_id=selecionado_id, tipo="entrada"); filtradas = [t for t in transacoes if Decimal(t[2]) > 0]
            texto = f"💰 Entradas de {selecionado_nome}\n" + "\n".join([f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}" for t in filtradas]);
            if not filtradas: texto = f"{selecionado_nome} não tem entradas."; await update.message.reply_text(texto, reply_markup=teclado_admin_usuario_selecionado())
        elif msg == "💸 Saídas":
            transacoes = db.get_todas(user_id=selecionado_id, tipo="gasto"); filtradas = [t for t in transacoes if Decimal(t[2]) > 0]
            texto = f"💸 Saídas de {selecionado_nome}\n" + "\n".join([f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}" for t in filtradas]);
            if not filtradas: texto = f"{selecionado_nome} não tem saídas."; await update.message.reply_text(texto, reply_markup=teclado_admin_usuario_selecionado())
        elif msg == "🧾 Saldo Geral":
            entradas = db.get_soma(selecionado_id, "entrada"); gastos = db.get_soma(selecionado_id, "gasto"); saldo = entradas - gastos
            await update.message.reply_text(f"Saldo de {selecionado_nome}\n💰 Entradas: R$ {formatar_valor(entradas)}\n💸 Gastos: R$ {formatar_valor(gastos)}\n📌 Saldo: R$ {formatar_valor(saldo)}", reply_markup=teclado_admin_usuario_selecionado())
        elif msg == "📑 Gerar PDF": filename = gerar_pdf(selecionado_id, f"rel_{selecionado_id}.pdf"); await update.message.reply_document(open(filename, "rb"), caption=f"PDF de {selecionado_nome}", reply_markup=teclado_admin_usuario_selecionado()); os.remove(filename)
        elif msg == "📊 Gerar XLSX": filename = gerar_xlsx(selecionado_id, f"rel_{selecionado_id}.xlsx"); await update.message.reply_document(open(filename, "rb"), caption=f"XLSX de {selecionado_nome}", reply_markup=teclado_admin_usuario_selecionado()); os.remove(filename)
        else: await update.message.reply_text("Inválido.", reply_markup=teclado_admin_usuario_selecionado())
        return

    # --- Resposta Filtro Período (Sem alterações) ---
    if 'aguardando_filtro' in context.user_data:
        del context.user_data['aguardando_filtro']; hoje = datetime.now()
        if msg == "Hoje": inicio = fim = hoje
        elif msg == "Esta Semana": inicio = hoje - timedelta(days=hoje.weekday()); fim = inicio + timedelta(days=6)
        elif msg == "Este Mês": inicio = hoje.replace(day=1); fim = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        elif msg == "Mês Passado": fim = hoje.replace(day=1) - timedelta(days=1); inicio = fim.replace(day=1)
        elif msg == "Este Ano": inicio = hoje.replace(day=1, month=1); fim = hoje.replace(day=31, month=12)
        else: await update.message.reply_text("Filtro cancelado.", reply_markup=teclado_flutuante(user_id)); return
        await enviar_extrato_filtrado(update, context, inicio, fim, msg); return

    # --- Lógica Usuário Comum ---
    if msg == "🔄 Resetar Valores": await update.message.reply_text("Período para resetar:", reply_markup=ReplyKeyboardMarkup([["Último valor", "Hoje"], ["Última semana", "Este mês"], ["Tudo"], ["Cancelar"]], resize_keyboard=True, one_time_keyboard=True)); return
    elif msg in ["Último valor", "Hoje", "Última semana", "Este mês", "Tudo"]: mapa = {"Último valor":"ultimo","Hoje":"dia","Última semana":"semana","Este mês":"mes","Tudo":"tudo"}; db.limpar_transacoes(user_id, mapa[msg]); await update.message.reply_text(f"✅ Removido ({msg})", reply_markup=teclado_flutuante(user_id)); return

    if msg == "📊 Gráfico Pizza": buf = grafico_gastos_pizza(user_id); await update.message.reply_photo(buf, caption="💸 Gastos por Categoria", reply_markup=teclado_flutuante(user_id)) if buf else await update.message.reply_text("Nenhum gasto.", reply_markup=teclado_flutuante(user_id)); return
    if msg == "📊 Gráfico Barras": buf = grafico_mensal_barras(user_id); await update.message.reply_photo(buf, caption="📊 Entradas x Gastos", reply_markup=teclado_flutuante(user_id)) if buf else await update.message.reply_text("Nenhuma transação.", reply_markup=teclado_flutuante(user_id)); return

    if msg == "💰 Ver Entradas (Tudo)": transacoes = db.get_todas(user_id=user_id, tipo="entrada"); filtradas = [t for t in transacoes if Decimal(t[2]) > 0]; await update.message.reply_text("Nenhuma entrada.", reply_markup=teclado_flutuante(user_id)) if not filtradas else await update.message.reply_text("💰 Entradas:\n" + "\n".join([f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[6]}" for t in filtradas]), reply_markup=teclado_flutuante(user_id)); return
    if msg == "💸 Ver Saídas (Tudo)": transacoes = db.get_todas(user_id=user_id, tipo="gasto"); filtradas = [t for t in transacoes if Decimal(t[2]) > 0]; await update.message.reply_text("Nenhuma saída.", reply_markup=teclado_flutuante(user_id)) if not filtradas else await update.message.reply_text("💸 Saídas:\n" + "\n".join([f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}" for t in filtradas]), reply_markup=teclado_flutuante(user_id)); return

    if msg == "🧾 Filtrar Extrato": context.user_data['aguardando_filtro'] = True; await update.message.reply_text("Selecione o período:", reply_markup=teclado_filtros_periodo()); return

    # --- NOVO BLOCO 2: Capturar clique no botão de filtro por categoria ---
    if msg == "📊 Filtrar por Categoria":
        context.user_data['aguardando_filtro_categoria'] = True
        # Mostra um teclado simples apenas com "Cancelar" enquanto espera a categoria
        await update.message.reply_text(
            "Digite o nome da categoria que deseja filtrar (ex: Alimentação, Transporte, Salário):",
            reply_markup=ReplyKeyboardMarkup([["Cancelar"]], resize_keyboard=True, one_time_keyboard=True)
        )
        return
    # --- Fim Novo Bloco 2 ---

    if msg == "💳 Gastos por Cartão": texto = gastos_por_cartao(user_id); await update.message.reply_text(texto, reply_markup=teclado_flutuante(user_id)); return
    if msg == "🧾 Saldo Geral":
        entradas = db.get_soma(user_id, "entrada"); gastos = db.get_soma(user_id, "gasto"); saldo = entradas - gastos
        status = "🟢😀 Saudável";
        if saldo < 0: status = "🔴😟 Negativo"
        elif entradas > 0 and (gastos / entradas) > Decimal("0.7"): status = "🟠🤔 Gastos altos!"
        await update.message.reply_text((f"🧾 Saldo Geral\n💰 Entradas: R$ {formatar_valor(entradas)}\n💸 Gastos: R$ {formatar_valor(gastos)}\n📌 Saldo: R$ {formatar_valor(saldo)}\n\nStatus: {status}"), reply_markup=teclado_flutuante(user_id)); return

    if msg == "📑 Gerar PDF": filename = gerar_pdf(user_id); await update.message.reply_document(open(filename, "rb"), reply_markup=teclado_flutuante(user_id)); os.remove(filename); return
    if msg == "📊 Gerar XLSX": filename = gerar_xlsx(user_id); await update.message.reply_document(open(filename, "rb"), reply_markup=teclado_flutuante(user_id)); os.remove(filename); return

    # --- Lógica Admin (Listar/Selecionar) ---
    if msg == "👁️ Ver Usuários" and user_id == ADMIN_USER_ID: usuarios = db.listar_usuarios(); await update.message.reply_text("Nenhum usuário.", reply_markup=teclado_flutuante(user_id)) if not usuarios else await update.message.reply_text("Gerenciar usuário:", reply_markup=ReplyKeyboardMarkup([[f"{u[0]} - {u[1]}"] for u in usuarios] + [["⬅️ Voltar"]], resize_keyboard=True, one_time_keyboard=True)); return
    if user_id == ADMIN_USER_ID and " - " in msg and msg.split(" - ")[0].isdigit(): selecionado_id = int(msg.split(" - ")[0]); selecionado_nome = msg.split(" - ")[1]; context.user_data["admin_selecionado"] = (selecionado_id, selecionado_nome); await update.message.reply_text(f"Gerenciando: {selecionado_nome}.", reply_markup=teclado_admin_usuario_selecionado()); return

    # --- Interpretação de Mensagem (Adicionar transação) ---
    resultado = interpretar_mensagem(msg)
    if resultado["acao"] == "add":
        # A categoria já vem mapeada (ex: "Alimentação") da função interpretar_mensagem
        db.add_transacao(user_id, resultado["tipo"], resultado["valor_num"], resultado["valor_txt"], resultado["categoria"], resultado["metodo"], resultado["cartao"], user_name)
        msg_resp = f"✅ {resultado['tipo'].capitalize()} R$ {formatar_valor(resultado['valor_num'])} (Cat: {resultado['categoria']})"
        if resultado['cartao']: msg_resp += f"\n💳 Cartão: {resultado['cartao']}"
        alerta = verificar_alerta(user_id)
        if alerta: msg_resp += f"\n\n{alerta}"
        await update.message.reply_text(msg_resp, reply_markup=teclado_flutuante(user_id))
    else:
        await update.message.reply_text("❌ Não entendi. Digite valor + descrição (ex: '50 lanche').", reply_markup=teclado_flutuante(user_id))

# =======================
# Inicialização do Bot (VERSÃO FINAL E CORRIGIDA - Sem alterações aqui)
# =======================
TOKEN = os.environ.get('BOT_TOKEN') # Lê o token dos "Secrets"
app = None # Variável global para o app do Telegram
if not TOKEN: print("ERRO CRÍTICO: Token não encontrado.")
else:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    print("🤖 Bot configurado.")

# --- CÓDIGO DO SERVIDOR FLASK (Sem alterações aqui) ---
app_flask = Flask('')
@app_flask.route('/')
def home(): return "Estou vivo!"

def run_telegram_bot():
    print("🤖 Bot do Telegram rodando em background.")
    try: app.run_polling(stop_signals=None)
    except Exception as e: print(f"!!! ERRO FATAL NO POLLING: {e} !!!")

def run_flask_and_bot():
    if not app: return
    print("Iniciando Bot e Servidor...")
    thread_bot = Thread(target=run_telegram_bot, daemon=True)
    thread_bot.start()
    print("\n--- INICIANDO FLASK ---")
    try:
        from waitress import serve
        print("--- Waitress na porta 8080 ---")
        serve(app_flask, host='0.0.0.0', port=8080)
    except ImportError:
        print("--- Fallback Flask na porta 8080 ---")
        app_flask.run(host='0.0.0.0', port=8080)
    except Exception as e: print(f"!!! ERRO FLASK: {e} !!!")

if __name__ == "__main__":
    run_flask_and_bot()