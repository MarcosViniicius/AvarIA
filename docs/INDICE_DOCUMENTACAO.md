# Auto Avaria — Índice da Documentação

Documentação oficial do repositório, organizada por público.

## Para quem tem pressa

| Público | Comece por |
|---|---|
| Usuário normal (opera a loja, envia fotos) | `docs/GUIA_USUARIO.md` |
| Desenvolvedor (vai rodar, debugar, estender) | `docs/GUIA_DESENVOLVEDOR.md` |
| Aprofundamento em processamento/classificação | `docs/ARQUITETURA_PROCESSAMENTO.md` |
| Agente de IA / contribuidor automatizado | `AGENTS.md` (raiz) |
| Referência rápida de comandos | `docs/GUIA_DESENVOLVEDOR.md#referência-rápida` |

## Arquivos

```
AGENTS.md                          ← instruções para IAs (repo map, regras, comandos)
docs/GUIA_USUARIO.md               ← passo a passo operacional, conceitos, FAQ
docs/GUIA_DESENVOLVEDOR.md         ← setup, arquitetura, rotas, banco, testes, deploy
docs/ARQUITETURA_PROCESSAMENTO.md  ← deep dive: barcode, IA, conversa, catálogo, pipeline, unificação
docs/INDICE_DOCUMENTACAO.md        ← este arquivo
```

## Convenção

- `autoavaria/services/` = regras de negócio (puro, testável).
- `autoavaria/routes/` = HTTP/Flask (fino, delega para services).
- `autoavaria/core/paths.py` = única fonte de pastas/arquivos.
- Excel mestre (`resultados/Relatorio_Mestre_Produtos.xlsx`) = fonte de trabalho do usuário.
- SQLite (`database/autoavaria.db`) = histórico, versionamento, catálogo.
- Os dois andam juntos: cada lote persiste em **ambos** antes de marcar a imagem como processada.
