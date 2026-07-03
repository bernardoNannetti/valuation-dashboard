"""
Dashboard HTML customizado — substitui a versão Streamlit como o "produto
final" visual do projeto.
================================================================================
Por quê trocar de Streamlit para HTML/CSS/JS puro: Streamlit tem um teto
visual (é um conjunto fixo de widgets, dá pra customizar CSS mas só até
certo ponto). Gerando o HTML do zero temos controle total do design —
tipografia, cards, tabela ordenável, barras de upside — sem as limitações
do framework. O preço é perder a reatividade de servidor: este arquivo é
ESTÁTICO (dados congelados no momento da geração), por isso entra no
pipeline diário do atualizar_tudo.py, igual o gráfico e os Excels.

O app Streamlit (src/dashboard.py) continua no repositório como referência
técnica (mostra domínio das duas abordagens), mas dashboard.html é a versão
"para mostrar".

Segunda rodada de melhorias (pós-feedback visual):
  - Cada linha da tabela expande (clique na linha) num painel de detalhe
    com o breakdown do WACC (CAPM), as premissas do DCF (crescimento,
    capex%, margem) e um cross-check com os múltiplos de comps
    (EV/Revenue, EV/EBITDA, P/E vs. mediana do grupo) — mesmos números do
    comps_analysis.xlsx, recalculados aqui a partir do banco (não faz
    parsing do Excel, que seria frágil).
  - Modo escuro (toggle no header, persistido em localStorage — aqui é
    seguro usar localStorage: isto é um arquivo estático de verdade, aberto
    direto no navegador do usuário via file://, não um artifact renderizado
    dentro do Claude).
  - Folha de estilo de impressão (@media print).
  - Gráfico comparativo restilizado (ver returns_chart.py:
    modo_standalone=False) — fundo transparente, fonte/paleta do
    dashboard, sem o modebar e os botões nativos "engessados" do Plotly;
    os botões YTD/12M/24M/36M agora são HTML custom (mesmo estilo dos
    outros controles do site) que chamam Plotly.update() diretamente.

Como usar:
  - Gerar/atualizar:      python -m src.dashboard_export
  - Ver o resultado:      abrir dashboard.html direto no navegador (arquivo
                           estático, não precisa rodar nenhum servidor)
  - Atualização completa: python -m src.atualizar_tudo (roda isso como
                           último passo, depois do gráfico e dos Excels)

Nota técnica sobre como o HTML é montado: usamos um template com
placeholders (__ALGO__) e `.replace()` sequencial, em vez de f-string ou
`%`-formatting no texto inteiro. Já tomamos essa decisão em returns_chart.py
(_JS_TOOLTIP_CUSTOMIZADO) depois de um bug real: o CSS/JS embutido tem
literais `%` (ex: `border-radius: 50%`) e `{ }` (funções JS) por todo lado,
que colidem com `%`-formatting e f-strings respectivamente. `.replace()`
com marcadores únicos não tem esse problema.
"""

import json
import os
import sqlite3
import statistics
from datetime import datetime

import plotly.io as pio

from . import comps_analysis
from . import config
from . import dcf
from . import returns_chart

CAMINHO_SAIDA = os.path.join(config.DIR_RAIZ, "dashboard.html")


# ---------------------------------------------------------------------------
# Camada de dados: DCF + comps, prontos para virar JSON no template
# ---------------------------------------------------------------------------

def _montar_comps(conn) -> dict:
    """
    Recalcula os múltiplos de valuation (EV/Revenue, EV/EBITDA, P/E) e
    métricas operacionais (margens, crescimento) direto do banco — MESMA
    fonte e MESMAS fórmulas do comps_analysis.xlsx (reaproveita
    comps_analysis._obter_dados_empresa), só que em Python puro em vez de
    fórmula de Excel. Não faz parsing do .xlsx (seria frágil a mudanças de
    layout da planilha).
    """
    resultado = {}
    for ticker in config.TICKERS:
        d = comps_analysis._obter_dados_empresa(conn, ticker)
        ev = d["market_cap"] + d["net_debt"]
        resultado[ticker] = {
            "ev": ev,
            "evRevenue": (ev / d["receita_atual"]) if d["receita_atual"] else None,
            "evEbitda": (ev / d["ebitda"]) if d["ebitda"] else None,
            "pe": (d["market_cap"] / d["net_income"]) if d["net_income"] else None,
            "revenueGrowth": (
                (d["receita_atual"] - d["receita_anterior"]) / d["receita_anterior"]
                if d["receita_anterior"] else None
            ),
            "grossMargin": (d["gross_profit"] / d["receita_atual"]) if d["receita_atual"] else None,
            "ebitdaMargin": (d["ebitda"] / d["receita_atual"]) if d["receita_atual"] else None,
            "fcfMargin": (d["fcf"] / d["receita_atual"]) if d["receita_atual"] else None,
        }
    return resultado


def _estatisticas_grupo(comps: dict) -> dict:
    """Mediana do grupo pras 3 métricas usadas no cross-check do painel de detalhe."""
    def mediana(chave):
        valores = [v[chave] for v in comps.values() if v.get(chave) is not None]
        return statistics.median(valores) if valores else None

    return {
        "evRevenueMed": mediana("evRevenue"),
        "evEbitdaMed": mediana("evEbitda"),
        "peMed": mediana("pe"),
    }


def _montar_linhas_recomendacao() -> tuple:
    """DCF + comps das 6 ações -> lista de dicts prontos para virar JSON no template."""
    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    comps = _montar_comps(conn)
    stats_grupo = _estatisticas_grupo(comps)

    linhas = []
    for ticker in config.TICKERS:
        r = dcf.calcular_dcf(ticker, conn)
        w = r["wacc_detalhe"]
        linhas.append({
            "ticker": r["ticker"],
            "empresa": r["nome"],
            "setor": r["setor"],
            "precoAtual": round(r["preco_atual"], 2),
            "precoAlvo": round(r["preco_alvo"], 2),
            "upside": round(r["upside"], 4),
            "recomendacao": r["recomendacao"],
            "wacc": round(r["wacc_detalhe"]["wacc"], 4),
            "cor": returns_chart.CORES.get(r["ticker"], "#1F4E79"),
            "dcf": {
                "beta": round(w["beta"], 3),
                "rf": round(w["taxa_livre_de_risco"], 4),
                "erp": round(w["premio_risco_mercado"], 4),
                "custoEquity": round(w["custo_capital_proprio"], 4),
                "custoDividaPosImposto": round(w["custo_divida_pos_imposto"], 4),
                "pesoEquity": round(w["peso_equity"], 4),
                "pesoDivida": round(w["peso_divida"], 4),
                "margemEbit": round(r["margem_ebit"], 4),
                "pctDa": round(r["pct_da"], 4),
                "pctCapexHist": round(r["pct_capex_historico"], 4),
                "pctCapexAno1": round(r["pct_capex_inicial"], 4),
                "pctWc": round(r["pct_variacao_wc"], 4),
                "taxaImposto": round(r["taxa_imposto_efetiva"], 4),
                "crescimentoAno1": round(r["crescimento_ano1"], 4),
                "crescimentoPerpetuidade": round(r["crescimento_perpetuidade"], 4),
                "horizonte": r["horizonte_projecao_anos"],
                "receitaBase": r["receita_base"],
                "receitasProjetadas": [round(x, 0) for x in r["receitas_projetadas"]],
                "fcffsProjetados": [round(x, 0) for x in r["fcffs_projetados"]],
                "valorPresenteTerminal": round(r["valor_presente_terminal"], 0),
                "somaPvFcff": round(sum(r["valores_presentes_fcff"]), 0),
                "valorEmpresa": round(r["valor_empresa"], 0),
                "dividaLiquida": round(r["divida_liquida"], 0),
                "valorEquity": round(r["valor_equity"], 0),
                "sharesOutstanding": round(r["shares_outstanding"], 0),
            },
            "comps": comps[ticker],
        })
    conn.close()
    return linhas, stats_grupo


def _montar_metadados() -> list:
    """Datas de divulgação de resultado, por ticker (pro rodapé/painel expansível)."""
    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    cur = conn.execute(
        "SELECT ticker, ultima_divulgacao_resultado, proxima_divulgacao_resultado, "
        "atualizado_em FROM empresas"
    )
    colunas = [c[0] for c in cur.description]
    linhas = [dict(zip(colunas, linha)) for linha in cur.fetchall()]
    conn.close()
    return linhas


def _gerar_html_grafico() -> str:
    """
    Gráfico comparativo em modo 'dashboard' (returns_chart.gerar_grafico com
    modo_standalone=False): sem título/eixos/botões nativos — o card já tem
    título, e os botões viram controles HTML customizados (ver
    __JANELAS_JSON__/__TICKERS_JSON__ no template). Escondemos o modebar
    padrão do Plotly (ícones de câmera/zoom no canto) via `config`, que
    fica com um ar "de ferramenta genérica" destoante do resto do site.
    """
    fig = returns_chart.gerar_grafico(modo_standalone=False)
    return pio.to_html(
        fig,
        div_id=returns_chart.DIV_ID_GRAFICO,
        post_script=returns_chart._JS_TOOLTIP_CUSTOMIZADO,
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": False, "responsive": True},
    )


def _montar_dados_janelas_grafico() -> dict:
    """Dados pré-calculados por janela (YTD/12M/24M/36M), pros botões HTML customizados."""
    precos = returns_chart.carregar_precos_do_banco()
    return returns_chart.calcular_dados_por_janela(precos)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard de Valuation — Ações Globais</title>
<script>
  // Aplica o tema salvo ANTES do primeiro paint (evita "flash" de tema
  // errado ao abrir a página). Roda fora de qualquer bloco defer/async,
  // colado no <head>, de propósito.
  (function() {
    var salvo = null;
    try { salvo = localStorage.getItem('tema-dashboard'); } catch (e) {}
    var tema = salvo || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', tema);
  })();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
  :root {
    --navy: #0F2942;
    --heading: #0F2942;
    --accent: #2E6FE0;
    --bg-grad-1: #F6F8FC; --bg-grad-2: #EEF2F8; --bg-grad-3: #EAF0F9;
    --card: #FFFFFF;
    --border: #E5E9F0;
    --text-1: #101828;
    --text-2: #667085;
    --text-3: #98A2B3;
    --surface-1: #FAFBFD;
    --surface-2: #F8FAFE;
    --green-tx: #0B7A46; --green-bg: #E5F6EE; --green-bd: #B7E9D0;
    --red-tx: #B3261E;   --red-bg: #FCEBEA;   --red-bd: #F5C2BE;
    --gray-tx: #54575C;  --gray-bg: #EEF1F4;  --gray-bd: #DDE2E8;
    --blue-icon-bg: #EAF1FE;
    --action-bg: #EAF1FE; --action-bd: #D6E4FC; --action-hover: #DCE9FE;
    --segmented-bg: #F1F2F4; --segmented-active-bg: #FFFFFF;
    --shadow-sm: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06);
    --shadow-md: 0 4px 8px rgba(16,24,40,0.04), 0 8px 20px rgba(16,24,40,0.08);
  }
  html[data-theme="dark"] {
    --navy: #E8ECF3;
    --heading: #EDF1F8;
    --accent: #6E9BF5;
    --bg-grad-1: #0B1220; --bg-grad-2: #0D1526; --bg-grad-3: #0A0F1C;
    --card: #121A2B;
    --border: #232E45;
    --text-1: #E6E9F0;
    --text-2: #97A2B8;
    --text-3: #67728C;
    --surface-1: #162033;
    --surface-2: #182136;
    --green-tx: #3DD68C; --green-bg: rgba(61,214,140,0.12); --green-bd: rgba(61,214,140,0.35);
    --red-tx: #F2685E;   --red-bg: rgba(242,104,94,0.12);   --red-bd: rgba(242,104,94,0.35);
    --gray-tx: #A6B0C3;  --gray-bg: rgba(166,176,195,0.12); --gray-bd: rgba(166,176,195,0.3);
    --blue-icon-bg: rgba(110,155,245,0.15);
    --action-bg: rgba(110,155,245,0.14); --action-bd: rgba(110,155,245,0.35); --action-hover: rgba(110,155,245,0.24);
    --segmented-bg: #182136; --segmented-active-bg: #23304A;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.24), 0 1px 3px rgba(0,0,0,0.28);
    --shadow-md: 0 4px 10px rgba(0,0,0,0.32), 0 10px 24px rgba(0,0,0,0.4);
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: linear-gradient(160deg, var(--bg-grad-1) 0%, var(--bg-grad-2) 45%, var(--bg-grad-3) 100%);
    color: var(--text-1);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
    transition: background .2s ease, color .2s ease;
  }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 40px 28px 64px; }

  /* ---------- Header ---------- */
  .header { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-bottom: 32px; flex-wrap: wrap; }
  .header-left { display: flex; align-items: center; gap: 16px; }
  .logo-badge {
    width: 52px; height: 52px; border-radius: 14px;
    background: linear-gradient(135deg, #0F2942 0%, #2E6FE0 100%);
    display: flex; align-items: center; justify-content: center;
    box-shadow: var(--shadow-md); flex-shrink: 0;
  }
  .logo-badge svg { width: 26px; height: 26px; stroke: #fff; }
  .kicker { font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); margin: 0 0 4px; }
  h1 { font-size: 26px; font-weight: 800; margin: 0; color: var(--heading); letter-spacing: -0.02em; }
  .subtitle { font-size: 14px; color: var(--text-2); margin: 6px 0 0; max-width: 620px; line-height: 1.5; }
  .header-right { display: flex; align-items: center; gap: 10px; }
  .updated-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: var(--card); border: 1px solid var(--border); border-radius: 999px;
    padding: 8px 16px; font-size: 13px; color: var(--text-2); box-shadow: var(--shadow-sm);
    white-space: nowrap;
  }
  .updated-pill svg { width: 15px; height: 15px; stroke: var(--accent); }
  .updated-pill strong { color: var(--text-1); font-weight: 600; }
  .theme-toggle {
    width: 38px; height: 38px; border-radius: 999px; background: var(--card); border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center; cursor: pointer; box-shadow: var(--shadow-sm);
    flex-shrink: 0; transition: background .15s;
  }
  .theme-toggle:hover { background: var(--surface-2); }
  .theme-toggle svg { width: 17px; height: 17px; stroke: var(--text-2); }

  /* ---------- KPI cards ---------- */
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px; }
  .kpi-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 16px;
    padding: 20px 22px; box-shadow: var(--shadow-sm);
    transition: box-shadow .2s ease, transform .2s ease;
  }
  .kpi-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
  .kpi-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .kpi-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }
  .kpi-icon svg { width: 18px; height: 18px; }
  .kpi-icon.blue { background: var(--blue-icon-bg); } .kpi-icon.blue svg { stroke: var(--accent); }
  .kpi-icon.green { background: var(--green-bg); } .kpi-icon.green svg { stroke: var(--green-tx); }
  .kpi-icon.red { background: var(--red-bg); } .kpi-icon.red svg { stroke: var(--red-tx); }
  .kpi-icon.gray { background: var(--gray-bg); } .kpi-icon.gray svg { stroke: var(--gray-tx); }
  .kpi-value { font-size: 26px; font-weight: 800; color: var(--heading); letter-spacing: -0.02em; line-height: 1; }
  .kpi-label { font-size: 12.5px; color: var(--text-2); margin-top: 6px; }

  /* ---------- Cards / sections ---------- */
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 18px; box-shadow: var(--shadow-sm); margin-bottom: 24px; overflow: hidden; }
  .card-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 24px 16px; flex-wrap: wrap; gap: 12px; }
  .card-title { font-size: 16px; font-weight: 700; color: var(--heading); margin: 0; }
  .card-subtitle { font-size: 12.5px; color: var(--text-3); margin-top: 2px; }

  .search-box { position: relative; }
  .search-box svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 15px; height: 15px; stroke: var(--text-3); }
  .search-box input {
    font-family: inherit; font-size: 13.5px; padding: 9px 12px 9px 34px; width: 220px;
    border: 1px solid var(--border); border-radius: 10px; outline: none; color: var(--text-1);
    background: var(--surface-1); transition: border-color .15s;
  }
  .search-box input:focus { border-color: var(--accent); }

  /* Controle segmentado (usado nos botões YTD/12M/24M/36M do gráfico) */
  .segmented { display: inline-flex; background: var(--segmented-bg); padding: 4px; border-radius: 10px; gap: 2px; }
  .segmented button {
    border: none; background: transparent; padding: 7px 14px; border-radius: 7px;
    font: 600 12.5px 'Inter', sans-serif; color: var(--text-2); cursor: pointer; transition: all .15s;
  }
  .segmented button.active { background: var(--segmented-active-bg); color: var(--heading); box-shadow: var(--shadow-sm); }
  .segmented button:hover:not(.active) { color: var(--text-1); }

  .table-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13.5px; min-width: 760px; }
  thead th {
    text-align: left; font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
    color: var(--text-3); padding: 10px 20px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
    background: var(--surface-1); cursor: pointer; user-select: none; white-space: nowrap;
  }
  thead th.col-expand { cursor: default; width: 34px; padding-left: 24px; padding-right: 0; }
  thead th:hover:not(.col-expand) { color: var(--accent); }
  thead th .th-inner { display: inline-flex; align-items: center; gap: 4px; }
  thead th svg { width: 12px; height: 12px; stroke: currentColor; opacity: 0.45; transition: transform .15s; }
  thead th.sort-desc svg { opacity: 1; transform: rotate(0deg); }
  thead th.sort-asc svg { opacity: 1; transform: rotate(180deg); }
  tbody tr.linha-dados { border-bottom: 1px solid var(--border); cursor: pointer; transition: background .12s; }
  tbody tr.linha-dados:hover { background: var(--surface-2); }
  tbody tr.linha-detalhe { background: var(--surface-1); border-bottom: 1px solid var(--border); }
  tbody tr:last-child { border-bottom: none; }
  tbody td { padding: 13px 20px; vertical-align: middle; }
  td.col-expand { padding-left: 24px; padding-right: 0; }

  .chevron { width: 15px; height: 15px; stroke: var(--text-3); transition: transform .18s ease; }
  .linha-dados.expandida .chevron { transform: rotate(90deg); stroke: var(--accent); }

  .ticker-cell { display: flex; align-items: center; gap: 10px; }
  .ticker-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
  .ticker-code { font-weight: 700; color: var(--heading); font-size: 13.5px; }
  .empresa-nome { color: var(--text-1); }

  .num-cell { font-variant-numeric: tabular-nums; color: var(--text-1); }
  .mono { font-family: 'JetBrains Mono', monospace; }

  .upside-cell { min-width: 150px; }
  .upside-track { position: relative; height: 6px; background: var(--gray-bg); border-radius: 999px; margin-bottom: 5px; overflow: hidden; }
  .upside-fill { position: absolute; top: 0; height: 100%; border-radius: 999px; }
  .upside-fill.pos { background: var(--green-tx); }
  .upside-fill.neg { background: var(--red-tx); }
  .upside-center { position: absolute; left: 50%; top: -2px; width: 1px; height: 10px; background: var(--text-3); opacity: .5; }
  .upside-text { font-weight: 700; font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .upside-text.pos { color: var(--green-tx); }
  .upside-text.neg { color: var(--red-tx); }

  .badge { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; padding: 4px 11px; border-radius: 999px; border: 1px solid; }
  .badge.compra { color: var(--green-tx); background: var(--green-bg); border-color: var(--green-bd); }
  .badge.venda  { color: var(--red-tx); background: var(--red-bg); border-color: var(--red-bd); }
  .badge.neutro { color: var(--gray-tx); background: var(--gray-bg); border-color: var(--gray-bd); }

  .action-btn {
    display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600;
    color: var(--accent); background: var(--action-bg); border: 1px solid var(--action-bd); border-radius: 8px;
    padding: 6px 11px; text-decoration: none; transition: background .12s;
  }
  .action-btn:hover { background: var(--action-hover); }
  .action-btn svg { width: 13px; height: 13px; stroke: currentColor; }

  /* ---------- Painel de detalhe (expandido por linha) ---------- */
  .detail-panel { padding: 18px 24px 22px 54px; display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 22px; }
  .detail-block h4 {
    font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
    color: var(--text-3); margin: 0 0 10px;
  }
  .detail-row-item { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; font-size: 12.5px; }
  .detail-row-item .lbl { color: var(--text-2); }
  .detail-row-item .val { color: var(--text-1); font-weight: 600; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
  .detail-row-item .val.hi { color: var(--accent); }
  .detail-note { font-size: 11.5px; color: var(--text-3); margin-top: 8px; line-height: 1.5; }
  .fcff-strip { display: flex; gap: 6px; margin-top: 10px; }
  .fcff-chip { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 6px 4px; text-align: center; }
  .fcff-chip .ano { font-size: 9.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
  .fcff-chip .val { display: block; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700; margin-top: 2px; }
  .fcff-chip .val.pos { color: var(--green-tx); } .fcff-chip .val.neg { color: var(--red-tx); }

  .chart-toolbar { padding: 0 24px 8px; }
  .chart-wrap { padding: 4px 16px 20px; }

  .footer { margin-top: 8px; padding: 20px 4px 0; border-top: 1px solid var(--border); }
  .footer p { font-size: 12.5px; color: var(--text-3); line-height: 1.7; margin: 0 0 8px; }
  .footer code { background: var(--surface-1); padding: 1px 5px; border-radius: 4px; }
  .footer .tech { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-3); margin-top: 12px; }

  .empty-state { padding: 40px 24px; text-align: center; color: var(--text-3); font-size: 13.5px; }

  @media (max-width: 900px) {
    .wrap { padding: 24px 16px 48px; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
    table { font-size: 12.5px; }
    thead th, tbody td { padding: 10px 12px; }
    .detail-panel { padding: 16px 14px 18px 30px; grid-template-columns: 1fr; }
    .search-box input { width: 150px; }
  }
  @media (max-width: 520px) {
    .kpi-grid { grid-template-columns: 1fr 1fr; }
    h1 { font-size: 21px; }
    .card-header { flex-direction: column; align-items: flex-start; }
  }

  @media print {
    html, body { background: #fff !important; }
    .theme-toggle, .search-box, .action-btn, thead th svg, .chart-toolbar { display: none !important; }
    .wrap { max-width: 100% !important; padding: 10px !important; }
    .card { box-shadow: none !important; border: 1px solid #ddd !important; break-inside: avoid; }
    .kpi-card { box-shadow: none !important; border: 1px solid #ddd !important; }
    .kpi-card:hover { transform: none !important; }
    tbody tr.linha-dados:hover { background: transparent !important; }
    a[href]:after { content: none !important; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div class="header-left">
      <div class="logo-badge">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
      </div>
      <div>
        <p class="kicker">Dashboard de Valuation</p>
        <h1>Ações Globais</h1>
        <p class="subtitle">AAPL · MSFT · AMZN · NVDA · GOOGL · TSM — modelo de DCF (WACC via CAPM) comparado ao preço de mercado, com cross-check por múltiplos de comps.</p>
      </div>
    </div>
    <div class="header-right">
      <div class="updated-pill">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
        Atualizado em <strong>__DATA_ATUALIZACAO__</strong>
      </div>
      <button class="theme-toggle" id="botao-tema" title="Alternar tema" aria-label="Alternar tema claro/escuro"></button>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-top">
        <div class="kpi-icon blue"><svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg></div>
      </div>
      <div class="kpi-value">__KPI_TOTAL__</div>
      <div class="kpi-label">Ações analisadas</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-top">
        <div class="kpi-icon green"><svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg></div>
      </div>
      <div class="kpi-value">__KPI_COMPRA__ / __KPI_NEUTRO__ / __KPI_VENDA__</div>
      <div class="kpi-label">Compra / Neutro / Venda</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-top">
        <div class="kpi-icon __KPI_UPSIDE_COR__"><svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="5" x2="5" y2="19"></line><circle cx="6.5" cy="6.5" r="2.5"></circle><circle cx="17.5" cy="17.5" r="2.5"></circle></svg></div>
      </div>
      <div class="kpi-value">__KPI_UPSIDE_MEDIO__</div>
      <div class="kpi-label">Upside médio do grupo (DCF vs. mercado)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-top">
        <div class="kpi-icon blue"><svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg></div>
      </div>
      <div class="kpi-value">__KPI_WACC_MEDIO__</div>
      <div class="kpi-label">WACC médio do grupo</div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <div>
        <h2 class="card-title">Recomendações (DCF)</h2>
        <p class="card-subtitle">Clique numa coluna pra ordenar · clique numa linha pra ver o detalhamento (WACC, premissas e comps)</p>
      </div>
      <div class="search-box">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        <input id="filtro" type="text" placeholder="Buscar ticker ou empresa...">
      </div>
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr id="cabecalho-tabela"></tr>
        </thead>
        <tbody id="corpo-tabela"></tbody>
      </table>
    </div>
    <div id="vazio" class="empty-state" style="display:none;">Nenhum resultado para essa busca.</div>
  </div>

  <div class="card">
    <div class="card-header">
      <div>
        <h2 class="card-title">Retorno comparativo</h2>
        <p class="card-subtitle">Retorno acumulado normalizado (base 100 no início de cada janela) · linha pontilhada = S&amp;P 500 (benchmark)</p>
      </div>
    </div>
    <div class="chart-toolbar">
      <div class="segmented" id="janela-toggle">
        <button data-janela="YTD">YTD</button>
        <button data-janela="12M">12M</button>
        <button data-janela="24M">24M</button>
        <button data-janela="36M" class="active">36M</button>
      </div>
    </div>
    <div class="chart-wrap">
      __GRAFICO_HTML__
    </div>
  </div>

  <div class="footer">
    <p><strong>Metodologia:</strong> DCF de horizonte de 5 anos, WACC calculado via CAPM (beta, Treasury 10Y como taxa livre de risco, prêmio de risco de mercado Damodaran), crescimento com fade até a perpetuidade (2,5%). Threshold de recomendação: upside &gt; __THRESHOLD_COMPRA__ = Compra, &lt; __THRESHOLD_VENDA__ = Venda, entre isso = Neutro.</p>
    <p>DCF de horizonte curto tende a subestimar mega caps de alto crescimento — clique numa linha da tabela pra ver o cross-check com múltiplos de comps (EV/Revenue, EV/EBITDA, P/E vs. mediana do grupo). Detalhamento completo de cada valuation em <code>/valuations/{ticker}.xlsx</code> e <code>comps_analysis.xlsx</code>.</p>
    <p class="tech">Gerado em __TIMESTAMP_GERACAO__ · Python (yfinance, pandas, Plotly) + SQLite + HTML/CSS/JS</p>
  </div>

</div>

<script>
const DADOS = __DADOS_JSON__;
const STATS_GRUPO = __STATS_GRUPO_JSON__;
const JANELAS_GRAFICO = __JANELAS_JSON__;
const TICKERS_GRAFICO = __TICKERS_JSON__;
const CORES_BADGE = { "Compra": "compra", "Venda": "venda", "Neutro": "neutro" };

function fmtUSD(v) {
  return "US$ " + v.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
function fmtPctSigned(v) {
  const s = (v * 100).toFixed(1).replace('.', ',');
  return (v >= 0 ? '+' : '') + s + '%';
}
function fmtPctPlain(v) {
  if (v === null || v === undefined) return '—';
  return (v * 100).toFixed(2).replace('.', ',') + '%';
}
function fmtX(v) {
  if (v === null || v === undefined) return '—';
  return v.toFixed(1).replace('.', ',') + 'x';
}
function fmtBi(v) {
  if (v === null || v === undefined) return '—';
  return (v / 1e9).toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + 'B';
}

const COLUNAS = [
  { chave: '_expand',      rotulo: '',           ordenavel: false },
  { chave: 'ticker',       rotulo: 'Ticker',     ordenavel: true  },
  { chave: 'setor',        rotulo: 'Setor',      ordenavel: true  },
  { chave: 'precoAtual',   rotulo: 'Preço Atual',ordenavel: true  },
  { chave: 'precoAlvo',    rotulo: 'Preço-Alvo', ordenavel: true  },
  { chave: 'upside',       rotulo: 'Upside',     ordenavel: true  },
  { chave: 'recomendacao', rotulo: 'Recomendação', ordenavel: true  },
  { chave: 'wacc',         rotulo: 'WACC',       ordenavel: true  },
  { chave: '_acao',        rotulo: '',           ordenavel: false },
];

let ordenarPor = 'upside';
let ordemAsc = false;
const expandidos = new Set();

function montarCabecalho() {
  const tr = document.getElementById('cabecalho-tabela');
  tr.innerHTML = '';
  COLUNAS.forEach(col => {
    const th = document.createElement('th');
    if (col.chave === '_expand') { th.className = 'col-expand'; tr.appendChild(th); return; }
    if (col.ordenavel) {
      let classe = '';
      if (ordenarPor === col.chave) classe = ordemAsc ? 'sort-asc' : 'sort-desc';
      th.className = classe;
      th.innerHTML = '<span class="th-inner">' + col.rotulo +
        '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg></span>';
      th.addEventListener('click', () => {
        if (ordenarPor === col.chave) { ordemAsc = !ordemAsc; }
        else { ordenarPor = col.chave; ordemAsc = false; }
        renderizar();
      });
    } else {
      th.textContent = col.rotulo;
    }
    tr.appendChild(th);
  });
}

function compsRowHTML(item) {
  const c = item.comps;
  const linha = (label, valor, mediana, fmt) => {
    const acimaOuAbaixo = (valor !== null && mediana !== null)
      ? (valor > mediana ? ' <span class="lbl">(acima da mediana)</span>' : ' <span class="lbl">(abaixo da mediana)</span>')
      : '';
    return '<div class="detail-row-item"><span class="lbl">' + label + '</span>' +
      '<span class="val">' + fmt(valor) + ' <span class="lbl">· grupo ' + fmt(mediana) + '</span></span></div>';
  };
  return '' +
    '<div class="detail-block"><h4>Cross-check · Comps</h4>' +
    linha('EV / Revenue', c.evRevenue, STATS_GRUPO.evRevenueMed, fmtX) +
    linha('EV / EBITDA', c.evEbitda, STATS_GRUPO.evEbitdaMed, fmtX) +
    linha('P/E', c.pe, STATS_GRUPO.peMed, fmtX) +
    '<div class="detail-row-item"><span class="lbl">Margem EBITDA</span><span class="val">' + fmtPctPlain(c.ebitdaMargin) + '</span></div>' +
    '<div class="detail-row-item"><span class="lbl">Crescimento receita (YoY)</span><span class="val">' + fmtPctPlain(c.revenueGrowth) + '</span></div>' +
    '<p class="detail-note">Mesma fonte/fórmulas do comps_analysis.xlsx. TSM tem modelo de negócio diferente do restante do grupo (manufatura vs. plataformas) — ver ressalva de comparabilidade na planilha.</p>' +
    '</div>';
}

function detalheHTML(item) {
  const d = item.dcf;
  const anos = d.fcffsProjetados.map((_, i) => 'Y' + (i + 1));
  const fcffStrip = d.fcffsProjetados.map((v, i) =>
    '<div class="fcff-chip"><span class="ano">' + anos[i] + '</span>' +
    '<span class="val ' + (v >= 0 ? 'pos' : 'neg') + '">' + fmtBi(v) + '</span></div>'
  ).join('');

  return '' +
    '<tr class="linha-detalhe" data-detalhe-de="' + item.ticker + '"><td colspan="9"><div class="detail-panel">' +
      '<div class="detail-block"><h4>WACC (CAPM)</h4>' +
        '<div class="detail-row-item"><span class="lbl">Beta</span><span class="val">' + d.beta.toFixed(2) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Taxa livre de risco</span><span class="val">' + fmtPctPlain(d.rf) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Prêmio de risco (ERP)</span><span class="val">' + fmtPctPlain(d.erp) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Custo do equity</span><span class="val">' + fmtPctPlain(d.custoEquity) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Custo da dívida (pós-imp.)</span><span class="val">' + fmtPctPlain(d.custoDividaPosImposto) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Peso equity / dívida</span><span class="val">' + fmtPctPlain(d.pesoEquity) + ' / ' + fmtPctPlain(d.pesoDivida) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">WACC final</span><span class="val hi">' + fmtPctPlain(item.wacc) + '</span></div>' +
      '</div>' +
      '<div class="detail-block"><h4>Premissas do DCF</h4>' +
        '<div class="detail-row-item"><span class="lbl">Crescimento ano 1 → perpetuidade</span><span class="val">' + fmtPctPlain(d.crescimentoAno1) + ' → ' + fmtPctPlain(d.crescimentoPerpetuidade) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Margem EBIT histórica</span><span class="val">' + fmtPctPlain(d.margemEbit) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">CapEx % (histórico → ano 1)</span><span class="val">' + fmtPctPlain(d.pctCapexHist) + ' → ' + fmtPctPlain(d.pctCapexAno1) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">D&amp;A % da receita</span><span class="val">' + fmtPctPlain(d.pctDa) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Taxa de imposto efetiva</span><span class="val">' + fmtPctPlain(d.taxaImposto) + '</span></div>' +
        '<div class="detail-row-item"><span class="lbl">Horizonte de projeção</span><span class="val">' + d.horizonte + ' anos</span></div>' +
        '<div class="fcff-strip">' + fcffStrip + '</div>' +
        '<p class="detail-note">FCFF projetado por ano (bilhões de US$), horizonte explícito.</p>' +
      '</div>' +
      compsRowHTML(item) +
    '</div></td></tr>';
}

function linhaHTML(item, maxAbsUpside) {
  const classeBadge = CORES_BADGE[item.recomendacao] || 'neutro';
  const upsidePos = item.upside >= 0;
  const larguraBarra = maxAbsUpside > 0 ? Math.min(Math.abs(item.upside) / maxAbsUpside * 50, 50) : 0;
  const estiloFill = upsidePos
    ? 'left:50%; width:' + larguraBarra + '%;'
    : 'right:50%; width:' + larguraBarra + '%;';
  const expandida = expandidos.has(item.ticker);

  let html = '' +
    '<tr class="linha-dados' + (expandida ? ' expandida' : '') + '" onclick="alternarDetalhe(\'' + item.ticker + '\')">' +
      '<td class="col-expand"><svg class="chevron" viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"></polyline></svg></td>' +
      '<td><div class="ticker-cell">' +
        '<span class="ticker-dot" style="background:' + item.cor + '"></span>' +
        '<div><div class="ticker-code">' + item.ticker + '</div>' +
        '<div class="empresa-nome">' + item.empresa + '</div></div>' +
      '</div></td>' +
      '<td class="num-cell">' + item.setor + '</td>' +
      '<td class="num-cell mono">' + fmtUSD(item.precoAtual) + '</td>' +
      '<td class="num-cell mono">' + fmtUSD(item.precoAlvo) + '</td>' +
      '<td class="upside-cell">' +
        '<div class="upside-track"><div class="upside-center"></div>' +
          '<div class="upside-fill ' + (upsidePos ? 'pos' : 'neg') + '" style="' + estiloFill + '"></div>' +
        '</div>' +
        '<div class="upside-text ' + (upsidePos ? 'pos' : 'neg') + '">' + fmtPctSigned(item.upside) + '</div>' +
      '</td>' +
      '<td><span class="badge ' + classeBadge + '">' + item.recomendacao + '</span></td>' +
      '<td class="num-cell mono">' + fmtPctPlain(item.wacc) + '</td>' +
      '<td onclick="event.stopPropagation();">' +
        '<a class="action-btn" href="valuations/' + item.ticker + '.xlsx" target="_blank" rel="noopener">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>' +
          'Excel' +
        '</a>' +
      '</td>' +
    '</tr>';

  if (expandida) html += detalheHTML(item);
  return html;
}

function alternarDetalhe(ticker) {
  if (expandidos.has(ticker)) expandidos.delete(ticker);
  else expandidos.add(ticker);
  renderizar();
}

function renderizar() {
  const termo = document.getElementById('filtro').value.trim().toLowerCase();
  let linhas = DADOS.filter(d =>
    d.ticker.toLowerCase().includes(termo) || d.empresa.toLowerCase().includes(termo)
  );

  linhas.sort((a, b) => {
    let va = a[ordenarPor], vb = b[ordenarPor];
    if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
    if (va < vb) return ordemAsc ? -1 : 1;
    if (va > vb) return ordemAsc ? 1 : -1;
    return 0;
  });

  const maxAbsUpside = Math.max(...DADOS.map(d => Math.abs(d.upside)), 0.0001);
  const corpo = document.getElementById('corpo-tabela');
  corpo.innerHTML = linhas.map(item => linhaHTML(item, maxAbsUpside)).join('');
  document.getElementById('vazio').style.display = linhas.length === 0 ? 'block' : 'none';

  montarCabecalho();
}

document.getElementById('filtro').addEventListener('input', renderizar);
montarCabecalho();
renderizar();

// ---- Tema claro/escuro -----------------------------------------------
function iconeTema(tema) {
  return tema === 'dark'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';
}
function aplicarTema(tema) {
  document.documentElement.setAttribute('data-theme', tema);
  document.getElementById('botao-tema').innerHTML = iconeTema(tema);
  try { localStorage.setItem('tema-dashboard', tema); } catch (e) {}
}
document.getElementById('botao-tema').addEventListener('click', () => {
  const atual = document.documentElement.getAttribute('data-theme');
  aplicarTema(atual === 'dark' ? 'light' : 'dark');
});
aplicarTema(document.documentElement.getAttribute('data-theme') || 'light');

// ---- Botões YTD/12M/24M/36M do gráfico (custom, no lugar dos nativos) --
document.querySelectorAll('#janela-toggle button').forEach(btn => {
  btn.addEventListener('click', () => {
    const janela = btn.dataset.janela;
    const dadosJanela = JANELAS_GRAFICO[janela];
    if (!dadosJanela || typeof Plotly === 'undefined') return;
    const xs = TICKERS_GRAFICO.map(t => dadosJanela[t].x);
    const ys = TICKERS_GRAFICO.map(t => dadosJanela[t].y);
    const texts = TICKERS_GRAFICO.map(t => dadosJanela[t].text);
    Plotly.update(document.getElementById('__DIV_ID_GRAFICO__'), { x: xs, y: ys, text: texts });
    document.querySelectorAll('#janela-toggle button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});
</script>
</body>
</html>
"""


def gerar_dashboard_html() -> str:
    linhas, stats_grupo = _montar_linhas_recomendacao()
    metadados = _montar_metadados()
    dados_janelas = _montar_dados_janelas_grafico()

    total = len(linhas)
    n_compra = sum(1 for l in linhas if l["recomendacao"] == "Compra")
    n_neutro = sum(1 for l in linhas if l["recomendacao"] == "Neutro")
    n_venda = sum(1 for l in linhas if l["recomendacao"] == "Venda")
    upside_medio = sum(l["upside"] for l in linhas) / total if total else 0.0
    wacc_medio = sum(l["wacc"] for l in linhas) / total if total else 0.0

    datas_atualizacao = [m["atualizado_em"] for m in metadados if m.get("atualizado_em")]
    if datas_atualizacao:
        data_mais_recente = max(datas_atualizacao)
        try:
            data_atualizacao_fmt = datetime.fromisoformat(data_mais_recente).strftime("%d/%m/%Y")
        except ValueError:
            data_atualizacao_fmt = data_mais_recente
    else:
        data_atualizacao_fmt = "—"

    html = _TEMPLATE
    html = html.replace("__DATA_ATUALIZACAO__", data_atualizacao_fmt)
    html = html.replace("__KPI_TOTAL__", str(total))
    html = html.replace("__KPI_COMPRA__", str(n_compra))
    html = html.replace("__KPI_NEUTRO__", str(n_neutro))
    html = html.replace("__KPI_VENDA__", str(n_venda))
    html = html.replace("__KPI_UPSIDE_MEDIO__", f"{upside_medio:+.1%}".replace(".", ","))
    html = html.replace("__KPI_UPSIDE_COR__", "green" if upside_medio >= 0 else "red")
    html = html.replace("__KPI_WACC_MEDIO__", f"{wacc_medio:.2%}".replace(".", ","))
    html = html.replace("__THRESHOLD_COMPRA__", f"{config.THRESHOLD_COMPRA:.0%}")
    html = html.replace("__THRESHOLD_VENDA__", f"{config.THRESHOLD_VENDA:.0%}")
    html = html.replace("__TIMESTAMP_GERACAO__", datetime.now().strftime("%d/%m/%Y %H:%M"))
    html = html.replace("__DADOS_JSON__", json.dumps(linhas, ensure_ascii=False))
    html = html.replace("__STATS_GRUPO_JSON__", json.dumps(stats_grupo, ensure_ascii=False))
    html = html.replace("__JANELAS_JSON__", json.dumps(dados_janelas, ensure_ascii=False))
    html = html.replace(
        "__TICKERS_JSON__",
        json.dumps(list(config.TICKERS) + [config.TICKER_BENCHMARK], ensure_ascii=False),
    )
    html = html.replace("__DIV_ID_GRAFICO__", returns_chart.DIV_ID_GRAFICO)
    html = html.replace("__GRAFICO_HTML__", _gerar_html_grafico())
    return html


def gerar_e_salvar(caminho: str = None) -> str:
    caminho = caminho or CAMINHO_SAIDA
    html = gerar_dashboard_html()
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return caminho


if __name__ == "__main__":
    destino = gerar_e_salvar()
    print(f"Dashboard salvo em: {destino}")
