# Leiameoffchr

Módulo Chrome do ecossistema Leiameoff.

## Objetivo

Consolidar guias e soluções do Chrome em um mapa navegável de ações e resolução de problemas.

## Diretórios

- `sources/`: links e fontes de referência
- `data/`: templates e dados estruturados
- `workflows/`: checklists operacionais
- `tools/`: utilitários de coleta e verificação

## Fluxo local

1. Registrar fontes em `sources/links.md`
2. Sincronizar fontes para `data/source-index.json`
3. Criar ações em `data/action-map.template.json`
4. Executar revisão com o checklist em `workflows/triage-checklist.md`

## Ferramenta de coleta e verificação

Sincroniza links do markdown para o índice:

```bash
python /home/runner/work/awesome-python/awesome-python/leiameoffchr/tools/link_manager.py \
  --links /home/runner/work/awesome-python/awesome-python/leiameoffchr/sources/links.md \
  --index /home/runner/work/awesome-python/awesome-python/leiameoffchr/data/source-index.json \
  sync
```

Verifica links faltantes ou obsoletos:

```bash
python /home/runner/work/awesome-python/awesome-python/leiameoffchr/tools/link_manager.py \
  --links /home/runner/work/awesome-python/awesome-python/leiameoffchr/sources/links.md \
  --index /home/runner/work/awesome-python/awesome-python/leiameoffchr/data/source-index.json \
  check
```
