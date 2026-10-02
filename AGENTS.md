# AGENTS.md — Instruções para Agentes de IA

> Arquivo de contexto para IAs (e humanos com pressa). Leia antes de modificar o código.

## 1. O que é o projeto

Sistema Flask para registrar avarias de mercadorias a partir de fotos + texto do WhatsApp.
Gera relatório Excel/TXT separando itens em **Avaria**, **Uso Interno** e **Erro**.

Fluxo: `Upload/ZIP → imagens_para_analisar/ + conversa.txt → pipeline (lotes) → SQLite (fonte da verdade) → edição → unificação/exportação (Excel/TXT sob demanda)`.

## 2. Comandos

```bash
python -m venv venv && .\venv\Scripts\activate   # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt              # testes
python app.py                                    # http://localhost:5000
python -m pytest -q                              # 590 testes, ~35s
python -m pytest tests/test_barcode.py -q
python -m pytest tests/test_classificacao_imagens.py tests/test_processamento_backend.py -q
```

`pytest.ini`: `testpaths = tests`. Fixture `tmp_db` (`tests/conftest.py`) isola o SQLite em `tmp_path` — **nunca toque em `database/avariaia.db` nos testes**.

## 3. Mapa do código

```
app.py                          → entrypoint, só create_app()
avariaia/__init__.py      → create_app(): logging, dirs, db.init_db, backfill, migração, catálogo, blueprints
avariaia/core/paths.py    → ÚNICA fonte de paths (PROJECT_ROOT, UPLOAD_FOLDER, ARCHIVE_FOLDER, RESULTADOS_DIR, DATABASE_FILE...)
avariaia/services/
  extraction.py                 → descompactação segura (zip/tar/rar/7z, anti-zip-slip, dedup por SHA256)
  barcode.py                    → leitura local EAN-13 (zxing-cpp+opencv), validação DV, etiqueta balança prefixo 2
  ai.py                         → abstração multi-provedor (Gemini/OpenAI/Claude/OpenRouter)
  ai_extraction.py              → prompt + parse JSON + processar_resultado_arquivo (Avaria/Uso Interno/Erro/Misto)
  extraction_engines.py         → MotorIA / MotorCodigoBarras / MotorHibrido (mesmo contrato de saída)
  conversa.py                   → parser WhatsApp → ContextoImagem(textos, quantidade)
  catalogo.py                   → tradução código→produto, preco_kg interno, aprendizado, revisão, expiração
  extraction_pipeline.py        → orquestração: lotes, ThreadPool, persistência por lote (SÓ no banco), versionamento, reanálise
  mestre.py                     → visão MESTRE a partir do banco: todas as execuções deduplicadas, versão mais recente por linhagem (a fonte do relatório e do export)
  excel_report.py               → geração de xlsx por execução (legado do mestre; o mestre agora é gerado sob demanda do banco)
  export_service.py             → ÚNICO escritor xlsx/txt (detalhado vs compacto)
  unification.py                → funções PURAS de agrupamento (Avarias por nome, Uso Interno por código)
  db.py                         → SQLite: processing_runs, report_items, unified_reports, token_usage, catalogo_*
  reports.py                    → GerenciadorErros (lê/grava erros no BANCO; nome legado)
  report_editing.py / relatorio_view.py / execucao_export.py / campo_migration.py / stats.py / maintenance.py / image_archive.py / app_state.py / config_service.py / optimization.py
avariaia/routes/         → blueprints finos: upload, processing, relatorio, historico, erros, edicao, unificacao, dashboard, manutencao, logs, configuracoes, ai_config
```

## 4. Regras críticas (não quebrar)

1. **Texto > imagem.** `PROMPT_INSTRUCAO` (`ai_extraction.py:24`) e `conversa.py`: a conversa é a fonte da verdade; a imagem é apoio.
2. **EAN sozinho nunca decide categoria.** `_categoria_do_contexto()` (`extraction_engines.py:60`) ou `_categoria_catalogo()` (`extraction_engines.py:86`) precisam resolver; senão o item vira `Erro` com mensagem orientando (`extraction_engines.py:184`). Nunca defaulte para "Uso Interno".
3. **Balança (prefixo `2`) é sempre Avaria.** `interpretar_etiqueta_balanca()` (`barcode.py:109`) → `(PLU=codigo[1:6], total=codigo[6:12]/100)`. Peso = `total / preco_kg` (`barcode.py:122`); sem `preco_kg` o peso é `"N/A"` e o híbrido manda para a IA (`extraction_engines.py:314`).
4. **Quantidade só vem da conversa.** `extrair_quantidade()` (`conversa.py:228`) ignora `kg/g/R$`; default `1`. `_aplicar_quantidade()` (`extraction_engines.py:344`) só preenche o que está vazio.
5. **Peso plausível 0,02–30 kg.** `catalogo.aprender_preco_kg()` (`catalogo.py:199`) rejeita fora da faixa e abre revisão em vez de aprender.
6. **Preço/kg expira.** `esta_desatualizado()` (`catalogo.py:236`, padrão 30 dias): híbrido revalida com IA mesmo resolvido localmente.
7. **EAN-13 exige DV válido.** `ean13_valido()` (`barcode.py:88`). IA com DV quebrado é descartada; histórico com DV inválido não entra no catálogo (`catalogo.py:295`).
8. **SQLite é a fonte da verdade; Excel é export.** O pipeline grava SÓ no banco (`_persistir_lote`); o `.xlsx` é gerado sob demanda a partir de `mestre.py` (rotas de download). Nunca leia o Excel para decidir conteúdo. Ordem: gravar no banco → `registrar_log` → arquivar imagem. Erro fica pendente para reanálise; nunca arquive erro como sucesso.
9. **Reanálise seletiva preserva versão completa.** `reanalisar_execucao(categorias|item_ids)`: só a seleção vai para a IA; o resto é copiado intacto para a nova versão. No mestre (sem execução), `reanalisar_selecao_mestre(imagens|categorias)` substitui só as linhas daquelas imagens (via `db.excluir_itens_por_caminho`). A visão mestre mostra apenas a versão mais recente de cada linhagem (`raiz_execucao_id`).
10. **Checkbox de seleção é a última coluna.** Nas tabelas com reanálise seletiva, a coluna ✓ vem DEPOIS das colunas de dados (nunca antes): os índices `data-column` da ordenação não podem deslocar.
11. **Unificação é pura e tem chaves diferentes.** Avarias agrupa por **nome normalizado** (soma kg ou conta un); Uso Interno agrupa **só por código de barras** (`unification.py:141/245`). Sem código válido → cada linha própria.
12. **Paths só via `core/paths.py`.** Não hardcode `imagens_para_analisar`, `resultados/`, etc. Suporte Vercel (`/tmp`) já tratado lá.
13. **Não commite `config/config.json`.** Contém API keys; usar `config.example.json` + env (`GEMINI_API_KEY`, `OPENAI_API_KEY`, ...).

## 5. Contratos de saída (estáveis)

Motor → `{arquivo: {tipo: Avaria|Uso Interno|Erro|Misto, itens: [{produto, peso, marca, codigo_barras, quantidade, (categoria se Misto)}]}}`.

- Avaria → colunas `[Produto, Quantidade, Peso, Observação, Caminho, Ver]`.
- Uso Interno → `[Produto, Quantidade, Marca, Código de Barras, Observação, Caminho, Ver]`.
- Erro → `[Arquivo, Detalhes, Observação, Caminho, Ver]`.
- `Misto` → split por `item.categoria`; item sem categoria válida → Erro (`ai_extraction.py:178`).

## 6. Como testar mudanças

- Mocke `barcode.ler_imagem` (não dependa de zxing/opencv instalado) — padrão em `test_extraction_engines.py`.
- Use `tmp_db` para qualquer coisa que toque em `catalogo`/`db`.
- Imagens sintéticas: `zxingcpp.create_barcode(...)` (ver `test_barcode.py:12`); pule com `pytest.importorskip` se deps ausentes.
- AI: `MagicMock` provider + patch em `ai_extraction.extrair_dados_de_lote`.
- Rode a suíte completa antes de abrir PR. Alvo: sem regressão nos 590 testes existentes.

## 7. Pitfalls conhecidos

- `test_barcode.py` usa `pytest.importorskip("zxingcpp"/"cv2")` — sem as deps esses testes pulam, não falham.
- `salvar_relatorio_excel()` faz merge incremental + escrita atômica via temp+`os.replace`; teste de falha deve garantir que o mestre antigo não foi apagado.
- `unificar_itens_uso_interno` prefere `Quantidade` da linha e só cai para `extrair_quantidade_de_observacao` em planilhas legadas.
- `extrair_peso_de_valor("500g")` → `0.5`; sem unidade assume `kg`; `"N/A"` → `None`.
- Janela de comentário WhatsApp: 15 min (`JANELA_COMENTARIO_MINUTOS`); sem timestamp, associa.
