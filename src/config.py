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
# Guidance de CapEx (gastos de capital) para o ano 1 da projeção
# ---------------------------------------------------------------------------
# Pesquisado em 03/07/2026: guidance pública de capex para 2026 de cada
# empresa (anúncios de resultados / imprensa especializada), convertida para
# % da receita (usando a receita mais recente disponível como base).
#
# CUIDADO / limitação conhecida: os números de "capex" divulgados pela
# imprensa para big techs em 2026 muitas vezes somam capex em caixa (compra
# de imobilizado, a linha 'Capital Expenditure' que puxamos do yfinance) +
# infraestrutura financiada via leasing (que aparece em outras linhas do
# fluxo de caixa). Ou seja, esse número tende a SUPERESTIMAR um pouco o
# capex "em caixa" real. Para uma prova de conceito, ainda assim é a melhor
# proxy pública disponível da intensidade de investimento de cada empresa.
#
# NVDA não está aqui de propósito: diferente das outras 5, a NVDA vende os
# chips que alimentam esse boom de capex alheio — o capex PRÓPRIO dela é
# pequeno e estável historicamente (ver dcf.py), então usamos a média
# histórica normal para ela, sem guidance de "gastos" específica.
#
# Fontes: CNBC, Tom's Hardware, DataCenterDynamics, TrendForce, SCMP
# (ver histórico da conversa/README para links completos).
CAPEX_GUIDANCE_ANO1_USD = {
    "AAPL": 14e9,     # guidance 2026 (bem mais conservadora que os pares)
    "MSFT": 190e9,    # plano de capex calendário 2026 (revisado para cima)
    "AMZN": 200e9,    # guidance 2026, majoritariamente infra de IA/AWS
    "GOOGL": 185e9,   # topo do range revisado de $180-190bi para 2026
    "TSM": 55e9,      # topo do range de $52-56bi para 2026 (já em USD)
}

# A partir do CapEx guiado no ano 1, o modelo faz um "fade" linear até a
# média histórica de 2 anos (mesma lógica usada para crescimento de
# receita) — ou seja, assume que esse pico de investimento em IA modera ao
# longo do horizonte de projeção, em vez de ficar constante para sempre.

# Teto para o CapEx% implícito na guidance, como múltiplo do CapEx% médio
# histórico. Descoberto ao testar a Etapa 3: dividir a guidance em dólares
# pela receita do último ano fechado gerava percentuais desproporcionais
# (ex: MSFT -67,4% da receita, GOOGL -45,9%) — um único ano de CapEx tão
# pesado gerava FCFF ano 1 fortemente negativo e chegou a tornar o
# valuation da AMZN negativo (preço-alvo -$2,89, o que não existe na
# prática). Limitar a guidance a, no máximo, 2x o CapEx% histórico evita
# que um único ano domine o valuation inteiro, mantendo o sinal de "pico de
# investimento acima do normal" sem deixá-lo implodir o modelo.
CAPEX_GUIDANCE_CAP_MULTIPLO = 2.0

# ---------------------------------------------------------------------------
# Horizonte de projeção por empresa (override do padrão de 5 anos)
# ---------------------------------------------------------------------------
# Testamos estender AMZN/MSFT/GOOGL para 10 anos (nossa primeira tentativa
# de corrigir o preço-alvo negativo da AMZN) e NÃO funcionou: como o fade de
# capex é LINEAR ao longo de todo o horizonte, esticar o horizonte só
# esticou o período com capex elevado por mais tempo, piorando a AMZN em vez
# de melhorar. Revertido — ver ANOS_FADE_CAPEX abaixo para a correção real.
# Deixamos o mecanismo de override pronto (dict vazio = todos usam
# HORIZONTE_PROJECAO_ANOS) caso outra empresa precise de um horizonte
# diferente no futuro por outro motivo.
HORIZONTE_PROJECAO_POR_TICKER = {}

# ---------------------------------------------------------------------------
# Janela de normalização do CapEx (correção real do problema acima)
# ---------------------------------------------------------------------------
# Guidance pública de capex só é confiável para ~1-2 anos à frente (é o que
# as empresas realmente comunicam nos calls de resultado). Não faz sentido
# fingir que sabemos a trajetória de capex até o ano 5 ou 10 — então, em vez
# de um fade lento ao longo de todo o horizonte, o CapEx guiado vale para o
# ano 1, faz a transição até o ano ANOS_FADE_CAPEX, e a partir daí volta
# para a média histórica (2 anos) pelo resto da projeção.
ANOS_FADE_CAPEX = 2

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
# Benchmark de mercado (linha de referência no gráfico comparativo)
# ---------------------------------------------------------------------------
# NÃO é uma ação do projeto: nunca entra em TICKERS, então nunca aparece na
# tabela de recomendações, no DCF ou no comps_analysis — é usado só como uma
# linha extra (tracejada) no gráfico comparativo de retorno, pra dar
# contexto de "essa ação bateu ou perdeu do índice" (padrão em qualquer
# dashboard de research/portfolio de verdade). Precisa ser buscado via
# data_fetch.baixar_benchmark() (yfinance, só roda via Claude Code — mesma
# limitação de rede do resto do projeto).
TICKER_BENCHMARK = "^GSPC"
NOME_BENCHMARK = "S&P 500"

# ---------------------------------------------------------------------------
# Caminhos de arquivos
# ---------------------------------------------------------------------------
import os

DIR_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_VALUATIONS = os.path.join(DIR_RAIZ, "valuations")
DIR_DATA = os.path.join(DIR_RAIZ, "data")
CAMINHO_BANCO_SQLITE = os.path.join(DIR_DATA, "valuation.db")
