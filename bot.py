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
import matplotlib       # <-- ADICIONE ESTA LINHA
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- NOVAS LINHAS PARA HOSPEDAGEM REPLIT ---
from flask import Flask
from threading import Thread
# ----------------------------------------

from db import db # importa a instância do db.py

# =======================
# CONFIGURAÇÃO ADMIN
# =======================
ADMIN_USER_ID = 853716041 # substitua pelo seu ID do Telegram

# =======================
# Função para formatar valores BR
# =======================
def formatar_valor(valor):
    """
    Recebe Decimal ou float e retorna string no formato BR: 15.000,00
    Esta função já está correta e garante as duas casas decimais.
    """
    try:
        valor_decimal = Decimal(valor)
    except (decimal.InvalidOperation, TypeError, ValueError):
        valor_decimal = Decimal("0.00")

    # :.2f garante as duas casas decimais (ex: 2,00 e 200,00)
    return f"{valor_decimal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# =======================
# Interpretação de mensagens
# =======================
def interpretar_mensagem(texto: str):
    """
    Interpreta a mensagem do usuário (escrita livre).
    *** CORRIGIDA PARA ACEITAR NOVOS NOMES DE CARTÕES ***
    """
    texto = texto.lower().strip()
    match = re.search(r"(\d[\d.,]*)", texto)
    if match:
        valor_txt = match.group(1).strip()

        if not valor_txt:
            return {"acao": "desconhecido"}

        try:
            valor_num = Decimal(valor_txt.replace(".", "").replace(",", "."))
        except decimal.InvalidOperation:
            return {"acao": "desconhecido"}

        # Rejeita transações com valor 0 ou negativas
        if valor_num <= 0:
            return {"acao": "desconhecido"}


        palavras = texto.split()
        # Remove o valor da lista de palavras para facilitar a análise
        palavras_texto = [p for p in palavras if valor_txt not in p]

        cartao = None
        metodo = "dinheiro"
        # Lista de cartões conhecidos (pode adicionar mais)
        cartoes_lista = ["nubank", "santander", "inter", "caixa"]
        # Palavras-chave de entrada
        entradas_lista = ["salário", "entrada", "ganhei", "recebi", "pix", "venda"]
        # Palavras que definem categoria mas não são o nome do cartão
        stop_words = cartoes_lista + entradas_lista + ["cartão", "cartao"]

        # --- LÓGICA DE CARTÃO ATUALIZADA ---

        # 1. Procura por cartões conhecidos
        for c in cartoes_lista:
            if c in palavras_texto:
                cartao = c.capitalize()
                metodo = "cartao"
                break

        # 2. Se não achou, procura pela palavra "cartão"
        if cartao is None:
            idx = -1
            if "cartão" in palavras_texto:
                idx = palavras_texto.index("cartão")
            elif "cartao" in palavras_texto:
                idx = palavras_texto.index("cartao")

            if idx != -1: # Encontrou a palavra "cartão"
                metodo = "cartao"
                # Pega as palavras *depois* de "cartão"
                nome_cartao_palavras = []
                for i in range(idx + 1, len(palavras_texto)):
                    # Se a palavra seguinte não for uma categoria ou stop word, é parte do nome
                    if palavras_texto[i] not in stop_words:
                        nome_cartao_palavras.append(palavras_texto[i])
                    else:
                        break # Para se achar uma palavra de categoria (ex: "salário")

                if nome_cartao_palavras:
                    cartao = " ".join(nome_cartao_palavras).capitalize() # Ex: "Banco do brasil"
                else:
                    cartao = "Cartão" # Se o usuário digitou só "5000 cartão"

        # --- Fim da Lógica de Cartão ---

        # 3. Determina o Tipo (Entrada vs. Gasto)
        if any(p in texto for p in entradas_lista):
            # É uma entrada
            categoria = "entrada" # Categoria principal
            if "salário" in palavras_texto: categoria = "salário"
            if "venda" in palavras_texto: categoria = "venda"

            return {"acao": "add", "tipo": "entrada", "valor_num": valor_num, "valor_txt": valor_txt,
                    "categoria": categoria, "metodo": metodo, "cartao": cartao}
        else:
            # É um gasto
            # Adiciona o nome do cartão (se houver) às stopwords para não virar categoria
            if cartao:
                # Adiciona partes do nome do cartão às stopwords
                stop_words.extend(cartao.lower().split())

            # Encontra a primeira palavra que não é número nem stop word
            categoria = next((p for p in palavras_texto if p.isalpha() and p not in stop_words), "outros")

            return {"acao": "add", "tipo": "gasto", "valor_num": valor_num, "valor_txt": valor_txt,
                    "categoria": categoria, "metodo": metodo, "cartao": cartao}

    return {"acao": "desconhecido"}


# =======================
# Teclados
# =======================
def teclado_flutuante(user_id):
    entradas = db.get_soma(user_id, "entrada")
    gastos = db.get_soma(user_id, "gasto")
    saldo = entradas - gastos

    status = "🟢😀 Finanças Saudáveis"
    if saldo < 0:
        status = "🔴😟 Saldo Negativo"
    elif entradas > 0 and (gastos / entradas) > Decimal("0.7"):
        status = "🟠🤔 Gastos altos!"

    teclado = [
        [status],
        ["🧾 Saldo Geral", "💳 Gastos por Cartão"],
        ["💰 Ver Entradas (Tudo)", "💸 Ver Saídas (Tudo)"],
        ["🧾 Filtrar Extrato"],
        ["📊 Gráfico Pizza", "📊 Gráfico Barras"],
        ["📑 Gerar PDF", "📊 Gerar XLSX", "🔄 Resetar Valores"]
    ]
    if user_id == ADMIN_USER_ID:
        teclado.append(["👁️ Ver Usuários"])
    return ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=False)

def teclado_admin_usuario_selecionado():
    teclado = [
        ["💰 Entradas", "💸 Saídas"],
        ["🧾 Saldo Geral"],
        ["📑 Gerar PDF", "📊 Gerar XLSX"],
        ["⬅️ Voltar"]
    ]
    return ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=False)

def teclado_filtros_periodo():
    teclado = [
        ["Hoje", "Esta Semana", "Este Mês"],
        ["Mês Passado", "Este Ano"],
        ["Cancelar"]
    ]
    return ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=True)

# =======================
# Funções de Gráficos, PDF, XLSX, etc.
# =======================
def grafico_gastos_pizza(user_id=None, inicio=None, fim=None):
    rows = db.gastos_por_categoria(user_id=user_id, inicio=inicio, fim=fim)
    if not rows:
        return None
    labels = [r[0] for r in rows]
    valores = [float(r[1]) for r in rows]
    fig, ax = plt.subplots()
    ax.pie(valores, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.set_title("Distribuição de Gastos por Categoria")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

def grafico_mensal_barras(user_id=None, meses=6):
    labels, entradas_vals, gastos_vals = db.series_mensais(user_id=user_id, meses=meses)
    if not labels:
        return None
    x = list(range(len(labels)))
    fig, ax = plt.subplots()
    width = 0.4
    ax.bar([i - width/2 for i in x], entradas_vals, width=width, label="Entradas", align="center")
    ax.bar([i + width/2 for i in x], gastos_vals, width=width, label="Gastos", align="center")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45)
    ax.set_ylabel("R$")
    ax.set_title("Entradas x Gastos por Mês")
    ax.legend()
    fig.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

def gerar_pdf(user_id=None, filename="relatorio.pdf", inicio=None, fim=None):
    doc = SimpleDocTemplate(filename)
    styles = getSampleStyleSheet()
    story = []

    entradas = db.get_soma(user_id, "entrada", inicio=inicio, fim=fim)
    gastos = db.get_soma(user_id, "gasto", inicio=inicio, fim=fim)
    saldo = entradas - gastos

    story.append(Paragraph("📑 Relatório Financeiro", styles["Title"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"Entradas: R$ {formatar_valor(entradas)}", styles["Normal"]))
    story.append(Paragraph(f"Gastos: R$ {formatar_valor(gastos)}", styles["Normal"]))
    story.append(Paragraph(f"Saldo: R$ {formatar_valor(saldo)}", styles["Normal"]))
    story.append(Spacer(1, 20))

    story.append(Paragraph("💰 Entradas:", styles["Heading2"]))
    transacoes_entrada = db.get_todas(user_id=user_id, tipo="entrada", inicio=inicio, fim=fim)
    for t in transacoes_entrada:
        # Indices baseados no db.py corrigido: 2=valor_num, 3=categoria, 5=cartao, 6=data
        story.append(Paragraph(f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}", styles["Normal"]))

    story.append(Spacer(1, 20))
    story.append(Paragraph("💸 Saídas:", styles["Heading2"]))
    transacoes_saida = db.get_todas(user_id=user_id, tipo="gasto", inicio=inicio, fim=fim)
    for t in transacoes_saida:
        # Indices baseados no db.py corrigido: 2=valor_num, 3=categoria, 5=cartao, 6=data
        story.append(Paragraph(f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}", styles["Normal"]))

    doc.build(story)
    return filename

def gerar_xlsx(user_id=None, filename="relatorio.xlsx", inicio=None, fim=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Relatório"
    ws.append(["Tipo", "Valor", "Categoria", "Método", "Cartão", "Data"])
    transacoes = db.get_todas(user_id=user_id, inicio=inicio, fim=fim)
    for t in transacoes:
        # Indices baseados no db.py corrigido: 1=tipo, 2=valor_num, 3=categoria, 4=metodo, 5=cartao, 6=data
        try:
            valor_num = Decimal(t[2])
        except (decimal.InvalidOperation, TypeError, ValueError):
            valor_num = Decimal("0.00")
        ws.append([t[1], valor_num, t[3], t[4], t[5] or "Dinheiro", t[6]])

    entradas = db.get_soma(user_id, "entrada", inicio=inicio, fim=fim)
    gastos = db.get_soma(user_id, "gasto", inicio=inicio, fim=fim)
    saldo = entradas - gastos
    ws.append([])
    ws.append(["Entradas", entradas])
    ws.append(["Gastos", gastos])
    ws.append(["Saldo", saldo])

    for cell in ws['B']:
        cell.number_format = 'R$ #,##0.00'
    ws['B' + str(ws.max_row - 2)].number_format = 'R$ #,##0.00'
    ws['B' + str(ws.max_row - 1)].number_format = 'R$ #,##0.00'
    ws['B' + str(ws.max_row)].number_format = 'R$ #,##0.00'

    wb.save(filename)
    return filename

def gastos_por_cartao(user_id):
    rows = db.get_gastos_por_cartao(user_id=user_id)
    if not rows:
        return "💳 Gastos por Cartão:\nNenhum gasto registrado."
    texto = "💳 Gastos por Cartão:\n"
    for r in rows:
        valor_formatado = formatar_valor(r[1])
        texto += f"▪️ {r[0]}: R$ {valor_formatado}\n"
    return texto

def verificar_alerta(user_id):
    entradas = db.get_soma(user_id, "entrada")
    gastos = db.get_soma(user_id, "gasto")
    saldo = entradas - gastos

    status = None
    if saldo < 0:
        status = "🔴😟 Saldo Negativo"
    elif entradas > 0 and (gastos / entradas) > Decimal("0.7"):
        status = "🟠🤔 Gastos altos!"

    if status:
        return (f"{status}\n"
                f"💰 Entradas: R$ {formatar_valor(entradas)}\n"
                f"💸 Gastos: R$ {formatar_valor(gastos)}\n"
                f"📌 Saldo: R$ {formatar_valor(saldo)}")
    return None

async def enviar_extrato_filtrado(update: Update, context: ContextTypes.DEFAULT_TYPE, inicio: datetime, fim: datetime, titulo_periodo: str):
    """Busca transações no DB com base no período e envia a resposta."""
    user_id = update.message.from_user.id

    # 1. Buscar transações (usando a função corrigida que pega valor_num)
    entradas = db.get_todas(user_id, tipo="entrada", inicio=inicio, fim=fim)
    saidas = db.get_todas(user_id, tipo="gasto", inicio=inicio, fim=fim)

    # 2. Filtrar valores 0 (para limpar histórico antigo)
    entradas_filtradas = [t for t in entradas if Decimal(t[2]) > 0]
    saidas_filtradas = [t for t in saidas if Decimal(t[2]) > 0]

    # 3. Calcular somas do período
    total_entradas = db.get_soma(user_id, "entrada", inicio=inicio, fim=fim)
    total_gastos = db.get_soma(user_id, "gasto", inicio=inicio, fim=fim)
    saldo_periodo = total_entradas - total_gastos

    # 4. Construir a mensagem
    texto = f"🧾 Extrato Filtrado: *{titulo_periodo}*\n\n"

    if not entradas_filtradas and not saidas_filtradas:
        texto += "Nenhuma transação encontrada neste período."
        await update.message.reply_text(texto, parse_mode='Markdown', reply_markup=teclado_flutuante(user_id))
        return

    # Seção de Entradas
    if entradas_filtradas:
        texto += "--- *Entradas* ---\n"
        for t in entradas_filtradas:
            # Indices: 2=valor, 3=categoria, 6=data
            texto += f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[6]}\n"
        texto += "\n"

    # Seção de Saídas
    if saidas_filtradas:
        texto += "--- *Saídas* ---\n"
        for t in saidas_filtradas:
             # Indices: 2=valor, 3=categoria, 5=cartao, 6=data
            texto += f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}\n"
        texto += "\n"

    # Resumo do Período
    texto += "--- *Resumo do Período* ---\n"
    texto += f"💰 Total Entradas: R$ {formatar_valor(total_entradas)}\n"
    texto += f"💸 Total Gastos: R$ {formatar_valor(total_gastos)}\n"
    texto += f"📌 Saldo Período: R$ {formatar_valor(saldo_periodo)}\n"

    await update.message.reply_text(texto, parse_mode='Markdown', reply_markup=teclado_flutuante(user_id))

# =======================
# Handlers
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    await update.message.reply_text(f"Olá, {user_name}! Bem-vindo ao seu Bot de Finanças.\n"
                                     "Digite um valor para registrar (ex: '150 mercado' ou '2000 salário').\n"
                                     "Use o teclado abaixo para outras opções:",
                                     reply_markup=teclado_flutuante(user_id))

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    msg = update.message.text

    # --- Handler "Voltar" e "Cancelar" centralizado ---
    if msg == "⬅️ Voltar" and user_id == ADMIN_USER_ID:
        if "admin_selecionado" in context.user_data:
            del context.user_data["admin_selecionado"]
        await update.message.reply_text("Voltando ao menu principal...",
                                        reply_markup=teclado_flutuante(user_id))
        return

    if msg == "Cancelar":
        if 'aguardando_filtro' in context.user_data:
             del context.user_data['aguardando_filtro']
        await update.message.reply_text("Ação cancelada.", reply_markup=teclado_flutuante(user_id))
        return

    # --- Bloco de Gerenciamento do Admin (VEM PRIMEIRO) ---
    if user_id == ADMIN_USER_ID and "admin_selecionado" in context.user_data:
        selecionado_id, selecionado_nome = context.user_data["admin_selecionado"]

        if 'aguardando_filtro' in context.user_data:
             del context.user_data['aguardando_filtro']

        if msg == "💰 Entradas":
            transacoes = db.get_todas(user_id=selecionado_id, tipo="entrada")
            transacoes_filtradas = []
            for t in transacoes:
                try:
                    if Decimal(t[2]) > 0:
                        transacoes_filtradas.append(t)
                except (decimal.InvalidOperation, TypeError, ValueError):
                    continue
            # Indices: 2=valor, 3=categoria, 5=cartao, 6=data
            texto = f"💰 Entradas de {selecionado_nome} (Tudo)\n" + "\n".join([f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}" for t in transacoes_filtradas])
            if not transacoes_filtradas: texto = f"{selecionado_nome} não possui entradas válidas."
            await update.message.reply_text(texto, reply_markup=teclado_admin_usuario_selecionado())

        elif msg == "💸 Saídas":
            transacoes = db.get_todas(user_id=selecionado_id, tipo="gasto")
            transacoes_filtradas = []
            for t in transacoes:
                try:
                    if Decimal(t[2]) > 0:
                        transacoes_filtradas.append(t)
                except (decimal.InvalidOperation, TypeError, ValueError):
                    continue
             # Indices: 2=valor, 3=categoria, 5=cartao, 6=data
            texto = f"💸 Saídas de {selecionado_nome} (Tudo)\n" + "\n".join([f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}" for t in transacoes_filtradas])
            if not transacoes_filtradas: texto = f"{selecionado_nome} não possui saídas válidas."
            await update.message.reply_text(texto, reply_markup=teclado_admin_usuario_selecionado())

        elif msg == "🧾 Saldo Geral":
            entradas = db.get_soma(selecionado_id, "entrada")
            gastos = db.get_soma(selecionado_id, "gasto")
            saldo = entradas - gastos
            await update.message.reply_text(f"Saldo de {selecionado_nome}\n"
                                            f"💰 Entradas: R$ {formatar_valor(entradas)}\n"
                                            f"💸 Gastos: R$ {formatar_valor(gastos)}\n"
                                            f"📌 Saldo: R$ {formatar_valor(saldo)}",
                                            reply_markup=teclado_admin_usuario_selecionado())

        elif msg == "📑 Gerar PDF":
            filename = gerar_pdf(selecionado_id, f"relatorio_{selecionado_id}.pdf")
            await update.message.reply_document(open(filename, "rb"), caption=f"Relatório PDF de {selecionado_nome}", reply_markup=teclado_admin_usuario_selecionado())
            os.remove(filename)

        elif msg == "📊 Gerar XLSX":
            filename = gerar_xlsx(selecionado_id, f"relatorio_{selecionado_id}.xlsx")
            await update.message.reply_document(open(filename, "rb"), caption=f"Relatório XLSX de {selecionado_nome}", reply_markup=teclado_admin_usuario_selecionado())
            os.remove(filename)

        else:
            await update.message.reply_text("Comando inválido. Use o teclado abaixo para gerenciar o usuário ou clique em '⬅️ Voltar'.",
                                            reply_markup=teclado_admin_usuario_selecionado())
        return

    # --- Fim do Bloco de Admin ---

    # --- NOVO BLOCO: Resposta aos Filtros ---
    if 'aguardando_filtro' in context.user_data:
        del context.user_data['aguardando_filtro'] # Limpa o estado
        hoje = datetime.now()

        if msg == "Hoje":
            inicio = fim = hoje
            await enviar_extrato_filtrado(update, context, inicio, fim, "Hoje")

        elif msg == "Esta Semana":
            inicio = hoje - timedelta(days=hoje.weekday()) # Segunda-feira
            fim = inicio + timedelta(days=6) # Domingo
            await enviar_extrato_filtrado(update, context, inicio, fim, "Esta Semana")

        elif msg == "Este Mês":
            inicio = hoje.replace(day=1)
            # Calcula o último dia deste mês
            prox_mes_inicio = (inicio + timedelta(days=32)).replace(day=1)
            fim = prox_mes_inicio - timedelta(days=1)
            await enviar_extrato_filtrado(update, context, inicio, fim, "Este Mês")

        elif msg == "Mês Passado":
            primeiro_dia_mes_atual = hoje.replace(day=1)
            fim = primeiro_dia_mes_atual - timedelta(days=1)
            inicio = fim.replace(day=1)
            await enviar_extrato_filtrado(update, context, inicio, fim, "Mês Passado")

        elif msg == "Este Ano":
            inicio = hoje.replace(day=1, month=1)
            fim = hoje.replace(day=31, month=12)
            await enviar_extrato_filtrado(update, context, inicio, fim, "Este Ano")

        else:
            # Se clicou em "Cancelar" ou outra coisa
            await update.message.reply_text("Filtro cancelado.", reply_markup=teclado_flutuante(user_id))

        return # Impede que o resto da função seja executado

    # --- Fim do Bloco de Filtros ---


    # --- Lógica do Usuário Comum (e Admin para si mesmo) ---

    if msg == "🔄 Resetar Valores":
        await update.message.reply_text(
            "Escolha o período para resetar:",
            reply_markup=ReplyKeyboardMarkup(
                [["Último valor", "Hoje"], ["Última semana", "Este mês"], ["Tudo"], ["Cancelar"]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return
    elif msg in ["Último valor", "Hoje", "Última semana", "Este mês", "Tudo"]:
        opcao_map = {"Último valor":"ultimo","Hoje":"dia","Última semana":"semana","Este mês":"mes","Tudo":"tudo"}
        db.limpar_transacoes(user_id, opcao_map[msg])
        await update.message.reply_text(f"✅ Transações removidas ({msg})", reply_markup=teclado_flutuante(user_id))
        return

    if msg == "📊 Gráfico Pizza":
        buf = grafico_gastos_pizza(user_id)
        if buf:
            await update.message.reply_photo(buf, caption="💸 Distribuição de Gastos por Categoria", reply_markup=teclado_flutuante(user_id))
        else:
            await update.message.reply_text("Nenhum gasto registrado.", reply_markup=teclado_flutuante(user_id))
        return

    if msg == "📊 Gráfico Barras":
        buf = grafico_mensal_barras(user_id)
        if buf:
            await update.message.reply_photo(buf, caption="📊 Entradas x Gastos por Mês", reply_markup=teclado_flutuante(user_id))
        else:
            await update.message.reply_text("Nenhuma transação registrada.", reply_markup=teclado_flutuante(user_id))
        return

    if msg == "💰 Ver Entradas (Tudo)":
        transacoes = db.get_todas(user_id=user_id, tipo="entrada")
        transacoes_filtradas = []
        for t in transacoes:
            try:
                if Decimal(t[2]) > 0:
                    transacoes_filtradas.append(t)
            except (decimal.InvalidOperation, TypeError, ValueError):
                continue

        if not transacoes_filtradas:
            await update.message.reply_text("Nenhuma entrada válida registrada.", reply_markup=teclado_flutuante(user_id))
            return
        # Indices: 2=valor, 3=categoria, 6=data
        texto = "💰 Entradas (Lista Completa):\n" + "\n".join([f"➡️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[6]}" for t in transacoes_filtradas])
        await update.message.reply_text(texto, reply_markup=teclado_flutuante(user_id))
        return

    if msg == "💸 Ver Saídas (Tudo)":
        transacoes = db.get_todas(user_id=user_id, tipo="gasto")
        transacoes_filtradas = []
        for t in transacoes:
            try:
                if Decimal(t[2]) > 0:
                    transacoes_filtradas.append(t)
            except (decimal.InvalidOperation, TypeError, ValueError):
                continue

        if not transacoes_filtradas:
            await update.message.reply_text("Nenhuma saída válida registrada.", reply_markup=teclado_flutuante(user_id))
            return
         # Indices: 2=valor, 3=categoria, 5=cartao, 6=data
        texto = "💸 Saídas (Lista Completa):\n" + "\n".join([f"⬅️ R$ {formatar_valor(t[2])} ({t[3]}) - {t[5] or 'Dinheiro'} - {t[6]}" for t in transacoes_filtradas])
        await update.message.reply_text(texto, reply_markup=teclado_flutuante(user_id))
        return

    if msg == "🧾 Filtrar Extrato":
        context.user_data['aguardando_filtro'] = True
        await update.message.reply_text("Selecione o período que deseja filtrar:", reply_markup=teclado_filtros_periodo())
        return

    if msg == "💳 Gastos por Cartão":
        texto = gastos_por_cartao(user_id)
        await update.message.reply_text(texto, reply_markup=teclado_flutuante(user_id))
        return

    if msg == "🧾 Saldo Geral":
        entradas = db.get_soma(user_id, "entrada")
        gastos = db.get_soma(user_id, "gasto")
        saldo = entradas - gastos

        status = "🟢😀 Finanças Saudáveis"
        if saldo < 0:
            status = "🔴😟 Saldo Negativo"
        elif entradas > 0 and (gastos / entradas) > Decimal("0.7"):
            status = "🟠🤔 Gastos altos!"

        await update.message.reply_text(
            (f"🧾 Saldo Geral (Total)\n"
             f"💰 Entradas: R$ {formatar_valor(entradas)}\n"
             f"💸 Gastos: R$ {formatar_valor(gastos)}\n"
             f"📌 Saldo: R$ {formatar_valor(saldo)}\n\n"
             f"Status: {status}"),
            reply_markup=teclado_flutuante(user_id)
        )
        return

    if msg == "📑 Gerar PDF":
        filename = gerar_pdf(user_id)
        await update.message.reply_document(open(filename, "rb"), reply_markup=teclado_flutuante(user_id))
        os.remove(filename)
        return

    if msg == "📊 Gerar XLSX":
        filename = gerar_xlsx(user_id)
        await update.message.reply_document(open(filename, "rb"), reply_markup=teclado_flutuante(user_id))
        os.remove(filename)
        return

    # --- Lógica de Admin (Listar e Selecionar) ---
    if msg == "👁️ Ver Usuários" and user_id == ADMIN_USER_ID:
        usuarios = db.listar_usuarios()
        if not usuarios:
            await update.message.reply_text("Nenhum usuário registrado ainda.",
                                            reply_markup=teclado_flutuante(user_id))
            return

        teclado = [[f"{u[0]} - {u[1]}"] for u in usuarios]
        teclado.append(["⬅️ Voltar"])

        await update.message.reply_text("Escolha um usuário para gerenciar:",
                                        reply_markup=ReplyKeyboardMarkup(teclado, resize_keyboard=True, one_time_keyboard=True))
        return

    if user_id == ADMIN_USER_ID and " - " in msg and msg.split(" - ")[0].isdigit():
        selecionado_id = int(msg.split(" - ")[0])
        selecionado_nome = msg.split(" - ")[1]
        context.user_data["admin_selecionado"] = (selecionado_id, selecionado_nome)

        await update.message.reply_text(f"Gerenciando: {selecionado_nome}.\n"
                                        f"Escolha uma ação no teclado abaixo.",
                                        reply_markup=teclado_admin_usuario_selecionado())
        return

    # --- Interpretação de Mensagem (Adicionar transação) ---
    # Esta é a "escrita livre" que você mencionou
    resultado = interpretar_mensagem(msg)
    if resultado["acao"] == "add":
        db.add_transacao(user_id, resultado["tipo"], resultado["valor_num"], resultado["valor_txt"], resultado["categoria"], resultado["metodo"], resultado["cartao"], user_name)

        msg_resp = f"✅ {resultado['tipo'].capitalize()} registrada: R$ {formatar_valor(resultado['valor_num'])} ({resultado['categoria']})"
        if resultado['cartao']:
            msg_resp += f"\n💳 Cartão: {resultado['cartao']}"

        alerta = verificar_alerta(user_id)
        if alerta:
            msg_resp += f"\n\n{alerta}"

        await update.message.reply_text(msg_resp, reply_markup=teclado_flutuante(user_id))
    else:
        await update.message.reply_text("❌ Não entendi. Por favor, digite um valor (maior que zero) com ou sem descrição (ex: '50 lanche').", reply_markup=teclado_flutuante(user_id))

# =======================
# Inicialização do Bot (VERSÃO FINAL E CORRIGIDA)
# =======================
TOKEN = os.environ.get('BOT_TOKEN') # Lê o token dos "Secrets"

app = None # Variável global para o app do Telegram

if not TOKEN:
    print("ERRO CRÍTICO: Token do bot não encontrado.")
    print("Por favor, configure o 'BOT_TOKEN' na aba 'Secrets' (cadeado 🔒) do Replit.")
else:
    # 1. Configura o bot do Telegram
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    
    print("🤖 Bot configurado.")

# --- CÓDIGO DO SERVIDOR FLASK ---
# A variável 'app_flask' é o que o Waitress/Render precisa
app_flask = Flask('') 
@app_flask.route('/')
def home():
    return "Estou vivo!" # Mensagem para o UptimeRobot

# --- MUDANÇA CRÍTICA AQUI ---
def run_telegram_bot():
    """Roda o bot do Telegram em uma thread separada, sem capturar sinais."""
    print("🤖 Bot do Telegram rodando em background.")
    try:
        # stop_signals=None resolve o erro "set_wakeup_fd"
        app.run_polling(stop_signals=None)
    except Exception as e:
        print(f"!!! ERRO FATAL NO POLLING DO BOT: {e} !!!")

def run_flask_and_bot():
    if not app:
        return # Não inicia se não houver token
        
    print("Iniciando Bot e Servidor...")

    # 1. Inicia o Bot do Telegram em uma Thread separada (para ele rodar em paralelo)
    thread_bot = Thread(target=run_telegram_bot, daemon=True)
    thread_bot.start()
    
    # 2. Roda o Flask na thread principal (bloqueando)
    print("\n--- INICIANDO SERVIDOR FLASK NA THREAD PRINCIPAL ---")
    try:
        from waitress import serve
        print("--- Usando 'waitress' na porta 8080 ---")
        serve(app_flask, host='0.0.0.0', port=8080) 
    except ImportError:
        print("--- Usando fallback 'app_flask.run()' na porta 8080 ---")
        app_flask.run(host='0.0.0.0', port=8080)
    except Exception as e:
        print(f"\n!!! ERRO DESCONHECIDO AO INICIAR FLASK: {e} !!!\n")


if __name__ == "__main__":
    # Remove qualquer código de `main()` anterior
    run_flask_and_bot()