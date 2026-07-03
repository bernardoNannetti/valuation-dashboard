"""
Atualização diária completa do pipeline
==========================================
Executa em sequência: extração de dados (preço sempre; fundamentos só se
saiu resultado novo, ver data_fetch.precisa_atualizar_fundamentos) ->
Excel de DCF por ação -> comps analysis -> gráfico comparativo de retorno ->
dashboard.html (site estático consolidado, ver dashboard_export.py).

Pensado para rodar automaticamente todo dia via launchd (macOS) — ver
scripts/atualizar_diario.sh e scripts/com.valuation-dashboard.diario.plist.

IMPORTANTE: só funciona rodando LOCALMENTE (Claude Code ou Terminal do
Mac), nunca dentro do sandbox do Cowork. O Cowork bloqueia acesso a APIs
financeiras (yfinance, câmbio), então um agendamento feito por lá falharia
sempre no primeiro passo (busca de preços).
"""

import sys
import traceback
from datetime import datetime

from . import data_fetch
from . import valuation_export
from . import comps_analysis
from . import returns_chart
from . import dashboard_export
from . import config


def atualizar_tudo() -> bool:
    inicio = datetime.now()
    print(f"=== Atualização iniciada em {inicio.isoformat()} ===")

    try:
        print("1/6 - Buscando preços e fundamentos (yfinance -> SQLite)...")
        data_fetch.buscar_todas_as_empresas()

        print(f"2/6 - Buscando benchmark ({config.TICKER_BENCHMARK} / {config.NOME_BENCHMARK})...")
        data_fetch.baixar_benchmark()

        print("3/6 - Gerando Excel de DCF por ação em /valuations...")
        valuation_export.gerar_todos()

        print("4/6 - Gerando comps_analysis.xlsx...")
        comps_analysis.gerar_comps_analysis()

        print("5/6 - Gerando grafico_comparativo.html...")
        fig = returns_chart.gerar_grafico()
        returns_chart.salvar_grafico_html(fig, f"{config.DIR_RAIZ}/grafico_comparativo.html")

        print("6/6 - Gerando dashboard.html...")
        dashboard_export.gerar_e_salvar()

        fim = datetime.now()
        print(f"=== Atualização concluída em {fim.isoformat()} (duração: {fim - inicio}) ===")
        return True
    except Exception:
        print("ERRO durante a atualização automática:")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    sucesso = atualizar_tudo()
    sys.exit(0 if sucesso else 1)
