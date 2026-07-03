#!/bin/bash
# Wrapper chamado pelo launchd todo dia. Só existe porque o launchd prefere
# invocar um script simples a montar o ambiente Python direto no .plist.
set -e

PROJETO_DIR="$HOME/Desktop/valuation-dashboard"
LOG_DIR="$PROJETO_DIR/logs"
mkdir -p "$LOG_DIR"

cd "$PROJETO_DIR"
echo "--- Rodando atualização diária: $(date) ---" >> "$LOG_DIR/atualizacao.log"
/usr/bin/env python3 -m src.atualizar_tudo >> "$LOG_DIR/atualizacao.log" 2>&1
echo "--- Fim: $(date) ---" >> "$LOG_DIR/atualizacao.log"
