# Guia do Desenvolvedor — AvarIA

Setup, arquitetura, backend, rotas, banco, testes e deploy.

## 1. Setup

```bash
git clone https://github.com/MarcosViniicius/avariaia
cd avariaia
python -m venv venv
.\venv\Scripts\activate        # Windows | source venv/bin/activate (Linux/Mac)
pip install -r requirements.txt
pip install -r requirements-dev.txt
python app.py                  # http://localhost:5000
```

Na primeira execução, `config/config.json` é criado com defaults. Configure a API key em **Configurações** ou via env (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`). `config/config.json` está no `.gitignore` — nunca commite.

### Referência rápida

```bash
python -m pytest -q                                   # suíte completa (~22s, 371 testes)
python -m pytest tests/test_classificacao_imagens.py tests/test_processamento_backend.py -q
python -m pytest tests/test_barcode.py tests/test_extraction_engines.py -q
```

## 2. Arquitetura

```
app.py → avariaia.create_app()
  core/paths.py        única fonte de paths (suporte Vercel /tmp vs local)
  core/logging.py      logging compartilhado
  core/exceptions.py   exceções
  services/            regras de negócio (puro, testável, sem Flask)
  routes/              blueprints finos (HTTP → services)
  templates/ + static/ Jinja + Bootstrap, tema claro/escuro
```

`create_app()` (`avariaia/__init__.py:56`): settings → logging → `ensure_directories()` → `db.init_db()` → `backfill_relatorios_unificados` → `campo_migration` → `catalogo.popular_do_historico()` → blueprints → aliases → error handlers → static versioning (`mtime`) → optimizations.

Princípios: rotas finas, services puros, Excel = fonte de trabalho, SQLite = histórico/versionamento/catálogo, escrita única de export (`export_service.py`), unificação pura (`unification.py`).

## 3. Backend por módulo (services)

| Módulo | Responsabilidade | Funções-chave |
|---|---|---|
| `extraction.py` | Descompactação segura, anti-zip-slip, dedup SHA256 | `ExtratorArquivos.extrair_todos()`, `nome_para_gravar()` |
| `barcode.py` | Leitura local EAN-13, DV, balança prefixo 2 | `ean13_valido()`, `eh_etiqueta_balanca()`, `interpretar_etiqueta_balanca()`, `calcular_peso()`, `ler_imagem()` |
| `ai.py` | Multi-provedor, ordem texto/imagem preservada | `AIProvider.gerar_conteudo()`, `AIProviderFactory.criar_provedor()`, `obter_modelos()` (cache 600s) |
| `ai_extraction.py` | Prompt (texto>imagem), retry 3x, split Misto | `extrair_dados_de_lote()`, `processar_resultado_arquivo()` |
| `extraction_engines.py` | MotorIA / MotorCodigoBarras / MotorHibrido, mesmo contrato | `construir_motor()`, `processar_lote()`, `_precisa_de_ia()`, `_aprender_do_resultado()` |
| `conversa.py` | Parser WhatsApp → quantidade + observações | `mapear_contextos()`, `parsear_mensagens()`, `construir_contextos()`, `extrair_quantidade()` |
| `catalogo.py` | Código→produto, preco_kg interno, plausibilidade, expiração | `buscar()`, `registrar()`, `aprender()`, `aprender_preco_kg()`, `esta_desatualizado()`, `popular_do_historico()` |
| `extraction_pipeline.py` | Orquestração, lotes paralelos, persistência por lote, versionamento | `main()`, `reanalisar_erros()`, `reanalisar_execucao()`, `listar_imagens_pendentes()` |
| `excel_report.py` | Merge incremental + escrita atômica (temp+replace) | `salvar_relatorio_excel()` |
| `export_service.py` | Único escritor xlsx/txt detalhado/compacto | `escrever_xlsx()`, `escrever_txt_detalhado()`, `escrever_txt_compacto()` |
| `unification.py` | Agrupamento puro (Avarias por nome, Uso Interno por código) | `unificar_itens_avarias()`, `unificar_itens_uso_interno()` |
| `db.py` | SQLite: runs, items, unified, tokens, catálogo | `iniciar_execucao()`, `finalizar_execucao()`, `registrar_itens()`, `iniciar_reanalise_de_execucao()`, `resumo_geral()` |
| `reports.py` | GerenciadorErros (só aba Erros) | `GerenciadorErros.obter_erros_pendentes()`, `marcar_erro_como_reprocessado()` |
| `config_service.py` | config web (≠ pipeline), cache 300s, env override | `carregar_configuracao()`, `salvar_configuracao()` |

Detalhe do processamento e das regras de classificação: `docs/ARQUITETURA_PROCESSAMENTO.md`.

## 4. Rotas (routes, blueprint `web`)

| Blueprint | Endpoints principais |
|---|---|
| `upload.py` | `GET /upload`, `POST /upload_files` (dedup conteúdo, 50MB, forcar) |
| `processing.py` | `POST /processar` (lock, extração prévia reaproveitada), `POST /cancelar`, `GET /status` |
| `relatorio.py` | `GET /relatorio`, `GET /download_relatorio[?secoes&colunas]`, `GET /download_relatorio_txt`, `GET /api/opcoes_exportacao`, `GET /imagem/<path>` (ETag/304, cache 3600) |
| `historico.py` | `GET /historico`, `GET /historico/execucao/<id>`, `POST .../item/{editar,editar_completo,excluir,mover,adicionar}`, `GET .../exportar/<xlsx\|txt>`, `POST .../unificar`, `POST .../reanalisar` (só última versão, nova versão) |
| `erros.py` | `GET /api/obter_erros_pendentes`, `POST /api/reanalisar_erros` (só aba Erros, sem versionar), `GET /api/progresso_reanalise` |
| `edicao.py` | `GET /editar_dados`, `POST /salvar_edicao`, `/salvar_edicao_completa`, `/excluir_linha`, `/mover_item`, `/adicionar_linha` (backup + sync banco por caminho) |
| `unificacao.py` | `POST /api/unificar_relatorio` (fonte = última execução), `GET /download_relatorio_unificado/<f>`, `GET /api/opcoes_unificacao` |
| `dashboard.py` | `GET /`, `GET /api/stats` (cache 60s) |
| `manutencao.py` | `POST /limpar_dados` (`logs\|relatorio\|imagens\|reprocessar_tudo\|exportacoes`) |
| `logs.py` | `GET /logs`, `GET /api/logs` |
| `configuracoes.py` | `GET /configuracoes`, `GET/POST /api/configuracoes` (mascara `***`), `POST /salvar_configuracao`, `GET /download_config` |
| `ai_config.py` | `GET /api/listar_modelos/<provider>` |

## 5. Banco (SQLite, `database/avariaia.db`)

- `processing_runs(id, tipo, status, imagens_total, avarias, uso_interno, erros, tokens, mensagem, raiz_execucao_id, versao)` — reanálise = `versao = max+1`.
- `report_items(run_id, categoria, produto, peso, marca, codigo_barras, detalhes, observacao, caminho, quantidade)`.
- `unified_reports`, `token_usage`, `catalogo_produtos(codigo PK, tipo, produto, marca, preco_kg, categoria_padrao, origem, vezes_visto, atualizado_em)`, `catalogo_revisoes`.
- Conexão: `timeout=30`, `Row`, FK ON. Migrações de coluna em `init_db()`.
- `resumo_geral()`: contagens do DB + agregados do Excel mestre (evita dupla contagem).

## 6. Testes

```bash
pip install -r requirements-dev.txt
pytest                 # tudo
pytest tests/test_processamento_backend.py -q
pytest tests/test_classificacao_imagens.py -q
```

- `tests/conftest.py`: fixture `tmp_db` redireciona `db.DATABASE_DIR/FILE` para `tmp_path` + `init_db()`.
- Padrões: mocke `barcode.ler_imagem` (sem depender de hardware), `MagicMock` provider + patch `ai_extraction.extrair_dados_de_lote`, imagens sintéticas via `zxingcpp.create_barcode` com `importorskip`.
- Novos arquivos de cobertura focada:
  - `tests/test_classificacao_imagens.py` — matriz de categorização (EAN/balança/misto/quantidade/aprendizado/híbrido).
  - `tests/test_processamento_backend.py` — pipeline helpers, `processar_resultado_arquivo`, barcode/unificação/conversa/excel/export edge cases.
- Cobertura existente (29 arquivos, 371 testes): upload, processing, extraction, pipeline, engines, barcode, catálogo, conversa, unificação, relatório, edição, histórico, manutenção, dashboard/stats, AI providers.

## 7. Configuração e deploy

`config/config.json` (gerado): `api{provider, modelo_selecionado, *_api_key}`, `processamento{temperatura 0.1, max_tokens 4000, timeout 60, tamanho_lote 12, max_workers, request_delay, modo_extracao, dias_para_reverificar_peso}`, `interface{...}`. Env sobrescreve em produção. Vercel: `vercel.json` + `app_vercel`/`handler` em `app.py`; variáveis `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` no dashboard.

## 8. Contribuindo

Branch `feature/...`, pytest verde, sem `config.json` no commit, paths via `core/paths.py`, regras de classificação do `AGENTS.md` preservadas.
