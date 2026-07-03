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

# Prêmio de risco de mercado (Equity Risk Premium). Usamos o "implied ERP"
# do Aswath Damodaran, referência mais usada no mercado, atualizada em
# jan/2026 (baseada no nível do S&P 500 e fluxos de caixa esperados).
# Fonte: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histimpl.html
PREMIO_RISCO_MERCADO = 0.0423

# Fallback para a taxa livre de risco (Treasury 10Y), usado quando não há
# conexão com a internet para buscar o yield ao vivo via yfinance (ticker
# ^TNX). Valor de referência: yield de 10 anos em 02/07/2026.
TAXA_LIVRE_DE_RISCO_FALLBACK = 0.0449

# Crescimento de receita esperado no ANO 1 da projeção, com base em consenso
# de analistas pesquisado em 03/07/2026 (Yahoo Finance, Simply Wall St, S&P
# Global e guidance da própria TSMC para 2026). A partir do ano 1, o modelo
# faz um "fade" linear até CRESCIMENTO_PERPETUIDADE no último ano do
# horizonte de projeção — nenhuma empresa sustenta o crescimento atual para
# sempre, e isso é especialmente relevante para NVDA/TSM, que crescem muito
# acima da média do grupo.
CRESCIMENTO_CONSENSO_ANO1 = {
    "AAPL": 0.075,
    "MSFT": 0.145,
    "AMZN": 0.14,
    "GOOGL": 0.145,
    "NVDA": 0.24,
    "TSM": 0.35,
}

# ---------------------------------------------------------------------------
# Conversão de moeda para ADRs (ex: TSM)
# ---------------------------------------------------------------------------
# ADRs como a TSM negociam em USD, mas reportam as demonstrações financeiras
# na moeda do país de origem (TSM reporta em TWD - New Taiwan Dollar).
# Descoberto durante o teste da Etapa 3: sem essa conversão, o DCF da TSM
# saía com preço-alvo de milhares de dólares (misturando TWD com USD).
# data_fetch.py usa isso como fallback quando não consegue buscar a taxa de
# câmbio ao vivo. Fonte: 31,92 TWD/USD em 03/07/2026 (tradingeconomics.com).
FX_FALLBACK_PARA_USD = {
    "TWD": 31.92,
}

# ---------------------------------------------------------------------------
# Janela de anos usada para médias históricas (margem EBIT, % D&A, % CapEx,
# % variação de capital de giro). Descoberto durante o teste da Etapa 3: usar
# TODO o histórico disponível (4-5 anos) distorce empresas com margem em
# transição rápida (ex: AMZN foi de -0,7% de margem EBIT em 2022 para 13,9%
# em 2025 - a média de 4 anos non-sense subestima a lucratividade atual).
# Usar só os últimos 2 anos equilibra estabilidade com relevância.
PERIODOS_MEDIA_HISTORICA = 2


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
