"""
Camada de extração de dados (yfinance).
=========================================
Esta é a ÚNICA camada do projeto que fala diretamente com o yfinance.
Motivo: se um dia trocarmos/complementarmos com a SEC EDGAR (data.sec.gov)
para dados mais rigorosos, só este arquivo muda — dcf.py, valuation_export.py
e dashboard.py continuam recebendo os dados no mesmo formato.

Baseado na exploração real da AAPL (Etapa 1, notebooks/01_explorar_aapl.py),
sabemos que:
  - yf.download(tickers, period="3y") devolve colunas MultiIndex
    (campo, ticker); df["Close"] já dá um DataFrame largo (1 coluna por ticker).
  - .info é um dict com chaves como 'sector', 'industry', 'beta' etc.
  - .financials / .balance_sheet / .cashflow são DataFrames com itens como
    índice (linhas) e períodos (datas) como colunas, ordenados do mais
    recente para o mais antigo.

IMPORTANTE: nem toda empresa tem exatamente as mesmas linhas contábeis
(ex: TSM é uma ADR, reporta via 20-F e pode ter nomenclatura diferente de
uma empresa americana comum). Por isso usamos `buscar_linha()` abaixo, que
tenta múltiplos nomes possíveis em vez de assumir um nome fixo.
"""

from datetime import datetime, timezone
import warnings

import pandas as pd
import yfinance as yf

from . import config
from . import db


def baixar_precos_brutos(tickers: list[str], anos: int = config.ANOS_HISTORICO_PRECO) -> pd.DataFrame:
    """
    Baixa o histórico de preços de TODOS os tickers em UMA única chamada
    (nunca em loop, para não estourar rate limit e para garantir que todas
    as séries tenham exatamente a mesma janela de datas).

    Retorna o DataFrame bruto do yfinance, com colunas MultiIndex
    (campo OHLCV, ticker). Use `baixar_precos_historicos` para o formato
    "largo" (só Close) usado no gráfico comparativo, ou `_extrair_dataframe_completo`
    para o OHLCV completo de um ticker específico (usado ao salvar no banco).
    """
    bruto = yf.download(
        tickers,
        period=f"{anos}y",
        auto_adjust=True,   # já ajusta por proventos/desdobramentos
        progress=False,
        group_by="column",
    )

    if bruto.empty:
        raise RuntimeError(
            "Download de preços retornou vazio. Verifique conexão com a "
            "internet ou se os tickers estão corretos."
        )

    return bruto


def baixar_precos_historicos(tickers: list[str], anos: int = config.ANOS_HISTORICO_PRECO) -> pd.DataFrame:
    """
    Retorna um DataFrame "largo": índice = data, colunas = ticker, valores = Close.
    Esse é o formato que o gráfico comparativo (Etapa 4) espera.
    """
    bruto = baixar_precos_brutos(tickers, anos)
    return bruto["Close"].copy()


def _extrair_dataframe_completo(bruto: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Helper interno: extrai OHLCV de UM ticker do DataFrame multi-ticker bruto."""
    return pd.DataFrame({
        "Close": bruto["Close"][ticker],
        "High": bruto["High"][ticker],
        "Low": bruto["Low"][ticker],
        "Open": bruto["Open"][ticker],
        "Volume": bruto["Volume"][ticker],
    }).dropna()


def buscar_linha(df: pd.DataFrame, nomes_possiveis: list[str], coluna=None):
    """
    Procura uma linha em df.index testando múltiplos nomes possíveis
    (diferentes empresas/relatórios podem nomear o mesmo conceito contábil
    de formas diferentes). Retorna o valor da primeira coluna (mais recente)
    ou da coluna especificada. Retorna None se nenhum nome for encontrado.
    """
    for nome in nomes_possiveis:
        if nome in df.index:
            serie = df.loc[nome]
            valor = serie.iloc[0] if coluna is None else serie.get(coluna)
            if pd.notna(valor):
                return float(valor)
    return None


def buscar_info_cadastral(ticker_obj: yf.Ticker) -> dict:
    """Extrai os campos cadastrais relevantes de .info, com defaults seguros."""
    info = ticker_obj.info
    datas_resultado = buscar_datas_resultado(ticker_obj)
    return {
        "nome": info.get("longName") or info.get("shortName") or ticker_obj.ticker,
        "setor": info.get("sector", "N/A"),
        "industria": info.get("industry", "N/A"),
        "descricao": info.get("longBusinessSummary", ""),
        "beta": info.get("beta"),
        "preco_atual": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": info.get("marketCap"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "moeda": info.get("currency", "USD"),
        # Moeda em que as DEMONSTRAÇÕES FINANCEIRAS são reportadas — pode ser
        # diferente da moeda de negociação (ver obter_taxa_cambio_para_usd).
        "moeda_financeira": info.get("financialCurrency", info.get("currency", "USD")),
        "ultima_divulgacao_resultado": datas_resultado["ultima_divulgacao"],
        "proxima_divulgacao_resultado": datas_resultado["proxima_divulgacao"],
    }


def buscar_datas_resultado(ticker_obj: yf.Ticker) -> dict:
    """
    Busca a data da última divulgação de resultado já ocorrida e da próxima
    prevista, via calendário de earnings do yfinance.

    Por quê isso importa: os fundamentos (financials/balance/cashflow) só
    mudam de verdade quando a empresa divulga um resultado novo (~4x por
    ano). Guardamos essas datas para `precisa_atualizar_fundamentos` decidir
    se vale a pena bater na API de novo, ou se o que já está no banco ainda
    é válido — isso é literalmente o "pipeline de acompanhamento de
    resultados corporativos" mencionado na descrição da vaga.
    """
    try:
        datas = ticker_obj.get_earnings_dates(limit=8)
        if datas is None or datas.empty:
            return {"ultima_divulgacao": None, "proxima_divulgacao": None}

        agora = pd.Timestamp.now(tz=datas.index.tz)
        passadas = datas.index[datas.index <= agora]
        futuras = datas.index[datas.index > agora]

        ultima = str(passadas.max().date()) if len(passadas) else None
        proxima = str(futuras.min().date()) if len(futuras) else None
        return {"ultima_divulgacao": ultima, "proxima_divulgacao": proxima}
    except Exception as erro:
        warnings.warn(f"Não foi possível buscar datas de divulgação de resultado: {erro}")
        return {"ultima_divulgacao": None, "proxima_divulgacao": None}


def precisa_atualizar_fundamentos(conn, ticker: str) -> bool:
    """
    Decide se vale a pena rebuscar financials/balance_sheet/cashflow via
    API, ou se os dados já salvos no banco ainda são válidos.

    Regra: só precisa atualizar se
      (a) a empresa nunca foi buscada antes, OU
      (b) a "última divulgação de resultado" conhecida é diferente da que
          está salva (ou seja, saiu um resultado novo desde a última busca).

    Isso evita bater na API de fundamentos toda vez que o dashboard roda —
    eles só mudam ~4x por ano. Preço e câmbio continuam sendo atualizados
    sempre (são baratos e mudam todo dia).
    """
    estado = db.buscar_estado_empresa(conn, ticker)
    if estado is None:
        return True

    _, ultima_divulgacao_salva = estado
    if ultima_divulgacao_salva is None:
        return True

    datas_atuais = buscar_datas_resultado(yf.Ticker(ticker))
    return datas_atuais["ultima_divulgacao"] != ultima_divulgacao_salva


def obter_taxa_cambio_para_usd(moeda_origem: str) -> float:
    """
    Fator de conversão de `moeda_origem` para USD (1 unidade de moeda_origem
    em USD). Necessário porque ADRs negociam em USD na bolsa americana, mas
    reportam as demonstrações financeiras na moeda do país de origem.

    Descoberto testando a Etapa 3: a TSM reporta em TWD (New Taiwan Dollar).
    Sem essa conversão, o DCF misturava receita/EBIT em TWD com market cap/
    preço em USD, gerando um preço-alvo ~30x maior que o real.
    """
    if moeda_origem == "USD":
        return 1.0
    try:
        par_cambial = yf.Ticker(f"{moeda_origem}USD=X")
        historico = par_cambial.history(period="5d")
        if historico.empty:
            raise ValueError("histórico de câmbio vazio")
        return float(historico["Close"].iloc[-1])
    except Exception as erro:
        fallback_moeda_por_usd = config.FX_FALLBACK_PARA_USD.get(moeda_origem)
        if fallback_moeda_por_usd is None:
            warnings.warn(
                f"Sem taxa de câmbio {moeda_origem}->USD (ao vivo falhou: {erro}) "
                f"e sem fallback configurado em config.FX_FALLBACK_PARA_USD. "
                f"Usando fator 1.0 (SEM CONVERSÃO) — revise manualmente."
            )
            return 1.0
        fator = 1.0 / fallback_moeda_por_usd
        print(f"[aviso] Câmbio {moeda_origem}->USD ao vivo indisponível ({erro}). "
              f"Usando fallback: 1 {moeda_origem} = {fator:.5f} USD")
        return fator


def buscar_dados_empresa(ticker: str) -> dict:
    """
    Busca o "pacote completo" de dados de UMA empresa: cadastro + as 3
    demonstrações financeiras (financials, balance_sheet, cashflow), já
    convertidas para USD quando a empresa reporta em outra moeda (ADRs).

    Retorna um dict com:
      - 'ticker', 'info' (dict cadastral)
      - 'financials', 'balance_sheet', 'cashflow' (DataFrames em USD,
        prontos para salvar no banco e para o DCF usar diretamente)
    """
    ticker_obj = yf.Ticker(ticker)

    info = buscar_info_cadastral(ticker_obj)

    financials = ticker_obj.financials
    balance_sheet = ticker_obj.balance_sheet
    cashflow = ticker_obj.cashflow

    if financials.empty or balance_sheet.empty or cashflow.empty:
        warnings.warn(
            f"[{ticker}] Uma ou mais demonstrações financeiras vieram vazias. "
            f"Isso pode acontecer com ADRs (ex: TSM) que reportam com atraso "
            f"ou em formato diferente. Vale checar manualmente."
        )

    # Converte para USD se a empresa reporta as financeiras em outra moeda
    # (ex: TSM em TWD). market_cap/shares/preço já vêm em USD do próprio
    # yfinance, então só as 3 demonstrações precisam de conversão.
    moeda_financeira = info["moeda_financeira"]
    moeda_negociacao = info["moeda"]
    if moeda_financeira != moeda_negociacao:
        fator = obter_taxa_cambio_para_usd(moeda_financeira)
        print(f"[{ticker}] Convertendo demonstrações financeiras de {moeda_financeira} "
              f"para {moeda_negociacao} (fator: {fator:.5f})")
        financials = financials * fator
        balance_sheet = balance_sheet * fator
        cashflow = cashflow * fator

    return {
        "ticker": ticker,
        "info": info,
        "financials": financials,
        "balance_sheet": balance_sheet,
        "cashflow": cashflow,
    }


def buscar_todas_as_empresas(tickers: list[str] = config.TICKERS, forcar_atualizacao: bool = False) -> dict:
    """
    Orquestrador: busca preços (1 chamada, sempre) + dados fundamentalistas
    (1 chamada por ticker, só quando necessário) de todas as empresas do
    projeto, e persiste tudo no SQLite.

    Preço e câmbio são sempre atualizados (são baratos e mudam todo dia).
    Fundamentos (financials/balance/cashflow) só são rebuscados se saiu um
    resultado novo desde a última vez (ver `precisa_atualizar_fundamentos`),
    ou se `forcar_atualizacao=True` (útil para forçar um refresh manual).

    Retorna um dict {ticker: dados_empresa} para uso imediato (ex: DCF),
    além de já ter salvo tudo em /data/valuation.db.
    """
    db.criar_schema()

    precos_brutos = baixar_precos_brutos(tickers)
    resultado = {}

    with db.conectar() as conn:
        for ticker in tickers:
            precos_ticker = _extrair_dataframe_completo(precos_brutos, ticker)

            # precos_historicos tem FOREIGN KEY para empresas(ticker), então
            # só podemos salvar o preço depois de garantir que a empresa já
            # existe no banco (o que só acontece na primeira busca).
            if not forcar_atualizacao and not precisa_atualizar_fundamentos(conn, ticker):
                db.salvar_precos(conn, ticker, precos_ticker)  # preço: sempre atualiza
                print(f"{ticker}: sem resultado novo desde a última busca — "
                      f"mantendo fundamentos salvos, só atualizando preço.")
                continue

            print(f"Buscando fundamentos de {ticker} (primeira busca ou resultado novo disponível)...")
            dados = buscar_dados_empresa(ticker)
            resultado[ticker] = dados

            db.salvar_empresa(conn, {
                "ticker": ticker,
                "nome": dados["info"]["nome"],
                "setor": dados["info"]["setor"],
                "industria": dados["info"]["industria"],
                "descricao": dados["info"]["descricao"],
                "beta": dados["info"]["beta"],
                "market_cap": dados["info"]["market_cap"],
                "shares_outstanding": dados["info"]["shares_outstanding"],
                "preco_no_cadastro": dados["info"]["preco_atual"],
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
                "ultima_divulgacao_resultado": dados["info"]["ultima_divulgacao_resultado"],
                "proxima_divulgacao_resultado": dados["info"]["proxima_divulgacao_resultado"],
            })
            db.salvar_precos(conn, ticker, precos_ticker)  # preço: sempre atualiza

            # Salva as 3 demonstrações no formato long
            db.salvar_linhas_financeiras(conn, ticker, "financials", dados["financials"])
            db.salvar_linhas_financeiras(conn, ticker, "balance_sheet", dados["balance_sheet"])
            db.salvar_linhas_financeiras(conn, ticker, "cashflow", dados["cashflow"])

    resultado["_precos_comparativo"] = precos_brutos["Close"].copy()
    return resultado


if __name__ == "__main__":
    # Execução direta: busca tudo (respeitando o cache de fundamentos) e
    # imprime um resumo lendo direto do banco — assim reflete o estado real
    # mesmo para tickers cujos fundamentos foram pulados nesta rodada.
    buscar_todas_as_empresas()

    with db.conectar() as conn:
        print(f"\n{'Ticker':<7}{'Nome':<38}{'Setor':<24}{'Beta':>6}  Próx. resultado")
        for ticker in config.TICKERS:
            cur = conn.execute("""
                SELECT nome, setor, beta, proxima_divulgacao_resultado
                FROM empresas WHERE ticker = ?
            """, (ticker,))
            nome, setor, beta, proxima = cur.fetchone()
            print(f"{ticker:<7}{nome:<38}{setor:<24}{beta:>6.2f}  {proxima or 'N/A'}")

    print(f"\nBanco salvo em: {config.CAMINHO_BANCO_SQLITE}")
