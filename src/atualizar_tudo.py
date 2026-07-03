"""
Atualização diária completa do pipeline
==========================================
Executa em sequência: extração de dados (preço sempre; fundamentos só se
saiu resultado novo, ver data_fetch.precisa_atualizar_fundamentos) ->
Excel de DCF por ação -> comps analysis -> gráfico comparativo de retorno.

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
from . import config


def atualizar_tudo() -> bool:
    inicio = datetime.now()
    print(f"=== Atualização iniciada em {inicio.isoformat()} ===")

    try:
        print("1/4 - Buscando preços e fundamentos (yfinance -> SQLite)...")
        data_fetch.buscar_todas_as_empresas()

        print("2/4 - Gerando Excel de DCF por ação em /valuations...")
        valuation_export.gerar_todos()

        print("3/4 - Gerando comps_analysis.xlsx...")
        comps_analysis.gerar_comps_analysis()

        print("4/4 - Gerando grafico_comparativo.html...")
        fig = returns_chart.gerar_grafico()
        returns_chart.salvar_grafico_html(fig, f"{config.DIR_RAIZ}/grafico_comparativo.html")

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
