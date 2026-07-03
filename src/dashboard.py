"""
Dashboard consolidado - Etapa 5 (final) + redesign visual
==========================================
App Streamlit que junta:
  1. Cards de KPI no topo (contagem Compra/Neutro/Venda, upside médio do
     grupo, data da última atualização de fundamentos).
  2. Tabela de recomendações: ticker, preço atual, preço-alvo (DCF), upside%
     (com seta de direção), recomendação (Compra/Neutro/Venda, colorida).
  3. Acesso rápido ao Excel individual de cada ticker (seletor + download).
  4. Gráfico comparativo de retorno (Etapa 4), com o tooltip customizado
     ordenado por retorno decrescente.

Como rodar: `streamlit run src/dashboard.py` (na raiz do projeto).

Nota técnica 1: usamos st.components.v1.html (em vez de st.plotly_chart) pro
gráfico comparativo porque o st.plotly_chart nativo do Streamlit renderiza
a figura através do próprio componente React dele, sem passar pelo
`fig.write_html(post_script=...)` — ou seja, perderíamos o JS do tooltip
customizado (Etapa 4) se usássemos st.plotly_chart. Embutindo o HTML
completo num iframe, o comportamento fica idêntico ao arquivo standalone.

Nota técnica 2 (redesign visual): a tabela de recomendações usa
`DataFrame.style` (pandas Styler) pra colorir a coluna de Recomendação por
valor — isso funciona bem com `st.dataframe`, mas o Streamlit 1.58 não
garante que a seleção interativa de linhas (`on_select=...`) funcione de
forma confiável quando o objeto passado é um Styler em vez de um DataFrame
puro (não documentado, e não dá pra confirmar visualmente rodando headless).
Por isso, em vez de "clicar na linha" para abrir o Excel, usamos um seletor
de ticker + botão de download explícito logo abaixo da tabela — mesma
funcionalidade (acesso rápido ao Excel individual), só que garantidamente
funcional.
"""

import os
import sqlite3
import sys

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
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Paleta e CSS - visual profissional (mesmo tom de azul marinho usado em
# comps_analysis.xlsx: #1F4E79), no lugar do verde/vermelho estilo "planilha
# do Excel" que estava na v1. As cores de recomendação também ficam mais
# dessaturadas/profissionais (menos "sinal de trânsito").
# ---------------------------------------------------------------------------
COR_PRIMARIA = "#1F4E79"
COR_COMPRA_TEXTO, COR_COMPRA_FUNDO = "#1B5E3B", "#E4F2E9"
COR_VENDA_TEXTO, COR_VENDA_FUNDO = "#8C2A22", "#FBEAE8"
COR_NEUTRO_TEXTO, COR_NEUTRO_FUNDO = "#54575C", "#EEEFF1"

_CSS = f"""
<style>
.block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1200px;
}}
h1 {{ color: {COR_PRIMARIA}; font-weight: 700; }}
h2, h3 {{ color: {COR_PRIMARIA}; }}
[data-testid="stMetric"] {{
    background-color: #F7F9FC;
    border: 1px solid #E3E8F0;
    border-radius: 10px;
    padding: 14px 18px;
}}
[data-testid="stMetricLabel"] {{ color: #5F6368; font-size: 0.85rem; }}
[data-testid="stMetricValue"] {{ color: {COR_PRIMARIA}; }}
hr {{ margin: 1.8rem 0; }}
</style>
"""


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
    """Aplica cor de fundo/texto por recomendação, na tabela (paleta profissional, não estilo Excel)."""
    cores = {
        "Compra": f"background-color: {COR_COMPRA_FUNDO}; color: {COR_COMPRA_TEXTO}; font-weight: 600",
        "Venda": f"background-color: {COR_VENDA_FUNDO}; color: {COR_VENDA_TEXTO}; font-weight: 600",
        "Neutro": f"background-color: {COR_NEUTRO_FUNDO}; color: {COR_NEUTRO_TEXTO}; font-weight: 600",
    }
    return cores.get(valor, "")


def seta_upside(valor: float) -> str:
    """Prefixo visual de direção (▲/▼/→) para a coluna de Upside."""
    if valor > 0:
        return "▲"
    if valor < 0:
        return "▼"
    return "→"


def main():
    st.markdown(_CSS, unsafe_allow_html=True)

    st.title("📊 Dashboard de Valuation — Ações Globais")
    st.caption(
        "AAPL · MSFT · AMZN · NVDA · GOOGL · TSM — DCF + comparativo de retorno. "
        "Metodologia completa em cada Excel individual (/valuations) e em comps_analysis.xlsx."
    )

    df = carregar_recomendacoes()
    metadados = carregar_metadados()

    # ---- Cards de KPI no topo --------------------------------------------
    n_compra = int((df["Recomendação"] == "Compra").sum())
    n_neutro = int((df["Recomendação"] == "Neutro").sum())
    n_venda = int((df["Recomendação"] == "Venda").sum())
    upside_medio = float(df["Upside"].mean())

    if not metadados.empty and metadados["atualizado_em"].notna().any():
        ultima_atualizacao = pd.to_datetime(metadados["atualizado_em"]).max()
        valor_atualizacao = ultima_atualizacao.strftime("%d/%m/%Y")
    else:
        valor_atualizacao = "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ações analisadas", len(df))
    c2.metric("Compra / Neutro / Venda", f"{n_compra} / {n_neutro} / {n_venda}")
    c3.metric("Upside médio do grupo", f"{upside_medio:+.1%}")
    c4.metric("Fundamentos atualizados em", valor_atualizacao)

    st.divider()

    # ---- Tabela de recomendações -------------------------------------------
    st.subheader("Recomendações (DCF)")

    df_exibicao = df.copy()
    df_exibicao["Preço Atual"] = df["Preço Atual"].map(lambda v: f"$ {v:,.2f}")
    df_exibicao["Preço-Alvo (DCF)"] = df["Preço-Alvo (DCF)"].map(lambda v: f"$ {v:,.2f}")
    df_exibicao["Upside"] = df["Upside"].map(lambda v: f"{seta_upside(v)} {v:+.1%}")
    df_exibicao["WACC"] = df["WACC"].map(lambda v: f"{v:.2%}")
    df_exibicao = df_exibicao[
        ["Ticker", "Empresa", "Setor", "Preço Atual", "Preço-Alvo (DCF)", "Upside", "Recomendação", "WACC"]
    ]

    estilo = df_exibicao.style.apply(
        lambda col: [cor_recomendacao(v) for v in col] if col.name == "Recomendação" else ["" for _ in col],
        axis=0,
    )
    st.dataframe(estilo, use_container_width=True, hide_index=True, height=250)

    # ---- Acesso rápido ao Excel individual --------------------------------
    col_sel, col_btn = st.columns([3, 1])
    ticker_selecionado = col_sel.selectbox(
        "Ver Excel de valuation detalhado de:", df["Ticker"].tolist(), label_visibility="visible"
    )
    caminho_excel = os.path.join(config.DIR_VALUATIONS, f"{ticker_selecionado}.xlsx")
    with col_btn:
        st.write("")  # alinhamento vertical com o selectbox
        if os.path.exists(caminho_excel):
            with open(caminho_excel, "rb") as f:
                st.download_button(
                    "⬇ Baixar Excel",
                    data=f.read(),
                    file_name=f"{ticker_selecionado}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        else:
            st.caption("Excel não encontrado.")

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

    st.divider()

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
