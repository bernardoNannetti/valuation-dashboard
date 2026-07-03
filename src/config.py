"""
Configurações centrais do projeto.
====================================
Tudo que é premissa de negócio/modelagem fica AQUI, e não espalhado pelo
código. Assim, para mudar uma taxa de imposto padrão, o threshold de
recomendação, ou trocar um ticker, você mexe só neste arquivo.
"""

# ---------------------------------------------------------------------------
# Universo de ações do projeto (prova de conceito)
# ---------------------------------------------------------------------------
TICKERS = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "TSM"]

# ---------------------------------------------------------------------------
# Janela de histórico de preços para o gráfico comparativo
# ---------------------------------------------------------------------------
ANOS_HISTORICO_PRECO = 3  # 36 meses

# ---------------------------------------------------------------------------
# Premissas macro do DCF (validadas com o usuário em 02/07/2026)
# ---------------------------------------------------------------------------
# Taxa livre de risco: puxada ao vivo do yield do Treasury 10Y (ticker ^TNX
# no yfinance, que reporta o yield em pontos percentuais, ex: 4.35 = 4,35%).
TICKER_TAXA_LIVRE_DE_RISCO = "^TNX"

# Prêmio de risco de mercado (Equity Risk Premium). Referência de mercado
# (linha do tempo Damodaran, US ERP histórico ~4,5%-5,5%). Fixamos 5% como
# premissa simplificadora para esta prova de conceito.
PREMIO_RISCO_MERCADO = 0.05

# Taxa de crescimento na perpetuidade (Gordon Growth). Referência: PIB
# nominal de longo prazo dos EUA (~inflação + crescimento real).
CRESCIMENTO_PERPETUIDADE = 0.025

# Horizonte de projeção explícita do DCF (anos de fluxo de caixa projetado
# antes de aplicar o valor terminal).
HORIZONTE_PROJECAO_ANOS = 5

# ---------------------------------------------------------------------------
# Threshold de recomendação (upside/downside do preço-alvo vs. preço atual)
# ---------------------------------------------------------------------------
THRESHOLD_COMPRA = 0.15   # upside > 15% => Compra
THRESHOLD_VENDA = -0.15   # upside < -15% => Venda
# entre os dois => Neutro

# ---------------------------------------------------------------------------
# Caminhos de arquivos
# ---------------------------------------------------------------------------
import os

DIR_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_VALUATIONS = os.path.join(DIR_RAIZ, "valuations")
DIR_DATA = os.path.join(DIR_RAIZ, "data")
CAMINHO_BANCO_SQLITE = os.path.join(DIR_DATA, "valuation.db")
