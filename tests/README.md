# Curadoria de Testes

Mapa canônico da suíte. Leia antes de criar um teste novo — **não duplique**.

## Regras

- `tmp_db` (`conftest.py`) para tudo que toca `db`/`catalogo`. Nunca toque em `database/autoavaria.db`.
- Mocke `barcode.ler_imagem` (não dependa de opencv/zxing). Imagem sintética só em `test_barcode.py` com `importorskip`.
- IA real nunca: `MagicMock` provider + patch `ai_extraction.extrair_dados_de_lote`.
- Um comportamento, um dono. Consulte a tabela antes de adicionar.

## Mapa (arquivo → dono → SUT)

| Arquivo | Dono | SUT |
|---|---|---|
| `test_extraction.py` | descompactação | `services/extraction.py` |
| `test_barcode.py` | leitura EAN/balança | `services/barcode.py` |
| `test_conversa.py` | parser WhatsApp | `services/conversa.py` |
| `test_catalogo.py` | catálogo base | `services/catalogo.py` |
| `test_ai_providers.py` | provedores IA | `services/ai.py` |
| `test_ai_extraction.py` | prompt/split base | `services/ai_extraction.py` |
| `test_extraction_engines.py` | motores base | `services/extraction_engines.py` |
| `test_classificacao_imagens.py` | **só gaps** de classificação | engines/ai_extraction (casos novos) |
| `test_processamento_backend.py` | **só gaps** de backend | barcode/conversa/unificação/excel (edges novos) |
| `test_extraction_pipeline.py` | orquestração | `services/extraction_pipeline.py` |
| `test_unification.py` | unificação pura | `services/unification.py` |
| `test_unificacao.py` | rota unificação (última execução) | `routes/unificacao.py` |
| `test_excel_report.py` | merge Excel | `services/excel_report.py` |
| `test_export_service.py` | escritor xlsx/txt | `services/export_service.py` |
| `test_relatorio.py` | rota relatório/imagem | `routes/relatorio.py` |
| `test_edicao.py` | rotas de edição (sync DB) | `routes/edicao.py` |
| `test_report_editing.py` | IO de planilha | `services/report_editing.py` |
| `test_historico.py` | reanálise/versionamento (+ filtros) | `routes/historico.py` |
| `test_reanalise_seletiva.py` | reanálise seletiva (1/vários/todos) | `services/extraction_pipeline` + `POST /api/reanalisar_mestre` |
| `test_upload.py` | upload | `routes/upload.py` |
| `test_processing.py` | status/processamento | `routes/processing.py` |
| `test_db.py` | SQLite | `services/db.py` |
| `test_config_service.py` | config | `services/config_service.py` |
| `test_dashboard.py` / `test_stats.py` | dashboard | `routes/dashboard.py` / `services/stats.py` |
| `test_maintenance.py` | retenção exports | `services/maintenance.py` |
| `test_manutencao.py` | rota limpeza | `routes/manutencao.py` |
| `test_campo_migration.py` | migração legada | `services/campo_migration.py` |
| `test_image_archive.py` | arquivamento | `services/image_archive.py` |
| `test_static_versioning.py` | cache-busting | `__init__.py` static |
| `test_app_smoke.py` | smoke GETs | app (DB real, só leitura) |

Pares com nome parecido são camadas distintas — **não mesclar**:
`maintenance` (service) x `manutencao` (rota), `unification` (pura) x `unificacao` (rota),
`edicao` (rota+DB) x `report_editing` (IO), `excel_report` (wrapper) x `export_service` (primitiva).

## Gaps conhecidos (não cobertos — contribuir aqui)

- Rotas POST/DELETE sem teste: `POST /processar` feliz, `GET /status`, `POST /historico/.../unificar|exportar`, CRUD `historico .../item/*`, `POST /api/reanalisar_erros`, `GET /api/opcoes_exportacao`, `POST /salvar_configuracao`, `GET /api/listar_modelos/<p>`.
- `rar/7z` em `extraction.py`, `token_usage` asserts no pipeline, `get_modelos` OpenAI/Claude/OpenRouter, `_codificar_imagem_base64`, erro/timeout Claude/OpenRouter.
- `create_app` nos testes de rota toca o DB real no init (só leitura hoje) — migrar para fixture `app isolado` quando possível.
