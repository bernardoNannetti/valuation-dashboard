"""
Modelo de DCF (Discounted Cash Flow) - Etapa 3
=================================================
Lê os dados já extraídos e salvos no SQLite (Etapa 2) e calcula, para cada
empresa: WACC (via CAPM), projeção de FCFF (Free Cash Flow to Firm) para os
próximos anos, valor terminal (Gordon Growth) e preço-alvo por ação.

Metodologia (validada com o usuário em 03/07/2026, ver README/histórico do
projeto para o racional de cada premissa):
  - Horizonte de projeção explícita: 5 anos (config.HORIZONTE_PROJECAO_ANOS)
  - Crescimento de receita: começa no consenso de analistas (ano 1) e cai
    linearmente ("fade") até a taxa de crescimento na perpetuidade (ano 5)
  - Margem EBIT, % D&A, % CapEx e % variação de capital de giro: médias
    históricas (como % da receita), mantidas constantes na projeção
  - Taxa de imposto: efetiva histórica (Tax Provision / Pretax Income)
  - WACC: CAPM (beta do yfinance, sem ajuste) + custo de dívida real
    (Despesa de Juros / Dívida Total), ponderado por valor de mercado
  - Valor terminal: Gordon Growth Model com g = 2,5% a.a.

FCFF = EBIT × (1 - taxa de imposto) + D&A - CapEx - Δ Capital de Giro
     (aqui usamos NOPAT = EBIT × (1 - taxa) como ponto de partida padrão)
"""

import sqlite3

import pandas as pd
import yfinance as yf

from . import config


# ---------------------------------------------------------------------------
# Camada de leitura do banco (lê o que data_fetch.py já salvou)
# ---------------------------------------------------------------------------

def serie_por_periodo(conn, ticker: str, demonstrativo: str, item: str) -> pd.Series:
    """Retorna uma Series (índice = data do período, ordenada) para um item contábil."""
    cur = conn.execute("""
        SELECT periodo, valor FROM linhas_financeiras
        WHERE ticker = ? AND demonstrativo = ? AND item = ?
        ORDER BY periodo
    """, (ticker, demonstrativo, item))
    dados = cur.fetchall()
    if not dados:
        return pd.Series(dtype=float)
    periodos, valores = zip(*dados)
    return pd.Series(valores, index=pd.to_datetime(periodos))


def valor_mais_recente(conn, ticker: str, demonstrativo: str, item: str, default=None):
    serie = serie_por_periodo(conn, ticker, demonstrativo, item)
    return float(serie.iloc[-1]) if not serie.empty else default


def periodo_mais_recente(conn, ticker: str, demonstrativo: str, item: str, default=None):
    """
    Data do período (fim de exercício fiscal) do valor mais recente de um
    item contábil — ex: '2025-09-30' para a receita da AAPL. Usado para
    deixar explícito, no Excel e no dashboard, de QUAL demonstração
    financeira (10-K/10-Q) os inputs do DCF vieram — importante pra
    auditoria: cada empresa tem um fim de ano fiscal diferente (AAPL
    fecha em setembro, MSFT em junho, NVDA em janeiro), então "o dado mais
    recente" não é a mesma data-calendário pra todas.
    """
    serie = serie_por_periodo(conn, ticker, demonstrativo, item)
    return str(serie.index[-1].date()) if not serie.empty else default


def carregar_empresa(conn, ticker: str) -> dict:
    cur = conn.execute("SELECT * FROM empresas WHERE ticker = ?", (ticker,))
    colunas = [d[0] for d in cur.description]
    linha = cur.fetchone()
    if linha is None:
        raise ValueError(f"Empresa {ticker} não encontrada no banco. Rode data_fetch.py primeiro.")
    return dict(zip(colunas, linha))


def preco_atual(conn, ticker: str) -> float:
    """Usa o último preço de fechamento salvo no banco (Etapa 2)."""
    cur = conn.execute("""
        SELECT close FROM precos_historicos WHERE ticker = ? ORDER BY data DESC LIMIT 1
    """, (ticker,))
    linha = cur.fetchone()
    if linha is None:
        raise ValueError(f"Sem histórico de preços para {ticker}. Rode data_fetch.py primeiro.")
    return float(linha[0])


def data_preco_atual(conn, ticker: str) -> str:
    """
    Data do último preço de fechamento salvo (não confundir com
    `empresas.atualizado_em`, que é quando os FUNDAMENTOS — não o preço —
    foram buscados pela última vez; preço é atualizado numa cadência
    diferente/mais frequente, ver data_fetch.buscar_todas_as_empresas).
    """
    cur = conn.execute("""
        SELECT data FROM precos_historicos WHERE ticker = ? ORDER BY data DESC LIMIT 1
    """, (ticker,))
    linha = cur.fetchone()
    return linha[0] if linha else None


# ---------------------------------------------------------------------------
# WACC
# ---------------------------------------------------------------------------

def taxa_livre_de_risco() -> dict:
    """
    Busca o yield atual do Treasury 10Y (ticker ^TNX) ao vivo.
    O yfinance reporta o Close do ^TNX diretamente em pontos percentuais de
    yield (ex: Close 4.372 ⇒ yield de 4,372%), então dividimos por 100 para
    chegar à taxa em fração decimal (0,04372).

    BUG CORRIGIDO: a versão anterior dividia por 1000, presumindo que o
    yfinance reportava o índice como yield% × 10 (ex: "44.90" para 4,49%).
    Essa premissa nunca foi checada contra dado real — o valor bruto atual
    é 4.372, não 43.72 — e vinha subestimando a taxa livre de risco em 10x
    (0,44% em vez de ~4,4%) desde que o modelo de DCF foi criado. Isso
    derrubava o WACC inteiro em ~4 p.p., inflando artificialmente todo
    preço-alvo calculado até agora (WACC menor = valor presente maior).

    Se não houver conexão com a internet (ex: ambiente sandboxed sem acesso
    a APIs financeiras), cai para o valor de referência salvo em config.

    Retorna um dict (não só o número) com `fonte` ("ao_vivo" | "fallback") e
    `capturado_em` (data do próprio pregão do Treasury, quando ao vivo) —
    sem isso, não tinha como o Excel/dashboard mostrarem se o WACC exibido
    usou o yield de verdade daquele dia ou a constante fixa de config.py
    (que fica desatualizada com o tempo). Ver valuation_export.py e
    dashboard_export.py.
    """
    try:
        historico = yf.Ticker(config.TICKER_TAXA_LIVRE_DE_RISCO).history(period="5d")
        if historico.empty:
            raise ValueError("histórico vazio")
        return {
            "valor": float(historico["Close"].iloc[-1]) / 100,
            "fonte": "ao_vivo",
            "capturado_em": str(historico.index[-1].date()),
        }
    except Exception as erro:
        print(f"[aviso] Não foi possível buscar Treasury 10Y ao vivo ({erro}). "
              f"Usando fallback: {config.TAXA_LIVRE_DE_RISCO_FALLBACK:.2%}")
        return {
            "valor": config.TAXA_LIVRE_DE_RISCO_FALLBACK,
            "fonte": "fallback",
            "capturado_em": None,
        }


def taxa_imposto_efetiva(conn, ticker: str) -> float:
    """
    Taxa efetiva de imposto = Tax Provision / Pretax Income, média dos
    últimos config.PERIODOS_MEDIA_HISTORICA anos. Limitada entre 0% e 40%
    para evitar distorções de itens não recorrentes (créditos fiscais
    pontuais, repatriação, etc.). Fallback: 21% (alíquota federal
    corporativa americana).
    """
    tax_provision = serie_por_periodo(conn, ticker, "financials", "Tax Provision")
    pretax_income = serie_por_periodo(conn, ticker, "financials", "Pretax Income")
    if tax_provision.empty or pretax_income.empty:
        return 0.21

    taxas = (tax_provision / pretax_income).dropna()
    taxas = taxas.tail(config.PERIODOS_MEDIA_HISTORICA)
    taxas_validas = taxas[(taxas >= 0) & (taxas <= 0.40)]
    return float(taxas_validas.mean()) if not taxas_validas.empty else 0.21


def calcular_wacc(conn, ticker: str) -> dict:
    """
    WACC = peso_equity × custo_capital_próprio + peso_dívida × custo_dívida_pós_imposto

    custo_capital_próprio (CAPM) = Rf + beta × ERP
    custo_dívida_pré_imposto = Despesa de Juros ÷ Dívida Total (taxa efetiva
        real da empresa — mais apropriado que rating sintético para estas
        6 large caps, que têm dívida líquida real e cotada).
    """
    empresa = carregar_empresa(conn, ticker)
    beta = empresa["beta"] or 1.0

    rf_info = taxa_livre_de_risco()
    rf = rf_info["valor"]
    custo_capital_proprio = rf + beta * config.PREMIO_RISCO_MERCADO

    divida_total = valor_mais_recente(conn, ticker, "balance_sheet", "Total Debt", default=0.0) or 0.0
    despesa_juros = abs(valor_mais_recente(conn, ticker, "financials", "Interest Expense", default=0.0) or 0.0)
    custo_divida_pre_imposto = (despesa_juros / divida_total) if divida_total else 0.0

    taxa_imposto = taxa_imposto_efetiva(conn, ticker)
    custo_divida_pos_imposto = custo_divida_pre_imposto * (1 - taxa_imposto)

    # Valor de mercado do equity: escala o último market_cap conhecido pela
    # variação de preço desde o cadastro, em vez de recalcular via preço ×
    # ações em circulação. Descoberto testando o comps-analysis: para
    # empresas com múltiplas classes de ação (ex: GOOGL/GOOG da Alphabet),
    # `shares_outstanding` do ticker só conta UMA classe, então preço×ações
    # subestimava o market cap da GOOGL pela metade. Escalar o market_cap já
    # correto (que o yfinance calcula somando todas as classes) pela razão
    # de preço evita esse problema e ainda mantém o peso reagindo ao preço
    # do dia entre uma atualização de fundamentos e outra.
    preco_hoje = preco_atual(conn, ticker)
    if empresa.get("preco_no_cadastro"):
        valor_equity = empresa["market_cap"] * (preco_hoje / empresa["preco_no_cadastro"])
    else:
        valor_equity = empresa["market_cap"]
    valor_total = valor_equity + divida_total
    peso_equity = valor_equity / valor_total
    peso_divida = divida_total / valor_total

    wacc = peso_equity * custo_capital_proprio + peso_divida * custo_divida_pos_imposto

    return {
        "beta": beta,
        "taxa_livre_de_risco": rf,
        "taxa_livre_de_risco_fonte": rf_info["fonte"],
        "taxa_livre_de_risco_capturado_em": rf_info["capturado_em"],
        "premio_risco_mercado": config.PREMIO_RISCO_MERCADO,
        "custo_capital_proprio": custo_capital_proprio,
        "divida_total": divida_total,
        "despesa_juros": despesa_juros,
        "custo_divida_pre_imposto": custo_divida_pre_imposto,
        "taxa_imposto_efetiva": taxa_imposto,
        "custo_divida_pos_imposto": custo_divida_pos_imposto,
        "valor_mercado_equity": valor_equity,
        "peso_equity": peso_equity,
        "peso_divida": peso_divida,
        "wacc": wacc,
    }


# ---------------------------------------------------------------------------
# Projeção de fluxo de caixa
# ---------------------------------------------------------------------------

def margem_ebit_historica(conn, ticker: str) -> float:
    """
    Margem EBIT média (EBIT ÷ Receita Total) dos últimos
    config.PERIODOS_MEDIA_HISTORICA anos.

    Por que só os últimos N anos, e não todo o histórico disponível?
    Testamos com todo o histórico (4-5 anos) e a média saiu distorcida para
    empresas com margem em transição rápida — ex: AMZN tinha margem EBIT de
    -0,7% em 2022 e 13,9% em 2025 (recuperação pós-pandemia + AWS crescendo
    como % do mix). Uma média de 4 anos "puxava" a margem projetada para
    baixo demais, gerando FCFF negativo em todos os anos futuros. Usar uma
    janela mais curta captura melhor a rentabilidade ATUAL da empresa.
    """
    ebit = serie_por_periodo(conn, ticker, "financials", "EBIT")
    receita = serie_por_periodo(conn, ticker, "financials", "Total Revenue")
    margens = (ebit / receita).dropna().tail(config.PERIODOS_MEDIA_HISTORICA)
    if margens.empty:
        raise ValueError(f"Não foi possível calcular margem EBIT para {ticker}.")
    return float(margens.mean())


def percentual_medio_da_receita(conn, ticker: str, demonstrativo: str, item: str) -> float:
    """
    Média de item ÷ Receita Total (ex: D&A%, CapEx%, ΔWC%) dos últimos
    config.PERIODOS_MEDIA_HISTORICA anos. Usada para projetar essas linhas
    como % constante da receita nos anos futuros — premissa simplificadora
    comum em modelos de DCF de prova de conceito (uma evolução natural
    seria projetar cada uma separadamente, com sua própria tendência).
    """
    valores = serie_por_periodo(conn, ticker, demonstrativo, item)
    receita = serie_por_periodo(conn, ticker, "financials", "Total Revenue")
    razao = (valores / receita).dropna().tail(config.PERIODOS_MEDIA_HISTORICA)
    return float(razao.mean()) if not razao.empty else 0.0


def projetar_percentual_com_fade(percentual_ano1: float, percentual_final: float, anos: int,
                                   anos_fade: int = None) -> list:
    """
    Interpola linearmente um percentual (ex: CapEx % da receita) do valor do
    ano 1 até o valor final, completando a transição em `anos_fade` anos
    (não necessariamente o horizonte inteiro) — os anos restantes ficam
    constantes em `percentual_final`.

    Por quê um fade CURTO (não ao longo de todo o horizonte)? Testamos fazer
    o fade ao longo dos 5-10 anos inteiros e piorou o resultado da AMZN: como
    a interpolação é linear, esticar o horizonte só mantém o capex elevado
    por mais tempo antes de normalizar. Guidance pública de capex só é
    confiável para ~1-2 anos à frente mesmo — não temos base real para supor
    uma trajetória de 5-10 anos, então é mais honesto assumir uma
    normalização rápida (config.ANOS_FADE_CAPEX) e manter a média histórica
    depois disso, em vez de inventar um "meio-termo" sem fundamento.
    """
    if anos_fade is None:
        anos_fade = anos
    anos_fade = max(1, min(anos_fade, anos))

    valores = []
    for ano in range(anos):
        if ano >= anos_fade - 1:
            valores.append(percentual_final)
        else:
            valores.append(
                percentual_ano1 + (percentual_final - percentual_ano1) * ano / (anos_fade - 1)
            )
    return valores


def pct_capex_ano1(conn, ticker: str, pct_capex_historico: float) -> float:
    """
    CapEx % da receita para o ano 1 da projeção. Usa a guidance pública de
    capex (config.CAPEX_GUIDANCE_ANO1_USD) quando disponível, convertida
    para % da receita mais recente; senão, cai para a média histórica
    (ex: NVDA, que não guia capex da mesma forma que os hyperscalers).

    O percentual implícito na guidance é limitado a
    config.CAPEX_GUIDANCE_CAP_MULTIPLO × o CapEx% histórico (ver comentário
    em config.py): sem esse teto, guidances desproporcionais em relação à
    receita do último ano fechado (ex: MSFT implicava -67,4% da receita)
    geravam um FCFF ano 1 tão negativo que dominava o valuation inteiro,
    inclusive tornando o preço-alvo da AMZN negativo.
    """
    guidance_usd = config.CAPEX_GUIDANCE_ANO1_USD.get(ticker)
    if guidance_usd is None:
        return pct_capex_historico

    receita_base = valor_mais_recente(conn, ticker, "financials", "Total Revenue")
    if not receita_base:
        return pct_capex_historico

    pct_guidance = -(guidance_usd / receita_base)  # negativo = saída de caixa, mesma convenção do yfinance
    limite = config.CAPEX_GUIDANCE_CAP_MULTIPLO * pct_capex_historico  # ambos negativos
    return max(pct_guidance, limite)  # max entre negativos = o de menor magnitude


def projetar_receita(receita_base: float, crescimento_ano1: float, anos: int, g_terminal: float) -> list:
    """
    Projeta a receita para `anos` anos à frente, com a taxa de crescimento
    caindo linearmente de `crescimento_ano1` (ano 1) até `g_terminal` (último
    ano do horizonte) — o "fade" para evitar saltos irreais de crescimento
    para a perpetuidade (crítico para NVDA/TSM, que crescem muito rápido hoje).
    """
    receitas = []
    receita_atual = receita_base
    for ano in range(1, anos + 1):
        if anos == 1:
            taxa = crescimento_ano1
        else:
            taxa = crescimento_ano1 + (g_terminal - crescimento_ano1) * (ano - 1) / (anos - 1)
        receita_atual = receita_atual * (1 + taxa)
        receitas.append(receita_atual)
    return receitas


def calcular_dcf(ticker: str, conn=None) -> dict:
    """
    Roda o DCF completo para um ticker. Devolve um dict com todas as
    premissas usadas (para transparência/auditoria no Excel exportado),
    os fluxos de caixa projetados, o preço-alvo e a recomendação.
    """
    fechar_conexao = False
    if conn is None:
        conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
        fechar_conexao = True

    try:
        wacc_info = calcular_wacc(conn, ticker)
        wacc = wacc_info["wacc"]

        # Horizonte de projeção: 10 anos para empresas com choque de capex de
        # IA muito acima do histórico (AMZN/MSFT/GOOGL, ver
        # config.HORIZONTE_PROJECAO_POR_TICKER), 5 anos para as demais.
        horizonte = config.HORIZONTE_PROJECAO_POR_TICKER.get(ticker, config.HORIZONTE_PROJECAO_ANOS)

        receita_base = valor_mais_recente(conn, ticker, "financials", "Total Revenue")
        # Data do período fiscal (10-K/10-Q) de onde a receita-base veio —
        # cada empresa fecha o ano fiscal numa data diferente (AAPL: set,
        # MSFT: jun, NVDA: jan), então isso NÃO é a mesma data-calendário
        # pra todas. Exposto no Excel/dashboard pra deixar claro "a partir
        # de qual documento" o DCF está calculado (ver valuation_export.py).
        receita_base_periodo = periodo_mais_recente(conn, ticker, "financials", "Total Revenue")
        margem_ebit = margem_ebit_historica(conn, ticker)
        pct_da = percentual_medio_da_receita(conn, ticker, "cashflow", "Depreciation Amortization Depletion")
        pct_capex_hist = percentual_medio_da_receita(conn, ticker, "cashflow", "Capital Expenditure")  # já negativo
        pct_wc = percentual_medio_da_receita(conn, ticker, "cashflow", "Change In Working Capital")
        taxa_imposto = wacc_info["taxa_imposto_efetiva"]

        crescimento_ano1 = config.CRESCIMENTO_CONSENSO_ANO1.get(ticker, config.CRESCIMENTO_PERPETUIDADE)
        receitas_projetadas = projetar_receita(
            receita_base, crescimento_ano1, horizonte, config.CRESCIMENTO_PERPETUIDADE
        )

        # CapEx: parte da guidance pública de investimento (ano 1) e faz fade
        # até a média histórica (ver projetar_percentual_com_fade) — reflete
        # o pico atual de investimento em IA nas 5 empresas com guidance
        # divulgada (AAPL, MSFT, AMZN, GOOGL, TSM); NVDA usa média histórica
        # nos dois pontos (sem guidance específica = sem fade).
        pct_capex_inicial = pct_capex_ano1(conn, ticker, pct_capex_hist)
        pcts_capex_projetados = projetar_percentual_com_fade(
            pct_capex_inicial, pct_capex_hist, horizonte, anos_fade=config.ANOS_FADE_CAPEX
        )

        fcffs = []
        for receita, pct_capex_ano in zip(receitas_projetadas, pcts_capex_projetados):
            ebit = receita * margem_ebit
            nopat = ebit * (1 - taxa_imposto)
            da = receita * pct_da
            capex = receita * pct_capex_ano  # já negativo (saída de caixa)
            variacao_wc = receita * pct_wc   # já no sinal de impacto de caixa (yfinance)
            fcff = nopat + da + capex + variacao_wc
            fcffs.append(fcff)

        valores_presentes_fcff = [
            fcff / (1 + wacc) ** (ano + 1) for ano, fcff in enumerate(fcffs)
        ]

        # Valor terminal (Gordon Growth) a partir do último FCFF projetado
        fcff_terminal = fcffs[-1] * (1 + config.CRESCIMENTO_PERPETUIDADE)
        valor_terminal = fcff_terminal / (wacc - config.CRESCIMENTO_PERPETUIDADE)
        valor_presente_terminal = valor_terminal / (1 + wacc) ** horizonte

        valor_empresa = sum(valores_presentes_fcff) + valor_presente_terminal

        empresa = carregar_empresa(conn, ticker)
        divida_total = wacc_info["divida_total"]
        # 'Net Debt' já vem calculado no balanço (Total Debt - Caixa); usamos
        # como proxy de dívida líquida, com fallback para dívida total bruta.
        divida_liquida = valor_mais_recente(conn, ticker, "balance_sheet", "Net Debt", default=divida_total)

        valor_equity = valor_empresa - divida_liquida
        preco_alvo = valor_equity / empresa["shares_outstanding"]

        preco_atual_acao = preco_atual(conn, ticker)
        preco_atual_data = data_preco_atual(conn, ticker)
        upside = (preco_alvo / preco_atual_acao) - 1

        if upside > config.THRESHOLD_COMPRA:
            recomendacao = "Compra"
        elif upside < config.THRESHOLD_VENDA:
            recomendacao = "Venda"
        else:
            recomendacao = "Neutro"

        return {
            "ticker": ticker,
            "nome": empresa["nome"],
            "setor": empresa["setor"],
            "industria": empresa["industria"],
            "wacc_detalhe": wacc_info,
            "margem_ebit": margem_ebit,
            "pct_da": pct_da,
            "pct_capex_inicial": pct_capex_inicial,
            "pct_capex_historico": pct_capex_hist,
            "pcts_capex_projetados": pcts_capex_projetados,
            "pct_variacao_wc": pct_wc,
            "taxa_imposto_efetiva": taxa_imposto,
            "crescimento_ano1": crescimento_ano1,
            "crescimento_perpetuidade": config.CRESCIMENTO_PERPETUIDADE,
            "horizonte_projecao_anos": horizonte,
            "receita_base": receita_base,
            "receita_base_periodo": receita_base_periodo,
            "dados_atualizados_em": empresa.get("atualizado_em"),
            "receitas_projetadas": receitas_projetadas,
            "fcffs_projetados": fcffs,
            "valores_presentes_fcff": valores_presentes_fcff,
            "valor_terminal": valor_terminal,
            "valor_presente_terminal": valor_presente_terminal,
            "valor_empresa": valor_empresa,
            "divida_liquida": divida_liquida,
            "valor_equity": valor_equity,
            "shares_outstanding": empresa["shares_outstanding"],
            "preco_alvo": preco_alvo,
            "preco_atual": preco_atual_acao,
            "preco_atual_data": preco_atual_data,
            "upside": upside,
            "recomendacao": recomendacao,
        }
    finally:
        if fechar_conexao:
            conn.close()


if __name__ == "__main__":
    print(f"{'Ticker':<7}{'Preço atual':>14}{'Preço-alvo':>14}{'Upside':>10}{'Recom.':>10}{'WACC':>8}")
    for ticker in config.TICKERS:
        r = calcular_dcf(ticker)
        print(f"{r['ticker']:<7}{r['preco_atual']:>14.2f}{r['preco_alvo']:>14.2f}"
              f"{r['upside']:>10.1%}{r['recomendacao']:>10}{r['wacc_detalhe']['wacc']:>8.2%}")
