"""
Dashboard consolidado - Etapa 5 (final)
==========================================
App Streamlit que junta:
  1. Tabela de recomendações: ticker, preço atual, preço-alvo (DCF), upside%,
     recomendação (Compra/Neutro/Venda, colorida).
  2. Gráfico comparativo de retorno (Etapa 4), com o tooltip customizado
     ordenado por retorno decrescente.

Como rodar: `streamlit run src/dashboard.py` (na raiz do projeto).

Nota técnica: usamos st.components.v1.html (em vez de st.plotly_chart) pro
gráfico comparativo porque o st.plotly_chart nativo do Streamlit renderiza
a figura através do próprio componente React dele, sem passar pelo
`fig.write_html(post_script=...)` — ou seja, perderíamos o JS do tooltip
customizado (Etapa 4) se usássemos st.plotly_chart. Embutindo o HTML
completo num iframe, o comportamento fica idêntico ao arquivo standalone.
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import plotly.io as pio
import streamlit.components.v1 as components

# `streamlit run src/dashboard.py` executa este arquivo como script solto
# (__main__), não como parte do pacote `src` — os imports relativos usados
# no resto do projeto (`from . import config`) quebram com "attempted
# relative import with no known parent package". Adicionamos a raiz do
# projeto ao sys.path e importamos via `from src import ...` (absoluto),
# que funciona porque src/__init__.py já existe e os módulos internos
# (dcf.py, returns_chart.py) fazem `from . import config` — isso resolve
# certo desde que sejam carregados como submódulos do pacote `src`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src import dcf
from src import returns_chart

st.set_page_config(
    page_title="Dashboard de Valuation — Ações Globais",
    layout="wide",
)


@st.cache_data(ttl=3600)
def carregar_recomendacoes() -> pd.DataFrame:
    """
    Roda o DCF das 6 ações e monta a tabela de recomendações. Cacheado por
    1h (ttl=3600) para não recalcular a cada interação do usuário no
    dashboard — os dados-base só mudam quando data_fetch.py roda de novo.
    """
    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    linhas = []
    for ticker in config.TICKERS:
        r = dcf.calcular_dcf(ticker, conn)
        linhas.append({
            "Ticker": r["ticker"],
            "Empresa": r["nome"],
            "Setor": r["setor"],
            "Preço Atual": r["preco_atual"],
            "Preço-Alvo (DCF)": r["preco_alvo"],
            "Upside": r["upside"],
            "Recomendação": r["recomendacao"],
            "WACC": r["wacc_detalhe"]["wacc"],
        })
    conn.close()
    return pd.DataFrame(linhas)


@st.cache_data(ttl=3600)
def carregar_metadados() -> pd.DataFrame:
    """Datas de divulgação de resultado e última atualização, por ticker (para o rodapé/sidebar)."""
    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    df = pd.read_sql_query(
        "SELECT ticker, atualizado_em, ultima_divulgacao_resultado, "
        "proxima_divulgacao_resultado FROM empresas", conn,
    )
    conn.close()
    return df


@st.cache_data(ttl=3600)
def gerar_html_grafico() -> str:
    """Gera o HTML do gráfico comparativo (mesma função/JS da Etapa 4)."""
    fig = returns_chart.gerar_grafico()
    return pio.to_html(
        fig,
        div_id=returns_chart.DIV_ID_GRAFICO,
        post_script=returns_chart._JS_TOOLTIP_CUSTOMIZADO,
        full_html=False,          # embutido num iframe, não precisa de <html>/<head> completos
        include_plotlyjs="cdn",   # carrega plotly.js do CDN em vez de embutir ~4MB a cada reload
    )


def cor_recomendacao(valor: str) -> str:
    """Aplica a cor de fundo por recomendação, na tabela (Compra=verde, Venda=vermelho, Neutro=cinza)."""
    cores = {"Compra": "background-color: #C6EFCE; color: #006100",
             "Venda": "background-color: #FFC7CE; color: #9C0006",
             "Neutro": "background-color: #E7E6E6; color: #3A3A3A"}
    return cores.get(valor, "")


def main():
    st.title("Dashboard de Valuation — Ações Globais")
    st.caption(
        "AAPL · MSFT · AMZN · NVDA · GOOGL · TSM — DCF + comparativo de retorno. "
        "Metodologia completa em cada Excel individual (/valuations) e em comps_analysis.xlsx."
    )

    df = carregar_recomendacoes()
    metadados = carregar_metadados()

    # ---- Cabeçalho: quando foi a última atualização de dados ------------
    if not metadados.empty and metadados["atualizado_em"].notna().any():
        ultima_atualizacao = pd.to_datetime(metadados["atualizado_em"]).max()
        st.caption(f"Fundamentos atualizados pela última vez em: {ultima_atualizacao.strftime('%d/%m/%Y %H:%M')} UTC")

    # ---- Tabela de recomendações -----------------------------------------
    st.subheader("Recomendações (DCF)")

    df_exibicao = df.copy()
    df_exibicao["Preço Atual"] = df_exibicao["Preço Atual"].map(lambda v: f"$ {v:,.2f}")
    df_exibicao["Preço-Alvo (DCF)"] = df_exibicao["Preço-Alvo (DCF)"].map(lambda v: f"$ {v:,.2f}")
    df_exibicao["Upside"] = df["Upside"].map(lambda v: f"{v:+.1%}")
    df_exibicao["WACC"] = df["WACC"].map(lambda v: f"{v:.2%}")

    estilo = df_exibicao.style.apply(
        lambda col: [cor_recomendacao(v) for v in col] if col.name == "Recomendação" else ["" for _ in col],
        axis=0,
    )
    st.dataframe(estilo, use_container_width=True, hide_index=True)

    with st.expander("Datas de divulgação de resultado"):
        st.dataframe(
            metadados.rename(columns={
                "ticker": "Ticker",
                "ultima_divulgacao_resultado": "Última divulgação",
                "proxima_divulgacao_resultado": "Próxima divulgação",
                "atualizado_em": "Fundamentos atualizados em",
            })[["Ticker", "Última divulgação", "Próxima divulgação", "Fundamentos atualizados em"]],
            use_container_width=True, hide_index=True,
        )

    # ---- Gráfico comparativo de retorno -----------------------------------
    st.subheader("Retorno comparativo")
    html_grafico = gerar_html_grafico()
    components.html(html_grafico, height=650, scrolling=False)

    st.caption(
        "Threshold de recomendação: upside > "
        f"{config.THRESHOLD_COMPRA:.0%} = Compra, < {config.THRESHOLD_VENDA:.0%} = Venda, entre isso = Neutro. "
        "DCF simples de horizonte curto tende a subestimar mega caps de crescimento — ver comps_analysis.xlsx "
        "para cross-check via múltiplos de mercado."
    )


if __name__ == "__main__":
    main()
