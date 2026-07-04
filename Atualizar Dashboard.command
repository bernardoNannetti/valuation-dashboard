#!/bin/bash
# Duplo-clique neste arquivo para atualizar o dashboard de valuation.
# Não precisa terminal, não precisa abrir o Claude — é só isso.
#
# O que ele faz, em ordem:
#   1. Busca preços e fundamentos novos (yfinance) e recalcula o DCF.
#   2. Regenera os Excels, o comps_analysis.xlsx, o gráfico e o dashboard.html.
#   3. Se algo mudou, commita e publica (git push) no GitHub sozinho.
#   4. Abre o dashboard atualizado no navegador.

cd "$(dirname "$0")" || exit 1

echo "=========================================="
echo " Atualizando dashboard de valuation..."
echo "=========================================="
echo ""

python3 -m src.atualizar_tudo
STATUS_PIPELINE=$?

if [ $STATUS_PIPELINE -ne 0 ]; then
    echo ""
    echo "❌ Algo deu errado ao atualizar os dados. Veja o erro acima."
    echo ""
    echo "Pressione Enter para fechar esta janela..."
    read -r
    exit 1
fi

echo ""
echo "✅ Dados atualizados."

if [ -n "$(git status --porcelain)" ]; then
    echo ""
    echo "Publicando no GitHub..."
    git add -A
    git commit -m "Atualização automática de dados - $(date +%d/%m/%Y)" > /dev/null
    if git push; then
        echo "✅ Publicado no GitHub."
    else
        echo "⚠️  Não consegui publicar no GitHub (confira sua conexão ou login do git)."
        echo "   Os dados locais já estão atualizados mesmo assim."
    fi
else
    echo "Nenhuma mudança nos dados desde a última atualização."
fi

echo ""
echo "Abrindo o dashboard..."
sleep 1
open dashboard.html

echo ""
echo "Tudo pronto. Pressione Enter para fechar esta janela..."
read -r
