"""
Gráfico comparativo de retorno - Etapa 4
===========================================
Peça central do dashboard: compara o retorno normalizado das 6 ações no
mesmo eixo, com abas YTD/12M/24M/36M que trocam INSTANTANEAMENTE (sem nova
chamada de API), porque tudo já está em memória — os botões só mudam o
range visível do eixo X (Plotly `relayout`), nunca recomputam os dados.

Fonte dos preços: tabela `precos_historicos` no SQLite (já baixados pelo
data_fetch.py na Etapa 2) — este módulo não faz NENHUMA chamada nova ao
yfinance, só lê o banco.

Decisão de design (documentada para você validar): a normalização para
base 100 acontece UMA VEZ, no primeiro dia da janela de 36 meses. As abas
YTD/12M/24M apenas RECORTAM essa mesma série já normalizada — elas não
recalculam a base 100 a partir do próprio início de cada janela. Ou seja,
ao abrir a aba "YTD", as linhas não necessariamente começam em 100; elas
mostram o valor acumulado desde o início dos 36 meses, só que "zoomado" no
período recente. Isso é o que a especificação original pediu (".loc()" só
filtra o DataFrame já carregado) — se você preferir que cada aba reinicie
em 100 no seu próprio primeiro dia, é uma mudança pequena, me avisa.
"""

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from . import config

# 6 cores distintas e com bom contraste entre si (paleta qualitativa)
CORES = {
    "AAPL": "#1f77b4",
    "MSFT": "#ff7f0e",
    "AMZN": "#2ca02c",
    "NVDA": "#d62728",
    "GOOGL": "#9467bd",
    "TSM": "#8c564b",
}


def carregar_precos_do_banco(tickers: list = None) -> pd.DataFrame:
    """
    Lê o histórico de preços (Close) de todos os tickers direto do SQLite —
    já foi baixado pelo data_fetch.py, então não faz nenhuma chamada nova
    de API. Retorna um DataFrame largo: índice = data, colunas = ticker.
    """
    if tickers is None:
        tickers = config.TICKERS

    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    partes = {}
    for ticker in tickers:
        df = pd.read_sql_query(
            "SELECT data, close FROM precos_historicos WHERE ticker = ? ORDER BY data",
            conn, params=(ticker,), parse_dates=["data"],
        )
        partes[ticker] = df.set_index("data")["close"]
    conn.close()

    precos = pd.DataFrame(partes).dropna(how="all")
    return precos


def normalizar_base_100(precos: pd.DataFrame) -> pd.DataFrame:
    """Normaliza cada série para base 100 no primeiro dia disponível."""
    return precos / precos.iloc[0] * 100


def construir_grafico_comparativo(precos_normalizados: pd.DataFrame) -> go.Figure:
    """
    Monta o gráfico de linhas com 4 botões (YTD/12M/24M/36M) que só mudam o
    range do eixo X — nenhum dado é recalculado ao trocar de aba, então a
    troca é instantânea mesmo com o gráfico já renderizado no navegador.
    """
    fig = go.Figure()

    for ticker in precos_normalizados.columns:
        serie = precos_normalizados[ticker].dropna()
        fig.add_trace(go.Scatter(
            x=serie.index,
            y=serie.values,
            mode="lines",
            name=ticker,
            line=dict(color=CORES.get(ticker), width=2),
            hovertemplate=f"<b>{ticker}</b><br>%{{x|%d/%m/%Y}}<br>Retorno: %{{y:.1f}}<extra></extra>",
        ))

    data_maxima = precos_normalizados.index.max()
    data_minima = precos_normalizados.index.min()
    inicio_ano_atual = pd.Timestamp(year=data_maxima.year, month=1, day=1)

    janelas = {
        "YTD": inicio_ano_atual,
        "12M": data_maxima - pd.DateOffset(months=12),
        "24M": data_maxima - pd.DateOffset(months=24),
        "36M": data_minima,
    }

    botoes = []
    for label, data_inicio in janelas.items():
        data_inicio_valida = max(data_inicio, data_minima)
        botoes.append(dict(
            label=label,
            method="relayout",
            args=[{"xaxis.range": [data_inicio_valida, data_maxima]}],
        ))

    fig.update_layout(
        title="Retorno comparativo (base 100) — AAPL, MSFT, AMZN, NVDA, GOOGL, TSM",
        xaxis_title="Data",
        yaxis_title="Retorno normalizado (base 100 no início da janela de 36 meses)",
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        updatemenus=[dict(
            type="buttons",
            direction="right",
            buttons=botoes,
            x=0, y=1.15, xanchor="left", yanchor="top",
            showactive=True,
        )],
        xaxis=dict(range=[janelas["36M"], data_maxima]),  # começa mostrando 36M (tudo)
    )
    return fig


def gerar_grafico(tickers: list = None) -> go.Figure:
    """Função de conveniência: carrega, normaliza e monta o gráfico em uma chamada."""
    precos = carregar_precos_do_banco(tickers)
    precos_normalizados = normalizar_base_100(precos)
    return construir_grafico_comparativo(precos_normalizados)


if __name__ == "__main__":
    fig = gerar_grafico()
    caminho = f"{config.DIR_RAIZ}/grafico_comparativo.html"
    fig.write_html(caminho)
    print(f"Gráfico salvo em: {caminho}")
