"""
Análise de Comparáveis (Comps) - complementa o DCF
=====================================================
Nenhum analista sério confia só em DCF: o padrão de mercado é cruzar o
valuation por fluxo de caixa descontado com múltiplos de empresas
comparáveis (EV/Revenue, EV/EBITDA, P/E). Se os dois métodos apontam na
mesma direção (ex: DCF diz "caro" E a ação negocia no topo do grupo de
múltiplos), é um sinal mais forte do que qualquer um dos dois isoladamente.

Este script lê os MESMOS dados já extraídos e salvos pelo data_fetch.py
(Etapa 2) — não faz nenhuma chamada nova à API — e gera uma planilha Excel
no padrão de comps de mercado: métricas operacionais, múltiplos de
valuation, estatísticas de distribuição (mediana/quartis) e uma seção de
metodologia documentando fontes e definições.

IMPORTANTE sobre comparabilidade: as 6 empresas do projeto NÃO são um peer
group perfeito no sentido tradicional — TSM é uma fabricante de
semicondutores (modelo de negócio de manufatura, margens e intensidade de
capital muito diferentes das outras 5, que são mais parecidas com
plataformas/hyperscalers de software e internet). Usamos o grupo mesmo
assim porque é o escopo do projeto, mas isso é documentado explicitamente
na aba de metodologia — compararademais entre modelos de negócio tão
diferentes é um erro clássico de comps (ver nota na planilha).
"""

import sqlite3

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter

from . import config
from . import dcf

# Paleta de cores (padrão profissional azul/cinza, conforme convenção de comps)
AZUL_ESCURO = "1F4E79"
AZUL_CLARO = "D9E1F2"
CINZA_CLARO = "F2F2F2"
BRANCO = "FFFFFF"

FONTE_TITULO = Font(name="Calibri", size=14, bold=True, color=BRANCO)
FONTE_SECAO = Font(name="Calibri", size=12, bold=True, color=BRANCO)
FONTE_CABECALHO = Font(name="Calibri", size=11, bold=True, color="000000")
FONTE_DADO_INPUT = Font(name="Calibri", size=11, color="1F4E79")   # azul = input bruto
FONTE_DADO_FORMULA = Font(name="Calibri", size=11, color="000000")  # preto = fórmula
FONTE_STATS = Font(name="Calibri", size=11, italic=True)

CENTRO = Alignment(horizontal="center", vertical="center")


def _obter_dados_empresa(conn, ticker: str) -> dict:
    """Busca no banco tudo que a análise de comps precisa para um ticker."""
    receita = dcf.serie_por_periodo(conn, ticker, "financials", "Total Revenue")
    receita_atual = float(receita.iloc[-1])
    receita_anterior = float(receita.iloc[-2]) if len(receita) >= 2 else None

    gross_profit = dcf.valor_mais_recente(conn, ticker, "financials", "Gross Profit")
    ebitda = dcf.valor_mais_recente(conn, ticker, "financials", "EBITDA")
    net_income = dcf.valor_mais_recente(conn, ticker, "financials", "Net Income")
    fcf = dcf.valor_mais_recente(conn, ticker, "cashflow", "Free Cash Flow")

    empresa = dcf.carregar_empresa(conn, ticker)

    # Net Debt: usa a linha direta do balanço quando existe; senão calcula
    # manualmente (Total Debt - Caixa) — a TSM não tem a linha 'Net Debt'
    # pronta no yfinance, e tem posição de CAIXA LÍQUIDA (mais caixa que dívida).
    net_debt = dcf.valor_mais_recente(conn, ticker, "balance_sheet", "Net Debt")
    if net_debt is None:
        total_debt = dcf.valor_mais_recente(conn, ticker, "balance_sheet", "Total Debt", default=0.0)
        caixa = dcf.valor_mais_recente(conn, ticker, "balance_sheet", "Cash And Cash Equivalents", default=0.0)
        net_debt = total_debt - caixa

    return {
        "ticker": ticker,
        "nome": empresa["nome"],
        "receita_atual": receita_atual,
        "receita_anterior": receita_anterior,
        "periodo_atual": str(receita.index[-1].date()),
        "gross_profit": gross_profit,
        "ebitda": ebitda,
        "net_income": net_income,
        "fcf": fcf,
        "beta": empresa["beta"],
        "market_cap": empresa["market_cap"],
        "net_debt": net_debt,
    }


def _secao_titulo(ws, linha, texto, colunas):
    ws.cell(row=linha, column=1, value=texto)
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=colunas)
    celula = ws.cell(row=linha, column=1)
    celula.font = FONTE_SECAO
    celula.fill = PatternFill("solid", fgColor=AZUL_ESCURO)
    celula.alignment = CENTRO
    for col in range(1, colunas + 1):
        ws.cell(row=linha, column=col).fill = PatternFill("solid", fgColor=AZUL_ESCURO)


def _cabecalho_colunas(ws, linha, textos):
    for i, texto in enumerate(textos, start=1):
        c = ws.cell(row=linha, column=i, value=texto)
        c.font = FONTE_CABECALHO
        c.fill = PatternFill("solid", fgColor=AZUL_CLARO)
        c.alignment = CENTRO


def _linha_estatistica(ws, linha, label, col_inicio, col_fim, primeira_linha_dado, ultima_linha_dado, formula_fn):
    ws.cell(row=linha, column=1, value=label).font = FONTE_STATS
    for col in range(col_inicio, col_fim + 1):
        letra = get_column_letter(col)
        faixa = f"{letra}{primeira_linha_dado}:{letra}{ultima_linha_dado}"
        c = ws.cell(row=linha, column=col, value=formula_fn(faixa))
        c.font = FONTE_STATS
        c.fill = PatternFill("solid", fgColor=CINZA_CLARO)
        c.alignment = CENTRO
        c.number_format = "0.0%" if col in (4, 5, 6, 7) else "0.00"


def gerar_comps_analysis(caminho_saida: str = None):
    if caminho_saida is None:
        caminho_saida = f"{config.DIR_RAIZ}/comps_analysis.xlsx"

    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    dados = [_obter_dados_empresa(conn, t) for t in config.TICKERS]
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Comps"

    n_cols_operacional = 8  # Company, Receita, Receita Ant., Growth, GP, GM, EBITDA, EBITDA M, FCF, FCFM, Beta -> ver abaixo
    # (definimos as colunas exatas abaixo; n_cols_operacional é só para merges)
    total_colunas = 11

    # ---- Cabeçalho geral -----------------------------------------------
    ws.cell(row=1, column=1, value="BIG TECH & SEMICONDUTORES — COMPARABLE COMPANY ANALYSIS")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_colunas)
    ws["A1"].font = FONTE_TITULO
    ws["A1"].fill = PatternFill("solid", fgColor=AZUL_ESCURO)
    ws["A1"].alignment = CENTRO

    nomes = " • ".join(f"{d['nome']} ({d['ticker']})" for d in dados)
    ws.cell(row=2, column=1, value=nomes)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_colunas)
    ws["A2"].alignment = CENTRO

    ws.cell(row=3, column=1,
            value="As of 03/07/2026 | Valores em USD (milhões), exceto múltiplos e beta | Fonte: pipeline próprio (data_fetch.py / SQLite)")
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=total_colunas)
    ws["A3"].alignment = CENTRO
    ws["A3"].font = Font(italic=True, size=9)

    # ---- Seção 1: Métricas Operacionais ---------------------------------
    linha_secao1 = 5
    _secao_titulo(ws, linha_secao1, "OPERATING STATISTICS & FINANCIAL METRICS", total_colunas)

    linha_cab1 = linha_secao1 + 1
    _cabecalho_colunas(ws, linha_cab1, [
        "Company", "Revenue (atual)", "Revenue (ano ant.)", "Revenue Growth YoY",
        "Gross Profit", "Gross Margin", "EBITDA", "EBITDA Margin",
        "Free Cash Flow", "FCF Margin", "Beta",
    ])

    primeira_linha_dado_op = linha_cab1 + 1
    for i, d in enumerate(dados):
        linha = primeira_linha_dado_op + i
        ws.cell(row=linha, column=1, value=f"{d['nome']} ({d['ticker']})")

        c_receita = ws.cell(row=linha, column=2, value=round(d["receita_atual"] / 1e6, 1))
        c_receita.font = FONTE_DADO_INPUT
        c_receita.comment = Comment(
            f"Fonte: SQLite valuation.db, tabela linhas_financeiras "
            f"('Total Revenue', período {d['periodo_atual']}). Extraído via yfinance "
            f"em data_fetch.py (03/07/2026).", "Comps Analysis")

        c_receita_ant = ws.cell(row=linha, column=3,
                                 value=round(d["receita_anterior"] / 1e6, 1) if d["receita_anterior"] else None)
        c_receita_ant.font = FONTE_DADO_INPUT
        c_receita_ant.comment = Comment("Receita do período anterior, mesma fonte (para calcular YoY).", "Comps Analysis")

        c_growth = ws.cell(row=linha, column=4, value=f"=(B{linha}-C{linha})/C{linha}")
        c_growth.font = FONTE_DADO_FORMULA
        c_growth.number_format = "0.0%"

        c_gp = ws.cell(row=linha, column=5, value=round(d["gross_profit"] / 1e6, 1))
        c_gp.font = FONTE_DADO_INPUT
        c_gp.comment = Comment("Fonte: linhas_financeiras, item 'Gross Profit'.", "Comps Analysis")

        c_gm = ws.cell(row=linha, column=6, value=f"=E{linha}/B{linha}")
        c_gm.font = FONTE_DADO_FORMULA
        c_gm.number_format = "0.0%"

        c_ebitda = ws.cell(row=linha, column=7, value=round(d["ebitda"] / 1e6, 1))
        c_ebitda.font = FONTE_DADO_INPUT
        c_ebitda.comment = Comment("Fonte: linhas_financeiras, item 'EBITDA' (como reportado pelo yfinance).", "Comps Analysis")

        c_ebitdam = ws.cell(row=linha, column=8, value=f"=G{linha}/B{linha}")
        c_ebitdam.font = FONTE_DADO_FORMULA
        c_ebitdam.number_format = "0.0%"

        c_fcf = ws.cell(row=linha, column=9, value=round(d["fcf"] / 1e6, 1))
        c_fcf.font = FONTE_DADO_INPUT
        c_fcf.comment = Comment(
            "Fonte: linhas_financeiras (cashflow), item 'Free Cash Flow' "
            "(definição yfinance: Fluxo de Caixa Operacional - CapEx).", "Comps Analysis")

        c_fcfm = ws.cell(row=linha, column=10, value=f"=I{linha}/B{linha}")
        c_fcfm.font = FONTE_DADO_FORMULA
        c_fcfm.number_format = "0.0%"

        c_beta = ws.cell(row=linha, column=11, value=round(d["beta"], 3))
        c_beta.font = FONTE_DADO_INPUT
        c_beta.comment = Comment(
            "Fonte: yfinance .info['beta'] (regressão histórica vs. mercado, "
            "sem ajuste de Blume — mesma premissa usada no DCF).", "Comps Analysis")

        for col in range(1, total_colunas + 1):
            ws.cell(row=linha, column=col).alignment = CENTRO

    ultima_linha_dado_op = primeira_linha_dado_op + len(dados) - 1

    # Estatísticas (Growth=4, GM=6, EBITDA M=8, FCFM=10, Beta=11)
    linha_stats_inicio = ultima_linha_dado_op + 2
    stats = [
        ("Maximum", lambda faixa: f"=MAX({faixa})"),
        ("75th Percentile", lambda faixa: f"=QUARTILE({faixa},3)"),
        ("Median", lambda faixa: f"=MEDIAN({faixa})"),
        ("25th Percentile", lambda faixa: f"=QUARTILE({faixa},1)"),
        ("Minimum", lambda faixa: f"=MIN({faixa})"),
    ]
    colunas_com_stats = [4, 6, 8, 10, 11]
    for i, (label, fn) in enumerate(stats):
        linha = linha_stats_inicio + i
        ws.cell(row=linha, column=1, value=label).font = FONTE_STATS
        for col in colunas_com_stats:
            letra = get_column_letter(col)
            faixa = f"{letra}{primeira_linha_dado_op}:{letra}{ultima_linha_dado_op}"
            c = ws.cell(row=linha, column=col, value=fn(faixa))
            c.font = FONTE_STATS
            c.fill = PatternFill("solid", fgColor=CINZA_CLARO)
            c.alignment = CENTRO
            c.number_format = "0.0%" if col != 11 else "0.00"

    # ---- Seção 2: Múltiplos de Valuation --------------------------------
    linha_secao2 = linha_stats_inicio + len(stats) + 2
    _secao_titulo(ws, linha_secao2, "VALUATION MULTIPLES & INVESTMENT METRICS", total_colunas)

    linha_cab2 = linha_secao2 + 1
    _cabecalho_colunas(ws, linha_cab2, [
        "Company", "Market Cap", "Net Debt", "Enterprise Value",
        "EV / Revenue", "EV / EBITDA", "Net Income", "P/E",
    ])

    primeira_linha_dado_val = linha_cab2 + 1
    for i, d in enumerate(dados):
        linha = primeira_linha_dado_val + i
        linha_operacional_correspondente = primeira_linha_dado_op + i

        ws.cell(row=linha, column=1, value=f"{d['nome']} ({d['ticker']})")

        c_mktcap = ws.cell(row=linha, column=2, value=round(d["market_cap"] / 1e6, 1))
        c_mktcap.font = FONTE_DADO_INPUT
        c_mktcap.comment = Comment(
            "Fonte: tabela empresas, campo market_cap (yfinance .info['marketCap'], "
            "já soma todas as classes de ação quando aplicável, ex: GOOGL+GOOG).", "Comps Analysis")

        c_netdebt = ws.cell(row=linha, column=3, value=round(d["net_debt"] / 1e6, 1))
        c_netdebt.font = FONTE_DADO_INPUT
        nota_netdebt = ("Fonte: balance_sheet, item 'Net Debt'." if d["ticker"] != "TSM" else
                         "TSM não tem a linha 'Net Debt' pronta no yfinance — calculado manualmente "
                         "como Total Debt - Caixa (TSM tem posição de caixa líquida, por isso o valor é negativo).")
        c_netdebt.comment = Comment(nota_netdebt, "Comps Analysis")

        c_ev = ws.cell(row=linha, column=4, value=f"=B{linha}+C{linha}")
        c_ev.font = FONTE_DADO_FORMULA
        c_ev.number_format = "#,##0"

        c_ev_rev = ws.cell(row=linha, column=5, value=f"=D{linha}/B{linha_operacional_correspondente}")
        c_ev_rev.font = FONTE_DADO_FORMULA
        c_ev_rev.number_format = '0.0"x"'

        c_ev_ebitda = ws.cell(row=linha, column=6, value=f"=D{linha}/G{linha_operacional_correspondente}")
        c_ev_ebitda.font = FONTE_DADO_FORMULA
        c_ev_ebitda.number_format = '0.0"x"'

        c_ni = ws.cell(row=linha, column=7, value=round(d["net_income"] / 1e6, 1))
        c_ni.font = FONTE_DADO_INPUT
        c_ni.comment = Comment("Fonte: linhas_financeiras, item 'Net Income'.", "Comps Analysis")

        c_pe = ws.cell(row=linha, column=8, value=f"=B{linha}/G{linha}")
        c_pe.font = FONTE_DADO_FORMULA
        c_pe.number_format = '0.0"x"'

        for col in range(1, 9):
            ws.cell(row=linha, column=col).alignment = CENTRO

    ultima_linha_dado_val = primeira_linha_dado_val + len(dados) - 1

    linha_stats2_inicio = ultima_linha_dado_val + 2
    colunas_com_stats2 = [5, 6, 8]  # EV/Revenue, EV/EBITDA, P/E
    for i, (label, fn) in enumerate(stats):
        linha = linha_stats2_inicio + i
        ws.cell(row=linha, column=1, value=label).font = FONTE_STATS
        for col in colunas_com_stats2:
            letra = get_column_letter(col)
            faixa = f"{letra}{primeira_linha_dado_val}:{letra}{ultima_linha_dado_val}"
            c = ws.cell(row=linha, column=col, value=fn(faixa))
            c.font = FONTE_STATS
            c.fill = PatternFill("solid", fgColor=CINZA_CLARO)
            c.alignment = CENTRO
            c.number_format = '0.0"x"'

    # ---- Seção 3: Metodologia -------------------------------------------
    linha_metodologia = linha_stats2_inicio + len(stats) + 2
    _secao_titulo(ws, linha_metodologia, "NOTES & METHODOLOGY", total_colunas)

    notas = [
        "Fonte dos dados: pipeline próprio do projeto (yfinance -> SQLite via src/data_fetch.py), "
        "não usamos web search para os números — todos vêm do banco já validado nas Etapas 1-2.",
        "EBITDA: linha 'EBITDA' como reportada pelo yfinance (não recalculada a partir de Operating Income + D&A).",
        "Free Cash Flow: definição yfinance = Fluxo de Caixa Operacional - CapEx.",
        "Revenue Growth: variação YoY entre os dois períodos anuais mais recentes disponíveis (fiscal year end de cada empresa).",
        "Enterprise Value = Market Cap + Net Debt. TSM não tem a linha 'Net Debt' pronta — calculada como Total Debt - Caixa.",
        "Market Cap da GOOGL já soma as duas classes de ação (Class A + Class C); shares_outstanding do ticker "
        "isoladamente NÃO reflete isso — ver bug documentado na Etapa de comps, corrigido no WACC do dcf.py.",
        "LIMITAÇÃO DE COMPARABILIDADE: TSM é uma fabricante de semicondutores (capital-intensiva, margens e "
        "modelo de negócio de manufatura), bem diferente das outras 5 (plataformas de software/internet/hardware "
        "de consumo). Os múltiplos da TSM devem ser lidos com essa ressalva — comparar diretamente contra o "
        "grupo pode distorcer a leitura de 'caro vs. barato'.",
        "Como usar isso com o DCF: se uma ação tem upside negativo no DCF (Etapa 3) E múltiplos no topo do grupo "
        "aqui, é um sinal mais forte de que está cara. Se os dois métodos discordam, vale investigar as premissas.",
    ]
    for i, nota in enumerate(notas):
        linha = linha_metodologia + 1 + i
        ws.cell(row=linha, column=1, value=f"• {nota}")
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=total_colunas)
        ws.cell(row=linha, column=1).font = Font(size=9)
        ws.cell(row=linha, column=1).alignment = Alignment(wrap_text=True, vertical="top")

    # ---- Formatação de colunas -------------------------------------------
    larguras = [26, 15, 15, 14, 14, 13, 14, 13, 14, 12, 9]
    for i, largura in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largura

    wb.save(caminho_saida)
    print(f"Comps analysis salvo em: {caminho_saida}")
    return caminho_saida


if __name__ == "__main__":
    gerar_comps_analysis()
