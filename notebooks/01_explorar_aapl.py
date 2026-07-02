"""
Etapa 1 - Validação de extração de dados para UMA ação (AAPL)
==============================================================
Objetivo deste script: entender exatamente o formato dos dados que o
yfinance devolve, ANTES de generalizar a lógica para as outras 5 ações.
Isso evita escrever código genérico em cima de premissas erradas sobre
o formato dos dados (ex: nomes de colunas, tipos, linhas faltantes).

Rodamos 4 tipos de extração:
  1. Histórico de preços (36 meses) - vai alimentar o gráfico comparativo
  2. .info - dados cadastrais (nome, setor, indústria, beta, descrição)
  3. .financials - DRE (receita, EBIT, lucro líquido, etc.)
  4. .balance_sheet e .cashflow - balanço e fluxo de caixa (para o DCF)
"""

import yfinance as yf
import pandas as pd

pd.set_option("display.max_columns", 10)
pd.set_option("display.width", 160)

TICKER = "AAPL"

print(f"\n{'='*70}\n1. HISTÓRICO DE PREÇOS (36 meses) - {TICKER}\n{'='*70}")
# yf.download baixa o histórico em UMA chamada só (nunca recotar por período).
# period="36mo" ~ não existe direto; usamos period="3y" que cobre 36 meses.
precos = yf.download(TICKER, period="3y", auto_adjust=True, progress=False)
print("Shape:", precos.shape)
print("Colunas:", list(precos.columns))
print("Índice (tipo):", type(precos.index))
print(precos.tail(3))

print(f"\n{'='*70}\n2. INFO CADASTRAL - {TICKER}\n{'='*70}")
ticker_obj = yf.Ticker(TICKER)
info = ticker_obj.info
campos_relevantes = [
    "longName", "sector", "industry", "longBusinessSummary",
    "beta", "currentPrice", "marketCap", "sharesOutstanding",
    "totalDebt", "totalCash", "currency",
]
for campo in campos_relevantes:
    valor = info.get(campo, "N/A")
    # corta descrições longas só para exibição no terminal
    if isinstance(valor, str) and len(valor) > 120:
        valor = valor[:120] + "..."
    print(f"  {campo}: {valor}")

print(f"\n{'='*70}\n3. FINANCIALS (DRE anual) - {TICKER}\n{'='*70}")
financials = ticker_obj.financials
print("Shape:", financials.shape)
print("Linhas (itens da DRE) disponíveis:")
print(list(financials.index))
print("\nColunas (períodos):", list(financials.columns))

print(f"\n{'='*70}\n4. BALANCE SHEET - {TICKER}\n{'='*70}")
balance = ticker_obj.balance_sheet
print("Shape:", balance.shape)
print("Linhas (itens do balanço) disponíveis:")
print(list(balance.index))

print(f"\n{'='*70}\n5. CASHFLOW - {TICKER}\n{'='*70}")
cashflow = ticker_obj.cashflow
print("Shape:", cashflow.shape)
print("Linhas (itens do fluxo de caixa) disponíveis:")
print(list(cashflow.index))

print(f"\n{'='*70}\nFIM DA EXPLORAÇÃO\n{'='*70}")
