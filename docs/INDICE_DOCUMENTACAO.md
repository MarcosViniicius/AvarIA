# AvarIA — Índice da Documentação

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
docs/IDENTIDADE.md                 ← marca AvarIA: grafia, tagline, onde aparece, tom de voz
docs/MIGRACAO_NOME.md              ← registro do rebrand Auto Avaria → AvarIA (compatibilidades e rollback)
docs/INDICE_DOCUMENTACAO.md        ← este arquivo
```

## Convenção

- `avariaia/services/` = regras de negócio (puro, testável).
- `avariaia/routes/` = HTTP/Flask (fino, delega para services).
- `avariaia/core/paths.py` = única fonte de pastas/arquivos.
- SQLite (`database/avariaia.db`) = fonte da verdade: histórico, versionamento, catálogo e itens extraídos.
- Excel (`resultados/Relatorio_Mestre_Produtos.xlsx`) = export gerado sob demanda a partir do banco.
