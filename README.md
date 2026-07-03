# Dashboard de Valuation — Ações Globais

Pipeline de dados + modelo de DCF + dashboard interativo para 6 ações globais (AAPL, MSFT, AMZN, NVDA, GOOGL, TSM), construído como projeto de portfólio para demonstrar Python, SQL, Git/GitHub e uso prático de ferramentas de IA generativa (Claude Code) num fluxo de trabalho de research/análise financeira.

**[Abra `dashboard.html` no navegador](./dashboard.html)** para ver o resultado — é um arquivo estático, não precisa rodar nada.

---

## O que o projeto faz

1. **Extrai dados** de mercado e fundamentalistas (preço, demonstrações financeiras, beta, calendário de earnings) via `yfinance` e persiste tudo em SQLite.
2. **Calcula um DCF** (Discounted Cash Flow) completo por ação: WACC via CAPM, projeção de FCFF com fade de crescimento e CapEx, valor terminal (Gordon Growth), preço-alvo e recomendação (Compra/Neutro/Venda).
3. **Cruza com comps**: múltiplos de mercado (EV/Revenue, EV/EBITDA, P/E) das 6 empresas, com estatísticas de grupo (mediana/quartis), pra validar o DCF contra o que o mercado está de fato pagando.
4. **Gera um dashboard HTML** autocontido — cards de KPI, tabela ordenável/filtrável com painel de detalhe por ação (WACC, premissas, cross-check de comps), gráfico comparativo de retorno com benchmark (S&P 500) e modo escuro.
5. **Atualiza tudo automaticamente** todo dia via `launchd` (macOS), incluindo lógica de cache que só rebusca fundamentos quando sai um resultado novo (não a cada execução).

## Arquitetura / pipeline

```
data_fetch.py  →  SQLite (data/valuation.db)  →  dcf.py
                                                     ↓
                            ┌────────────────────────┼─────────────────────┐
                            ↓                        ↓                     ↓
                  valuation_export.py       comps_analysis.py     returns_chart.py
                  (1 Excel por ação)         (comps_analysis.xlsx)  (gráfico de retorno)
                            └────────────────────────┬─────────────────────┘
                                                       ↓
                                            dashboard_export.py
                                               (dashboard.html)
```

Cada módulo tem uma responsabilidade só (`data_fetch.py` é a ÚNICA camada que fala com a API externa; `db.py` só cuida de schema/persistência; `dcf.py` só calcula; os exportadores só formatam saída). `atualizar_tudo.py` orquestra o pipeline inteiro em sequência.

## Metodologia do DCF (resumo)

- **WACC**: CAPM (beta do yfinance, Treasury 10Y como taxa livre de risco, prêmio de risco de mercado de Damodaran) + custo de dívida real da empresa, ponderado por valor de mercado.
- **Crescimento de receita**: consenso de analistas pesquisado manualmente no ano 1, com fade linear até a taxa de crescimento na perpetuidade (2,5%) ao longo do horizonte de projeção (5 anos).
- **CapEx**: parte da guidance pública de investimento de cada empresa (ano 1), com fade rápido até a média histórica — reflete o pico de investimento em IA das big techs sem assumir que ele dura para sempre.
- **Margem EBIT / D&A% / ΔWC%**: médias históricas dos últimos 2 anos (não o histórico completo — testamos e distorcia empresas com margem em transição rápida, como a AMZN).
- Todas as premissas (com o racional de cada uma, incluindo experimentos que NÃO funcionaram e foram revertidos) estão documentadas em `src/config.py` e nos comentários de `src/dcf.py`.

**Limitação conhecida**: é um DCF simples de horizonte curto. Em julho/2026, ele aponta "Venda" para as 6 ações — não porque o modelo esteja quebrado, mas porque o preço de mercado subiu muito mais rápido do que as premissas fundamentalistas (capex pesado debitado quase 1:1 no fluxo de caixa, sem creditar totalmente o crescimento de lucro que esse investimento deve gerar além do horizonte de 5 anos). É uma crítica clássica de DCF "vanilla" em fase de capex pesado — por isso o cross-check com comps existe. TSM também não é um comparável perfeito do resto do grupo (manufatura vs. plataformas de software) nem faz parte do S&P 500 (empresa domiciliada em Taiwan) — ambas as ressalvas estão documentadas no `comps_analysis.xlsx`.

## Stack técnica

Python · pandas · yfinance · SQLite · openpyxl (Excel com fórmulas, não valores hardcoded) · Plotly · HTML/CSS/JS vanilla (dashboard) · Streamlit (versão alternativa em `src/dashboard.py`) · launchd (automação)

## Como rodar

```bash
pip install -r requirements.txt

# Pipeline completo (busca dados, gera Excels, comps, gráfico e dashboard)
python -m src.atualizar_tudo

# Ou só o dashboard, se os dados já estiverem no banco
python -m src.dashboard_export
```

Abra `dashboard.html` direto no navegador depois. A versão Streamlit alternativa roda com `streamlit run src/dashboard.py`.

**Nota**: `data_fetch.py` precisa de acesso à internet (yfinance). O restante do pipeline só lê do SQLite já populado.

## Uso de IA generativa (Claude Code)

Este projeto foi construído em parceria com o Claude (via Claude Code, rodando localmente) e o Cowork (Claude Desktop), num fluxo de trabalho deliberadamente disciplinado:

- **Arquitetura antes de código**: cada etapa foi desenhada e validada com o autor antes de qualquer linha ser escrita.
- **Estágios incrementais**: dado → DCF → gráfico → dashboard, cada um testado e commitado separadamente (ver histórico de commits).
- **Verificação computacional, não visual**: como a IA não consegue "ver" o resultado renderizado, todo código foi validado de outras formas — recálculo manual das fórmulas de DCF, recalculação headless de fórmulas do Excel (LibreOffice), checagem de sintaxe JS (Node), simulação de DOM real (jsdom, incluindo cliques e eventos) para o dashboard, e boot local do servidor Streamlit — antes de qualquer entrega ser considerada pronta.
- **Decisões de modelagem sempre confirmadas com o autor** antes de implementadas (ex: threshold de recomendação, período de médias históricas, tratamento do capex de IA).
- **Bugs reais encontrados e corrigidos** ao longo do processo (documentados em `src/*.py` e nas mensagens de commit): conversão de moeda de ADR (TSM reporta em TWD), duplicidade de classes de ação (GOOGL/GOOG subestimava o market cap), fórmula de Excel autorreferenciada, formatação de hover do Plotly em modo "unified", entre outros.
- **Duas ferramentas complementares**: o Cowork (sandbox sem acesso a APIs financeiras) foi usado para escrever/editar código e gerar arquivos; o Claude Code (terminal local, com rede) foi usado especificamente para os passos que precisam de internet (busca de dados) ou de permissões de sistema de arquivos (commits do git).

## Limitações conhecidas

- DCF simples de 5 anos tende a subestimar mega caps de alto crescimento (ver seção de metodologia acima).
- TSM não é um comparável perfeito das outras 5 empresas (modelo de negócio de manufatura vs. plataformas).
- Fonte única de dados (yfinance) — sem redundância caso a API mude ou fique indisponível.
- Sem testes automatizados ainda (pasta `tests/` existe mas está vazia).

## Estrutura de pastas

```
src/               código-fonte (um módulo por responsabilidade)
valuations/        1 Excel de DCF por ação (gerado)
comps_analysis.xlsx  análise de comparáveis (gerado)
dashboard.html     dashboard consolidado (gerado)
scripts/           automação diária (launchd)
notebooks/         exploração inicial (Etapa 1)
data/              banco SQLite (não versionado)
```
