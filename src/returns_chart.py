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

Decisão de design (validada com o usuário em 03/07/2026): cada aba
RENORMALIZA para base 100 no primeiro dia da PRÓPRIA janela (não um recorte
de uma escala fixa de 36 meses) — é o padrão usado por Yahoo Finance,
Google Finance e TradingView em gráficos de comparação. Isso significa que
"YTD" sempre começa em 100 no primeiro dia do ano, "12M" sempre começa em
100 há 12 meses, etc. As 4 séries (uma por janela) são pré-calculadas em
memória e os botões apenas trocam qual conjunto de dados fica visível
(Plotly `update`, trocando x/y das linhas) — nenhuma chamada nova de API
acontece ao trocar de aba, a troca continua instantânea.
"""

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from . import config


def carregar_precos_do_banco(tickers: list = None, incluir_benchmark: bool = True) -> pd.DataFrame:
    """
    Lê o histórico de preços (Close) de todos os tickers direto do SQLite —
    já foi baixado pelo data_fetch.py, então não faz nenhuma chamada nova
    de API. Retorna um DataFrame largo: índice = data, colunas = ticker.

    `incluir_benchmark`: acrescenta config.TICKER_BENCHMARK (S&P 500) como
    última coluna, pra virar uma linha extra de referência no gráfico (ver
    construir_grafico_comparativo). Se o benchmark ainda não foi buscado
    (data_fetch.baixar_benchmark() nunca rodou), a coluna volta vazia e é
    ignorada silenciosamente — não quebra o gráfico das 6 ações.
    """
    if tickers is None:
        tickers = list(config.TICKERS)
    else:
        tickers = list(tickers)

    if incluir_benchmark and config.TICKER_BENCHMARK not in tickers:
        tickers = tickers + [config.TICKER_BENCHMARK]

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
    """Normaliza cada série para base 100 no primeiro dia disponível DESSE recorte."""
    return precos / precos.iloc[0] * 100


def calcular_retorno_percentual(precos: pd.DataFrame) -> pd.DataFrame:
    """
    Retorno acumulado em %, partindo de 0% no primeiro dia do recorte
    (equivalente a base_100 - 100, só que já no formato que o usuário quer
    ver no gráfico: +14,1% em vez de 114,1).
    """
    return (precos / precos.iloc[0] - 1) * 100


def formatar_retorno_br(valor: float) -> str:
    """
    Formata um retorno percentual como string pronta: 2 casas decimais,
    vírgula como separador decimal, sinal explícito (ex: "+48,44%").

    Por quê formatar aqui em vez de deixar o Plotly formatar via
    hovertemplate/hoverformat? Testamos e, no modo hovermode="x unified",
    o Plotly ignora a formatação numérica do hovertemplate (%{y:+.2f}) E o
    hoverformat do eixo, mostrando o float bruto sem arredondar. Gerando a
    string já pronta e usando %{text} no hovertemplate, a formatação nunca
    depende do Plotly — funciona igual em qualquer modo de hover.
    """
    return f"{valor:+.2f}%".replace(".", ",")


def _janelas_de_data(precos: pd.DataFrame) -> dict:
    """Calcula a data de início de cada janela (YTD/12M/24M/36M), limitada ao histórico disponível."""
    data_maxima = precos.index.max()
    data_minima = precos.index.min()
    inicio_ano_atual = pd.Timestamp(year=data_maxima.year, month=1, day=1)

    brutas = {
        "YTD": inicio_ano_atual,
        "12M": data_maxima - pd.DateOffset(months=12),
        "24M": data_maxima - pd.DateOffset(months=24),
        "36M": data_minima,
    }
    return {label: max(data_inicio, data_minima) for label, data_inicio in brutas.items()}


JANELA_INICIAL = "36M"

# Paleta refinada para as 6 linhas do gráfico — reaproveitada também para os
# "dots" coloridos de cada ticker na tabela de recomendações do dashboard
# (returns_chart.CORES), pra manter a mesma linguagem visual nos dois
# lugares. Trocamos da paleta "qualitativa" padrão do Plotly (tons meio
# datados de tab10/matplotlib) por uma paleta mais alinhada ao visual do
# dashboard.html (ver dashboard_export.py).
CORES = {
    "AAPL": "#2E6FE0",   # azul (cor de destaque do dashboard)
    "MSFT": "#12B76A",   # verde
    "AMZN": "#F79009",   # laranja
    "NVDA": "#7A5AF8",   # violeta
    "GOOGL": "#D6409F",  # magenta
    "TSM": "#667085",    # slate
    config.TICKER_BENCHMARK: "#111827",  # quase preto — neutro, não compete com as 6 cores acima
}

# Nome de exibição por ticker (legenda/tooltip) — só o benchmark precisa de
# tradução (^GSPC -> "S&P 500"); os outros usam o próprio ticker.
NOMES_EXIBICAO = {config.TICKER_BENCHMARK: config.NOME_BENCHMARK}


def nome_exibicao(ticker: str) -> str:
    return NOMES_EXIBICAO.get(ticker, ticker)


def calcular_dados_por_janela(precos: pd.DataFrame) -> dict:
    """
    Pré-calcula, para cada janela (YTD/12M/24M/36M) e cada ticker, a série
    de retorno % já formatada (x = datas, y = valores, text = string
    pronta em pt-BR) — estrutura compartilhada tanto pelos botões nativos
    do Plotly (construir_grafico_comparativo) quanto pelos botões HTML
    customizados usados no dashboard.html (ver dashboard_export.py), que
    chamam `Plotly.update` diretamente em JS com esses dados.
    """
    janelas = _janelas_de_data(precos)
    tickers = list(precos.columns)

    dados_por_janela = {}
    for label, data_inicio in janelas.items():
        recorte = precos.loc[data_inicio:]
        retorno = calcular_retorno_percentual(recorte)
        dados_por_janela[label] = {}
        for ticker in tickers:
            serie = retorno[ticker].dropna()
            dados_por_janela[label][ticker] = {
                "x": [d.strftime("%Y-%m-%d") for d in serie.index],
                "y": [round(float(v), 4) for v in serie.values],
                "text": [formatar_retorno_br(v) for v in serie.values],
            }
    return dados_por_janela


def construir_grafico_comparativo(precos: pd.DataFrame, modo_standalone: bool = True) -> go.Figure:
    """
    Monta o gráfico comparativo de retorno. Cada janela (YTD/12M/24M/36M) é
    RENORMALIZADA para base 100 no seu próprio primeiro dia (padrão de
    mercado — Yahoo/Google Finance) e pré-calculada em memória — a troca de
    janela nunca recalcula nada nem chama API de novo.

    `modo_standalone`: True (padrão) monta o gráfico "completo" — com
    título, rótulos de eixo e os botões nativos do Plotly — usado quando o
    gráfico é aberto sozinho (grafico_comparativo.html, ver
    salvar_grafico_html). No dashboard.html usamos `modo_standalone=False`:
    sem título/rótulos (o card já tem título) e SEM os botões nativos do
    Plotly (que têm um visual "engessado", tipo formulário, difícil de
    restilizar via CSS porque são desenhados como SVG) — no lugar, o
    dashboard usa botões HTML customizados no mesmo estilo do resto do
    site, que chamam Plotly.update() diretamente com os dados de
    calcular_dados_por_janela().

    `precos`: DataFrame de preços BRUTOS (não normalizados), uma coluna por
    ticker — a normalização é feita aqui, uma vez por janela.
    """
    tickers = list(precos.columns)
    dados_por_janela = calcular_dados_por_janela(precos)

    fig = go.Figure()
    for ticker in tickers:
        serie = dados_por_janela[JANELA_INICIAL][ticker]
        eh_benchmark = ticker == config.TICKER_BENCHMARK
        # Benchmark fica visualmente "atrás" das 6 ações: linha mais fina,
        # tracejada e num tom neutro — é referência, não é uma das ações
        # que estamos analisando, não deveria competir visualmente com elas.
        fig.add_trace(go.Scatter(
            x=serie["x"],
            y=serie["y"],
            mode="lines",
            name=nome_exibicao(ticker),
            line=dict(
                color=CORES.get(ticker),
                width=1.5 if eh_benchmark else 2.25,
                dash="dot" if eh_benchmark else "solid",
            ),
            text=serie["text"],
            hovertemplate=f"<b>{nome_exibicao(ticker)}</b><br>%{{x|%d/%m/%Y}}<br>Retorno: %{{text}}<extra></extra>",
        ))

    layout = dict(
        # separators=",." -> primeiro caractere é o separador decimal, o
        # segundo o de milhar. Padrão brasileiro: "14,10" em vez de "14.10".
        # Isso afeta os ticks do eixo E o hovertemplate (ambos usam d3-format).
        separators=",.",
        # Fundo transparente: no dashboard.html o gráfico fica dentro de um
        # card branco (var(--card)) — deixando paper/plot transparentes ele
        # se funde no card em vez de desenhar seu próprio retângulo branco
        # por cima (o que ficava com uma "borda" visível e um ar mais
        # "engessado", de formulário, separado do resto do layout).
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, -apple-system, BlinkMacSystemFont, sans-serif", size=12.5, color="#475467"),
        # hoverformat é necessário além do tickformat: com hovermode="x
        # unified", o Plotly usa o hoverformat do eixo (não o hovertemplate
        # de cada linha) para formatar o valor mostrado no tooltip unificado.
        yaxis=dict(
            ticksuffix="%", tickformat=".2f", hoverformat=".2f",
            gridcolor="#EEF1F6", gridwidth=1, zeroline=True,
            zerolinecolor="#DDE2EA", zerolinewidth=1,
            tickfont=dict(color="#98A2B3", size=11.5),
            showline=False,
        ),
        xaxis=dict(
            showgrid=False, showline=True, linecolor="#E5E9F0",
            tickfont=dict(color="#98A2B3", size=11.5),
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikethickness=1, spikedash="dot", spikecolor="#98A2B3",
        ),
        hovermode="x unified",
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=12, color="#475467"), bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=48, r=16, t=16, b=36),
    )

    if modo_standalone:
        layout["title"] = dict(
            text="Retorno comparativo — AAPL, MSFT, AMZN, NVDA, GOOGL, TSM",
            font=dict(size=15),
        )
        layout["xaxis"]["title"] = "Data"
        layout["yaxis"]["title"] = "Retorno acumulado no período selecionado (%)"
        layout["margin"] = dict(l=60, r=20, t=60, b=50)
        layout["template"] = "plotly_white"

        botoes = []
        for label, por_ticker in dados_por_janela.items():
            xs = [por_ticker[ticker]["x"] for ticker in tickers]
            ys = [por_ticker[ticker]["y"] for ticker in tickers]
            textos = [por_ticker[ticker]["text"] for ticker in tickers]
            botoes.append(dict(label=label, method="update", args=[{"x": xs, "y": ys, "text": textos}]))
        layout["updatemenus"] = [dict(
            type="buttons", direction="right", buttons=botoes,
            x=0, y=1.2, xanchor="left", yanchor="top", showactive=True,
            active=list(dados_por_janela.keys()).index(JANELA_INICIAL),
        )]

    fig.update_layout(**layout)
    return fig


def gerar_grafico(tickers: list = None, modo_standalone: bool = True) -> go.Figure:
    """Função de conveniência: carrega os preços brutos e monta o gráfico em uma chamada."""
    precos = carregar_precos_do_banco(tickers)
    return construir_grafico_comparativo(precos, modo_standalone=modo_standalone)


DIV_ID_GRAFICO = "grafico-comparativo-retorno"

# Tentativa anterior (reordenar as posições Y da caixinha nativa do Plotly)
# não funcionou: no modo hovermode="x unified", o Plotly desenha a caixinha
# inteira como UM bloco de texto só (todas as linhas juntas), não uma linha
# por ação com posição independente — não havia o que reordenar.
#
# Solução: escondemos a caixinha nativa via CSS e construímos a nossa
# própria, em HTML/CSS puro, com controle total sobre a ordem. Escutamos
# 'plotly_hover' (que o Plotly dispara com os pontos de todas as linhas
# naquela data, independente do hovermode) e montamos a caixinha já
# ordenada por retorno decrescente. Reaproveitamos o campo `text` de cada
# ponto (já formatado em "+62,61%", ver formatar_retorno_br) — não
# precisamos formatar número nenhum aqui em JS.
_JS_TOOLTIP_CUSTOMIZADO = """
(function() {
    var div = document.getElementById('__DIV_ID__');
    if (!div) return;

    var estilo = document.createElement('style');
    estilo.innerHTML = ""
        + "#__DIV_ID__ .hoverlayer { display: none !important; }"
        + "#tooltip-customizado { position: fixed; z-index: 1000; background: white; "
        + "border: 1px solid #444; border-radius: 4px; padding: 8px 12px; "
        + "font-family: Arial, sans-serif; font-size: 12px; color: #2a3f5f; "
        + "box-shadow: 2px 2px 6px rgba(0,0,0,0.25); pointer-events: none; display: none; }"
        + "#tooltip-customizado .data-header { font-weight: bold; margin-bottom: 4px; }"
        + "#tooltip-customizado .linha-ativo { display: flex; align-items: center; gap: 6px; white-space: nowrap; }"
        + "#tooltip-customizado .marcador { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }"
        + "#tooltip-customizado .nome-ativo { font-weight: bold; min-width: 48px; display: inline-block; }";
    document.head.appendChild(estilo);

    var caixa = document.createElement('div');
    caixa.id = 'tooltip-customizado';
    document.body.appendChild(caixa);

    div.on('plotly_hover', function(evento) {
        if (!evento.points || evento.points.length === 0) return;

        var pontosOrdenados = evento.points.slice().sort(function(a, b) { return b.y - a.y; });

        var dataFormatada = new Date(pontosOrdenados[0].x).toLocaleDateString('pt-BR', {
            day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC'
        });

        var html = '<div class="data-header">' + dataFormatada + '</div>';
        pontosOrdenados.forEach(function(p) {
            var cor = (p.fullData && p.fullData.line && p.fullData.line.color) || '#333';
            var texto = (p.text !== undefined) ? p.text : p.y;
            html += '<div class="linha-ativo">'
                  + '<span class="marcador" style="background:' + cor + '"></span>'
                  + '<span class="nome-ativo">' + p.data.name + '</span>'
                  + '<span>' + texto + '</span>'
                  + '</div>';
        });
        caixa.innerHTML = html;
        caixa.style.display = 'block';

        var mx = evento.event ? evento.event.clientX : 0;
        var my = evento.event ? evento.event.clientY : 0;
        caixa.style.left = Math.min(mx + 16, window.innerWidth - 220) + 'px';
        caixa.style.top = Math.min(my + 16, window.innerHeight - 200) + 'px';
    });

    div.on('plotly_unhover', function() {
        caixa.style.display = 'none';
    });
})();
""".replace("__DIV_ID__", DIV_ID_GRAFICO)


def salvar_grafico_html(fig: go.Figure, caminho: str):
    """
    Salva o gráfico em HTML já com o JS de ordenação do tooltip embutido.
    Usar esta função (em vez de fig.write_html direto) sempre que gerar o
    grafico_comparativo.html, para não perder esse comportamento.
    """
    fig.write_html(caminho, div_id=DIV_ID_GRAFICO, post_script=_JS_TOOLTIP_CUSTOMIZADO)


if __name__ == "__main__":
    fig = gerar_grafico()
    caminho = f"{config.DIR_RAIZ}/grafico_comparativo.html"
    salvar_grafico_html(fig, caminho)
    print(f"Gráfico salvo em: {caminho}")
