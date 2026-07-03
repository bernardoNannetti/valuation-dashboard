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
    }


def buscar_dados_empresa(ticker: str) -> dict:
    """
    Busca o "pacote completo" de dados de UMA empresa: cadastro + as 3
    demonstrações financeiras (financials, balance_sheet, cashflow).

    Retorna um dict com:
      - 'ticker', 'info' (dict cadastral)
      - 'financials', 'balance_sheet', 'cashflow' (DataFrames brutos,
        para salvar no banco e para o DCF usar como quiser)
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

    return {
        "ticker": ticker,
        "info": info,
        "financials": financials,
        "balance_sheet": balance_sheet,
        "cashflow": cashflow,
    }


def buscar_todas_as_empresas(tickers: list[str] = config.TICKERS) -> dict:
    """
    Orquestrador: busca preços (1 chamada) + dados fundamentalistas
    (1 chamada por ticker, pois .info/.financials não suportam batch) de
    todas as empresas do projeto, e persiste tudo no SQLite.

    Retorna um dict {ticker: dados_empresa} para uso imediato (ex: DCF),
    além de já ter salvo tudo em /data/valuation.db.
    """
    db.criar_schema()

    precos_brutos = baixar_precos_brutos(tickers)
    resultado = {}

    with db.conectar() as conn:
        for ticker in tickers:
            print(f"Buscando dados de {ticker}...")
            dados = buscar_dados_empresa(ticker)
            resultado[ticker] = dados

            # Salva cadastro
            db.salvar_empresa(conn, {
                "ticker": ticker,
                "nome": dados["info"]["nome"],
                "setor": dados["info"]["setor"],
                "industria": dados["info"]["industria"],
                "descricao": dados["info"]["descricao"],
                "beta": dados["info"]["beta"],
                "market_cap": dados["info"]["market_cap"],
                "shares_outstanding": dados["info"]["shares_outstanding"],
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
            })

            # Salva o OHLCV completo deste ticker (recortado do download em lote)
            precos_ticker = _extrair_dataframe_completo(precos_brutos, ticker)
            db.salvar_precos(conn, ticker, precos_ticker)

            # Salva as 3 demonstrações no formato long
            db.salvar_linhas_financeiras(conn, ticker, "financials", dados["financials"])
            db.salvar_linhas_financeiras(conn, ticker, "balance_sheet", dados["balance_sheet"])
            db.salvar_linhas_financeiras(conn, ticker, "cashflow", dados["cashflow"])

    resultado["_precos_comparativo"] = precos_brutos["Close"].copy()
    return resultado


if __name__ == "__main__":
    # Execução direta: busca tudo e imprime um resumo de checagem por ticker.
    dados = buscar_todas_as_empresas()
    for ticker in config.TICKERS:
        info = dados[ticker]["info"]
        print(f"\n{ticker}: {info['nome']} | {info['setor']} / {info['industria']} "
              f"| beta={info['beta']} | preço atual={info['preco_atual']}")
    print(f"\nBanco salvo em: {config.CAMINHO_BANCO_SQLITE}")
