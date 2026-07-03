"""
Camada de persistência em SQLite.
===================================
Por quê SQLite (e não só Excel/CSV)? Três motivos:
  1. A vaga que motivou este projeto pede conhecimento em SQL explicitamente.
  2. Consultas (ex: "me dê o histórico de receita de todas as ações") ficam
     triviais com SELECT, em vez de reabrir e concatenar planilhas.
  3. Separa "dado bruto coletado" de "dado processado" (Excel de valuation).
     Se o DCF mudar, não precisamos rebaixar da API de novo — já está no banco.

Este módulo só cuida de CRIAR o schema e LER/ESCREVER dados. A lógica de
"o que buscar" fica em data_fetch.py; a lógica de "como calcular o DCF"
fica em dcf.py. Cada módulo tem uma responsabilidade só.
"""

import sqlite3
import os
from contextlib import contextmanager

from . import config


def _garantir_pasta_data():
    """Cria a pasta /data se ainda não existir."""
    os.makedirs(config.DIR_DATA, exist_ok=True)


@contextmanager
def conectar():
    """
    Context manager para abrir/fechar a conexão SQLite de forma segura.
    Uso: `with conectar() as conn: conn.execute(...)`
    """
    _garantir_pasta_data()
    conn = sqlite3.connect(config.CAMINHO_BANCO_SQLITE)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def criar_schema():
    """
    Cria as tabelas do banco, se ainda não existirem.

    Schema:
      empresas        -> 1 linha por ticker (dados cadastrais)
      precos_historicos -> série temporal de preços (1 linha por ticker/data)
      linhas_financeiras -> formato "long" para financials/balance/cashflow:
                            cada linha = (ticker, demonstrativo, item, período, valor)
                            Esse formato genérico evita ter que criar uma
                            coluna nova toda vez que aparece um item contábil
                            diferente (ex: TSM pode ter linhas que AAPL não tem).
    """
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS empresas (
                ticker TEXT PRIMARY KEY,
                nome TEXT,
                setor TEXT,
                industria TEXT,
                descricao TEXT,
                beta REAL,
                market_cap REAL,
                shares_outstanding REAL,
                atualizado_em TEXT,
                ultima_divulgacao_resultado TEXT,
                proxima_divulgacao_resultado TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS precos_historicos (
                ticker TEXT,
                data TEXT,
                close REAL,
                high REAL,
                low REAL,
                open REAL,
                volume INTEGER,
                PRIMARY KEY (ticker, data),
                FOREIGN KEY (ticker) REFERENCES empresas(ticker)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS linhas_financeiras (
                ticker TEXT,
                demonstrativo TEXT,   -- 'financials' | 'balance_sheet' | 'cashflow'
                item TEXT,            -- ex: 'Total Revenue', 'Free Cash Flow'
                periodo TEXT,         -- data do período (ex: '2025-09-30')
                valor REAL,
                PRIMARY KEY (ticker, demonstrativo, item, periodo),
                FOREIGN KEY (ticker) REFERENCES empresas(ticker)
            )
        """)

        # Migração leve: se o banco já existia de uma versão anterior do
        # schema (sem as colunas de divulgação de resultado), adiciona agora.
        # SQLite não tem "ADD COLUMN IF NOT EXISTS" em todas as versões, então
        # tentamos e ignoramos o erro se a coluna já existir.
        for coluna in ("ultima_divulgacao_resultado", "proxima_divulgacao_resultado"):
            try:
                conn.execute(f"ALTER TABLE empresas ADD COLUMN {coluna} TEXT")
            except sqlite3.OperationalError:
                pass  # coluna já existe

        # Índices para acelerar as consultas mais comuns do DCF
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_linhas_ticker_item
            ON linhas_financeiras (ticker, item)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_precos_ticker
            ON precos_historicos (ticker)
        """)


def salvar_empresa(conn, dados_empresa: dict):
    """Insere ou atualiza os dados cadastrais de uma empresa (UPSERT)."""
    conn.execute("""
        INSERT INTO empresas
            (ticker, nome, setor, industria, descricao, beta,
             market_cap, shares_outstanding, atualizado_em,
             ultima_divulgacao_resultado, proxima_divulgacao_resultado)
        VALUES (:ticker, :nome, :setor, :industria, :descricao, :beta,
                :market_cap, :shares_outstanding, :atualizado_em,
                :ultima_divulgacao_resultado, :proxima_divulgacao_resultado)
        ON CONFLICT(ticker) DO UPDATE SET
            nome=excluded.nome, setor=excluded.setor, industria=excluded.industria,
            descricao=excluded.descricao, beta=excluded.beta,
            market_cap=excluded.market_cap,
            shares_outstanding=excluded.shares_outstanding,
            atualizado_em=excluded.atualizado_em,
            ultima_divulgacao_resultado=excluded.ultima_divulgacao_resultado,
            proxima_divulgacao_resultado=excluded.proxima_divulgacao_resultado
    """, dados_empresa)


def buscar_estado_empresa(conn, ticker: str):
    """
    Retorna (atualizado_em, ultima_divulgacao_resultado) já salvos para o
    ticker, ou None se a empresa ainda não foi buscada nenhuma vez.
    Usado por data_fetch.py para decidir se vale a pena rebuscar os
    fundamentos (financials/balance/cashflow) ou se os dados salvos ainda
    são válidos (nenhum resultado novo divulgado desde a última busca).
    """
    cur = conn.execute("""
        SELECT atualizado_em, ultima_divulgacao_resultado
        FROM empresas WHERE ticker = ?
    """, (ticker,))
    return cur.fetchone()


def salvar_precos(conn, ticker: str, df_precos):
    """
    Salva o histórico de preços de um ticker.
    df_precos: DataFrame com índice de datas e colunas Close/High/Low/Open/Volume.
    """
    registros = [
        (ticker, str(idx.date()), row["Close"], row["High"], row["Low"], row["Open"], int(row["Volume"]))
        for idx, row in df_precos.iterrows()
    ]
    conn.executemany("""
        INSERT OR REPLACE INTO precos_historicos
            (ticker, data, close, high, low, open, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, registros)


def salvar_linhas_financeiras(conn, ticker: str, demonstrativo: str, df):
    """
    Salva um DataFrame de financials/balance_sheet/cashflow no formato long.
    df: índice = itens (ex: 'Total Revenue'), colunas = períodos (Timestamps).
    """
    registros = []
    for item in df.index:
        for periodo in df.columns:
            valor = df.loc[item, periodo]
            if valor is None or (isinstance(valor, float) and valor != valor):  # NaN check
                continue
            registros.append((ticker, demonstrativo, str(item), str(periodo.date()), float(valor)))

    conn.executemany("""
        INSERT OR REPLACE INTO linhas_financeiras
            (ticker, demonstrativo, item, periodo, valor)
        VALUES (?, ?, ?, ?, ?)
    """, registros)
