# Reanálise sob demanda com versionamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user force a full reprocessing of resent files, and reanalyze a specific historical execution on demand, keeping every result as a browsable version.

**Architecture:** Add a `forcar` bypass to the existing content-hash dedup used during upload/extraction; add a lightweight version-lineage (`raiz_execucao_id` + `versao`) to `processing_runs`; add a `reanalisar_execucao()` pipeline function that re-runs AI extraction on an execution's already-known image paths, replaces those images' rows in the Excel master (so current totals never double-count), and records the result as a new version linked to the same lineage.

**Tech Stack:** Python 3 / Flask, SQLite (stdlib `sqlite3`), pandas + openpyxl for the Excel master report, pytest for tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-reanalise-versionamento-design.md` — follow it for all behavioral decisions.
- Never change the default (non-forced) upload/extraction behavior — existing dedup protection must keep working exactly as today unless `forcar`/"Forçar reprocessamento" is explicitly set.
- "Reanalisar" only ever available on the latest version of a lineage (linear history, no branching).
- The Excel master (`ARQUIVO_SAIDA_EXCEL`) is the single source of truth for current-state totals — old rows for reanalyzed images must be removed from it, never left duplicated.
- Follow existing code style: Portuguese identifiers/docstrings, comments only where the WHY is non-obvious (this codebase's own convention, visible throughout).
- All new tests go in `tests/`, using the existing `tmp_db` fixture (`tests/conftest.py`) and `monkeypatch` patterns already used in `tests/test_extraction.py`, `tests/test_db.py`, `tests/test_extraction_pipeline.py`, `tests/test_upload.py`.

---

### Task 1: Versionamento no banco (`processing_runs`)

**Files:**
- Modify: `src/autoavaria/services/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.iniciar_execucao(tipo, imagens_total) -> int` (unchanged signature, now also sets `raiz_execucao_id = id` and `versao = 1` on every new row).
- Produces: `db.iniciar_reanalise_de_execucao(raiz_execucao_id: int, imagens_total: int = 0) -> int` — inserts a `tipo='reanalise'` row linked to `raiz_execucao_id`, with `versao = MAX(versao WHERE raiz_execucao_id=...) + 1`.
- Produces: `db.listar_versoes(raiz_execucao_id: int) -> List[Dict[str, Any]]` — all runs of a lineage, ordered by `versao` ascending.
- Consumed by: Task 7 (`extraction_pipeline.reanalisar_execucao`) and Task 8 (`routes/historico.py`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
class TestVersionamento:
    def test_execucao_nova_tem_raiz_propria_e_versao_1(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        execucao = tmp_db.obter_execucao(run_id)
        assert execucao["raiz_execucao_id"] == run_id
        assert execucao["versao"] == 1

    def test_reanalise_herda_raiz_e_incrementa_versao(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        reanalise_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        execucao_reanalise = tmp_db.obter_execucao(reanalise_id)
        assert execucao_reanalise["raiz_execucao_id"] == run_id
        assert execucao_reanalise["versao"] == 2
        assert execucao_reanalise["tipo"] == "reanalise"

    def test_terceira_versao_incrementa_a_partir_da_ultima(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.iniciar_reanalise_de_execucao(run_id)
        terceira_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        assert tmp_db.obter_execucao(terceira_id)["versao"] == 3

    def test_listar_versoes_retorna_em_ordem(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        reanalise_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        versoes = tmp_db.listar_versoes(run_id)
        assert [v["id"] for v in versoes] == [run_id, reanalise_id]
        assert [v["versao"] for v in versoes] == [1, 2]

    def test_execucoes_de_linhagens_diferentes_nao_se_misturam(self, tmp_db):
        run_a = tmp_db.iniciar_execucao("processamento")
        run_b = tmp_db.iniciar_execucao("processamento")
        tmp_db.iniciar_reanalise_de_execucao(run_a)
        assert len(tmp_db.listar_versoes(run_a)) == 2
        assert len(tmp_db.listar_versoes(run_b)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::TestVersionamento -v`
Expected: FAIL — `obter_execucao(...)["raiz_execucao_id"]` raises `KeyError` (column doesn't exist yet) and `iniciar_reanalise_de_execucao` doesn't exist (`AttributeError`).

- [ ] **Step 3: Implement the migration and new functions**

In `src/autoavaria/services/db.py`, add a new migration function right after `_migrar_colunas_report_items` (around line 141):

```python
def _migrar_colunas_processing_runs(conn) -> None:
    """Adiciona o versionamento (linhagem de reanálises) a bancos criados
    antes de existir o botão "Reanalisar" do Histórico."""
    colunas_existentes = {row["name"] for row in conn.execute("PRAGMA table_info(processing_runs)").fetchall()}
    if "raiz_execucao_id" not in colunas_existentes:
        conn.execute("ALTER TABLE processing_runs ADD COLUMN raiz_execucao_id INTEGER")
        # Execuções antigas viram linhagens de um item só (raiz = ela mesma).
        conn.execute("UPDATE processing_runs SET raiz_execucao_id = id WHERE raiz_execucao_id IS NULL")
    if "versao" not in colunas_existentes:
        conn.execute("ALTER TABLE processing_runs ADD COLUMN versao INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_processing_runs_raiz ON processing_runs(raiz_execucao_id)"
    )
```

Call it from `init_db()` (around line 128):

```python
def init_db() -> None:
    """Cria as tabelas do banco (idempotente) e aplica migrações de colunas. Chamado na inicialização do app."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrar_colunas_report_items(conn)
        _migrar_colunas_processing_runs(conn)
```

Update `iniciar_execucao` (around line 148) to self-assign the lineage root:

```python
def iniciar_execucao(tipo: str = "processamento", imagens_total: int = 0) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO processing_runs (tipo, iniciado_em, status, imagens_total)
               VALUES (?, ?, 'em_andamento', ?)""",
            (tipo, _now(), imagens_total),
        )
        run_id = cursor.lastrowid
        # Toda execução nova começa a própria linhagem (versão 1, raiz = si
        # mesma) - reanálises de verdade entram por iniciar_reanalise_de_execucao.
        conn.execute("UPDATE processing_runs SET raiz_execucao_id = ? WHERE id = ?", (run_id, run_id))
        return run_id
```

Add the two new functions right after `obter_execucao` (around line 414):

```python
def iniciar_reanalise_de_execucao(raiz_execucao_id: int, imagens_total: int = 0) -> int:
    """Inicia uma reanálise vinculada à mesma linhagem de `raiz_execucao_id`.

    A versão é sempre a próxima da linhagem inteira (não da execução
    reanalisada especificamente) - garante uma linha do tempo linear mesmo
    que, no futuro, alguém chame isso a partir de uma versão que não seja a
    mais recente (a rota que expõe isso ao usuário já bloqueia esse caso -
    ver routes/historico.py)."""
    with get_connection() as conn:
        maior_versao = conn.execute(
            "SELECT COALESCE(MAX(versao), 0) AS maior FROM processing_runs WHERE raiz_execucao_id = ?",
            (raiz_execucao_id,),
        ).fetchone()["maior"]
        cursor = conn.execute(
            """INSERT INTO processing_runs
               (tipo, iniciado_em, status, imagens_total, raiz_execucao_id, versao)
               VALUES ('reanalise', ?, 'em_andamento', ?, ?, ?)""",
            (_now(), imagens_total, raiz_execucao_id, maior_versao + 1),
        )
        return cursor.lastrowid


def listar_versoes(raiz_execucao_id: int) -> List[Dict[str, Any]]:
    """Todas as execuções de uma linhagem (versões da mesma análise), da mais antiga para a mais nova."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM processing_runs WHERE raiz_execucao_id = ? ORDER BY versao",
            (raiz_execucao_id,),
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all of `TestVersionamento` plus the pre-existing tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/services/db.py tests/test_db.py
git commit -m "feat: add version lineage to processing_runs for on-demand reanalysis"
```

---

### Task 2: `forcar` em `nome_para_gravar` (bypass do dedup por conteúdo)

**Files:**
- Modify: `src/autoavaria/services/extraction.py:41-86`
- Test: `tests/test_extraction.py`

**Interfaces:**
- Produces: `nome_para_gravar(pastas, nome: str, dados: bytes, forcar: bool = False) -> Optional[str]` — with `forcar=True`, never returns `None`; a name+content collision gets a numeric suffix instead of being skipped.
- Consumed by: Task 3 (`ExtratorArquivos`), Task 4 (`/upload_files`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_extraction.py`, inside `class TestNomeParaGravar` (after `test_colisao_com_mesmo_conteudo_nao_duplica`):

```python
    def test_forcar_grava_mesmo_com_conteudo_identico(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"exatamente o mesmo conteudo")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"exatamente o mesmo conteudo", forcar=True) == "foto_2.jpg"

    def test_forcar_sem_colisao_mantem_nome(self, tmp_path):
        assert nome_para_gravar(tmp_path, "foto.jpg", b"conteudo", forcar=True) == "foto.jpg"

    def test_forcar_varias_colisoes_identicas_incrementam_sufixo(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"x")
        (tmp_path / "foto_2.jpg").write_bytes(b"x")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"x", forcar=True) == "foto_3.jpg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestNomeParaGravar -v`
Expected: FAIL with `TypeError: nome_para_gravar() got an unexpected keyword argument 'forcar'`.

- [ ] **Step 3: Implement**

In `src/autoavaria/services/extraction.py`, change the signature and the hash-collision branch (lines 41 and 72-80):

```python
def nome_para_gravar(pastas, nome: str, dados: bytes, forcar: bool = False) -> Optional[str]:
    """... (docstring existente, adicionar um parágrafo:)

    `forcar=True` desativa a checagem de "mesmo conteúdo" - toda colisão de
    nome ganha sufixo, mesmo que o conteúdo já exista. Usado pelo checkbox
    "Forçar reprocessamento" da tela de Upload, para quando o usuário quer
    reanalisar de propósito um lote já enviado antes.
    """
    lista_pastas = [Path(pastas)] if isinstance(pastas, (str, Path)) else [Path(p) for p in pastas]

    base, extensao = os.path.splitext(nome)
    candidato_nome = nome
    contador = 2
    while True:
        colide_com_conteudo_diferente = False
        for pasta in lista_pastas:
            caminho = pasta / candidato_nome
            if not caminho.exists():
                continue
            if not forcar and _hash_arquivo(caminho) == _hash(dados):
                return None
            colide_com_conteudo_diferente = True

        if not colide_com_conteudo_diferente:
            return candidato_nome

        candidato_nome = f"{base}_{contador}{extensao}"
        contador += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — `forcar` defaults to `False` so nothing else changes behavior).

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/services/extraction.py tests/test_extraction.py
git commit -m "feat: add forcar bypass to nome_para_gravar for on-demand reprocessing"
```

---

### Task 3: `forcar` em `ExtratorArquivos` (extração de ZIP/RAR/7Z/TAR)

**Files:**
- Modify: `src/autoavaria/services/extraction.py:89-149` (`_extrair_membro`, `ExtratorArquivos.__init__`, `_extrair_zip`, `_extrair_rar`, `_extrair_7z`, `_extrair_tar_modo`, `_extrair_gz`, `_extrair_bz2`)
- Test: `tests/test_extraction.py`

**Interfaces:**
- Consumes: `nome_para_gravar(pastas, nome, dados, forcar=False)` (Task 2).
- Produces: `ExtratorArquivos(pasta_origem, pasta_destino=None, pasta_arquivo=None, forcar=False)` — new `forcar` constructor param, stored as `self.forcar`.
- Consumed by: Task 4 (`extrair_arquivos_comprimidos`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_extraction.py`, a new class after `TestExtracaoConsideraPastaDeArquivo`:

```python
class TestExtracaoComForcar:
    """`forcar=True` é o que faz reenviar o MESMO .zip de propósito (para
    reanalisar) funcionar - sem isso, o conteúdo idêntico já arquivado faz a
    extração não gravar nada, e o pipeline não acha imagem nova pra processar."""

    def test_reextrair_zip_identico_com_forcar_grava_copia_nova(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "mesma foto"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino), forcar=True)
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)
        # reenvio de propósito, mesmo conteúdo
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "mesma foto"})
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)

        arquivos = sorted(p.name for p in destino.iterdir())
        assert arquivos == ["IMG-1.jpg", "IMG-1_2.jpg"]

    def test_sem_forcar_continua_nao_duplicando(self, tmp_path):
        """Regressão: o comportamento padrão (forcar=False, o default) não pode mudar."""
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "mesma foto"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "mesma foto"})
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)

        assert sorted(p.name for p in destino.iterdir()) == ["IMG-1.jpg"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extraction.py::TestExtracaoComForcar -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'forcar'`.

- [ ] **Step 3: Implement**

In `src/autoavaria/services/extraction.py`:

Change `_extrair_membro` (line 89) to accept and forward `forcar`:

```python
def _extrair_membro(dados_origem, caminho_relativo: str, pasta_destino, pasta_arquivo=None, forcar: bool = False) -> None:
    """... (docstring existente)"""
    caminho_relativo = Path(caminho_relativo)
    pasta_membro = Path(pasta_destino) / caminho_relativo.parent
    pasta_membro.mkdir(parents=True, exist_ok=True)
    with dados_origem as entrada:
        dados = entrada.read()
    pastas_colisao = [pasta_membro, pasta_arquivo] if pasta_arquivo else [pasta_membro]
    nome_final = nome_para_gravar(pastas_colisao, caminho_relativo.name, dados, forcar=forcar)
    if nome_final is None:
        return  # conteúdo idêntico já extraído antes - não duplicar
    with open(pasta_membro / nome_final, "wb") as saida:
        saida.write(dados)
```

In `ExtratorArquivos.__init__` (line 115), add the `forcar` param and store it:

```python
    def __init__(self, pasta_origem="imagens_para_analisar", pasta_destino=None, pasta_arquivo=None, forcar=False):
        """
        ... (docstring existente, adicionar:)
            forcar (bool): Se True, ignora a checagem de conteúdo idêntico -
                toda colisão de nome ganha sufixo numérico (ver
                `nome_para_gravar`). Usado para reprocessar de propósito um
                lote já enviado antes.
        """
        self.pasta_origem = Path(pasta_origem)
        self.pasta_destino = Path(pasta_destino) if pasta_destino else self.pasta_origem
        self.pasta_arquivo = Path(pasta_arquivo) if pasta_arquivo else None
        self.forcar = forcar
```

Update every extraction method to pass `forcar=self.forcar` to `_extrair_membro` — six call sites: `_extrair_zip` (line 172), `_extrair_rar` (line 188), `_extrair_7z` (line 202), `_extrair_tar_modo` (line 229), `_extrair_gz` (line 240), `_extrair_bz2` (line 253). Example for `_extrair_zip`:

```python
    def _extrair_zip(self, arquivo, pasta_destino):
        """Extrai arquivos ZIP, membro a membro (nunca sobrescreve - ver `nome_sem_colisao`)."""
        try:
            with zipfile.ZipFile(arquivo, "r") as zip_ref:
                for info in zip_ref.infolist():
                    if info.is_dir():
                        continue
                    _extrair_membro(zip_ref.open(info), info.filename, pasta_destino, self.pasta_arquivo, forcar=self.forcar)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair ZIP {arquivo}: {e}")
            return False
```

Apply the same `forcar=self.forcar` addition to the `_extrair_membro(...)` calls in `_extrair_rar`, `_extrair_7z`, `_extrair_tar_modo`, `_extrair_gz`, `_extrair_bz2` (same pattern, just appending the keyword argument to the existing call).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS (entire file, including all pre-existing extraction tests unaffected since `forcar` defaults to `False`).

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/services/extraction.py tests/test_extraction.py
git commit -m "feat: thread forcar through ExtratorArquivos for all archive formats"
```

---

### Task 4: "Forçar reprocessamento" nas rotas de upload e processamento

**Files:**
- Modify: `src/autoavaria/routes/upload.py`
- Modify: `src/autoavaria/routes/processing.py:53-107` (`extrair_arquivos_comprimidos`), `:388-441` (`/processar`)
- Test: `tests/test_upload.py`, `tests/test_processing.py`

**Interfaces:**
- Consumes: `nome_para_gravar(..., forcar=False)` (Task 2), `ExtratorArquivos(..., forcar=False)` (Task 3).
- Produces: `/upload_files` now reads a `forcar_reprocessamento` form field (`"true"`/absent). `extrair_arquivos_comprimidos(pasta_imagens, logs_callback=None, forcar=False)`. `/processar` now reads `forcar_reprocessamento` from its JSON body.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_upload.py`, a new class after `TestUploadFilesRota`:

```python
class TestUploadFilesComForcar:
    def test_forcar_grava_mesmo_com_conteudo_identico(self, client, tmp_path):
        (tmp_path / "IMG-1.jpg").write_bytes(b"mesma foto")

        data = {
            "files": (io.BytesIO(b"mesma foto"), "IMG-1.jpg"),
            "forcar_reprocessamento": "true",
        }
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()

        assert corpo["success"] is True
        assert corpo["files"] == ["IMG-1_2.jpg"]
        assert corpo["ignorados_duplicados"] == []

    def test_sem_forcar_continua_ignorando_duplicados(self, client, tmp_path):
        """Regressão: sem marcar o checkbox, nada muda."""
        (tmp_path / "IMG-1.jpg").write_bytes(b"mesma foto")

        data = {"files": (io.BytesIO(b"mesma foto"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()

        assert corpo["files"] == []
        assert corpo["ignorados_duplicados"] == ["IMG-1.jpg"]
```

Add to `tests/test_processing.py` (check the file's existing fixture name/pattern first — mirror it; if it already has an `app`/`client` fixture module-scoped like `test_upload.py`, reuse it):

```python
class TestProcessarComForcar:
    def test_forcar_reprocessamento_e_repassado_para_extracao(self, client, monkeypatch):
        """Não testamos a extração real aqui (já coberta em test_extraction.py) -
        só que o parâmetro do request chega até extrair_arquivos_comprimidos."""
        import autoavaria.routes.processing as processing_route

        chamadas = {}

        def fake_extrair(pasta_imagens, logs_callback=None, forcar=False):
            chamadas["forcar"] = forcar
            return {"arquivos_encontrados": 0, "arquivos_extraidos": 0}

        monkeypatch.setattr(processing_route, "extrair_arquivos_comprimidos", fake_extrair)
        monkeypatch.setattr(processing_route.os.path, "exists", lambda p: True)
        monkeypatch.setattr(processing_route.os, "listdir", lambda p: ["IMG-1.jpg"])

        client.post("/processar", json={"forcar_reprocessamento": True})
        assert chamadas["forcar"] is True
```

*(Se `tests/test_processing.py` não tiver fixture `client` pronta, leia o arquivo primeiro e siga o padrão de fixture que ele já usa — não crie uma segunda convenção.)*

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_upload.py::TestUploadFilesComForcar tests/test_processing.py::TestProcessarComForcar -v`
Expected: FAIL — `forcar_reprocessamento` is silently ignored today (test asserts on behavior that doesn't exist yet: `ignorados_duplicados` still contains `IMG-1.jpg`, and `forcar` is never passed to `extrair_arquivos_comprimidos`).

- [ ] **Step 3: Implement**

In `src/autoavaria/routes/upload.py`, in `upload_files()` (around lines 40-51):

```python
        forcar = request.form.get("forcar_reprocessamento") == "true"

        for file in files:
            if file and allowed_file(file.filename):
                filename_original = secure_filename(file.filename)
                dados = file.read()
                filename = nome_para_gravar([upload_dir, ARCHIVE_FOLDER], filename_original, dados, forcar=forcar)
```

In `src/autoavaria/routes/processing.py`, update `extrair_arquivos_comprimidos` (line 53):

```python
def extrair_arquivos_comprimidos(pasta_imagens, logs_callback=None, forcar=False):
    """
    Extrai arquivos comprimidos da pasta de imagens.

    Args:
        pasta_imagens (str): Caminho para a pasta de imagens
        logs_callback (function): Função callback para adicionar logs
        forcar (bool): Se True, ignora o dedup por conteúdo - toda imagem
            colidindo com uma já existente (mesmo idêntica) ganha um nome
            novo em vez de ser descartada. Usado pelo "Forçar reprocessamento"
            da tela de Upload.

    Returns:
        dict: Resultados da extração
    """
    try:
        extrator = ExtratorArquivos(pasta_origem=pasta_imagens, pasta_arquivo=ARCHIVE_FOLDER, forcar=forcar)
```

And in `/processar` (`iniciar_processamento`, around lines 407-419 and 432-437):

```python
    dados_requisicao = request.get_json(silent=True) or {}
    forcar_reprocessamento = bool(dados_requisicao.get("forcar_reprocessamento", False))

    resultado_extracao = None
    try:
        resultado_extracao = extrair_arquivos_comprimidos(DIRETORIO_IMAGENS, forcar=forcar_reprocessamento)
        if resultado_extracao["arquivos_extraidos"] > 0:
            print(f"✅ Extraídos {resultado_extracao['arquivos_extraidos']} arquivos comprimidos")
    except Exception as e:
        print(f"Aviso: Erro na extração de arquivos: {e}")
```

(Note: `dados_requisicao` is read once now, at the top, instead of again lower down for `modo_extracao` — move the existing `modo_extracao = dados_requisicao.get("modo_extracao")` line up next to it so `request.get_json` isn't called twice.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_upload.py tests/test_processing.py -v`
Expected: PASS (full files, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/routes/upload.py src/autoavaria/routes/processing.py tests/test_upload.py tests/test_processing.py
git commit -m "feat: wire forcar_reprocessamento through /upload_files and /processar"
```

---

### Task 5: Checkbox "Forçar reprocessamento" na tela de Upload

**Files:**
- Modify: `src/autoavaria/templates/upload.html`

**Interfaces:**
- Consumes: `/upload_files` (form field `forcar_reprocessamento`), `/processar` (JSON field `forcar_reprocessamento`) — both from Task 4.

*(No automated test for this task — it's a template/JS-only change with no Python behavior to unit test; verify manually per Step 3 checklist below, consistent with how this codebase already treats other pure-template changes.)*

- [ ] **Step 1: Add the checkbox HTML**

In `src/autoavaria/templates/upload.html`, inside the "Status Atual" card, right before the button row (before line 155, `<div class="mt-3 d-flex gap-2 justify-content-center">`):

```html
        <div class="form-check mt-3">
          <input class="form-check-input" type="checkbox" id="forcarReprocessamentoCheck" />
          <label class="form-check-label" for="forcarReprocessamentoCheck">
            Forçar reprocessamento (ignorar duplicados)
          </label>
          <div class="form-text">
            Marque para reanalisar arquivos idênticos a um envio anterior — por padrão eles são ignorados para não duplicar o relatório.
          </div>
        </div>
```

- [ ] **Step 2: Send the checkbox state with both requests**

In the same file's `<script>` block:

Add the element reference near the other `const` declarations (after line 182, `const processarAgoraBtn = ...`):

```javascript
    const forcarReprocessamentoCheck = document.getElementById("forcarReprocessamentoCheck");
```

In `iniciarProcessamento()` (line 202-206), add the field to the JSON body:

```javascript
      fetch("/processar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ forcar_reprocessamento: forcarReprocessamentoCheck.checked }),
      })
```

In `uploadFiles()` (line 403-406), append it to the `FormData`:

```javascript
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append("files", file);
      });
      if (forcarReprocessamentoCheck.checked) {
        formData.append("forcar_reprocessamento", "true");
      }
```

- [ ] **Step 3: Manually verify in the browser**

Run the app locally, go to `/upload`, upload a file, click "Processar Agora" so it's archived, then re-upload the identical file with the checkbox unchecked (message should say it was ignored as duplicate) and again with it checked (message should say it was saved, likely with a `_2` suffix, and "Processar Agora" should reappear and actually process it).

- [ ] **Step 4: Commit**

```bash
git add src/autoavaria/templates/upload.html
git commit -m "feat: add 'Forçar reprocessamento' checkbox to the Upload page"
```

---

### Task 6: Remover linhas do Excel mestre por caminho de imagem

**Files:**
- Modify: `src/autoavaria/services/report_editing.py`
- Test: `tests/test_report_editing.py`

**Interfaces:**
- Produces: `remover_linhas_por_caminho_imagem(sheets: Dict[str, pd.DataFrame], caminhos: set) -> Dict[str, pd.DataFrame]`.
- Consumed by: Task 7 (`extraction_pipeline.reanalisar_execucao`).

- [ ] **Step 1: Write the failing tests**

Read `tests/test_report_editing.py` first to match its existing fixture/import style, then add:

```python
class TestRemoverLinhasPorCaminhoImagem:
    def test_remove_linhas_das_imagens_informadas(self):
        import pandas as pd

        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {
            "Avarias": pd.DataFrame(
                {"Produto": ["Tomate", "Alface"], "Caminho da Imagem": ["/a/IMG-1.jpg", "/a/IMG-2.jpg"]}
            ),
        }
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert list(resultado["Avarias"]["Produto"]) == ["Alface"]

    def test_sheet_sem_coluna_caminho_imagem_fica_intacta(self):
        import pandas as pd

        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {"Outra": pd.DataFrame({"Coisa": [1, 2]})}
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert list(resultado["Outra"]["Coisa"]) == [1, 2]

    def test_sheet_vazia_fica_intacta(self):
        import pandas as pd

        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {"Avarias": pd.DataFrame(columns=["Produto", "Caminho da Imagem"])}
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert resultado["Avarias"].empty

    def test_nenhum_caminho_correspondente_mantem_todas_as_linhas(self):
        import pandas as pd

        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {"Avarias": pd.DataFrame({"Produto": ["Tomate"], "Caminho da Imagem": ["/a/IMG-9.jpg"]})}
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert list(resultado["Avarias"]["Produto"]) == ["Tomate"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report_editing.py::TestRemoverLinhasPorCaminhoImagem -v`
Expected: FAIL with `ImportError: cannot import name 'remover_linhas_por_caminho_imagem'`.

- [ ] **Step 3: Implement**

Add to `src/autoavaria/services/report_editing.py`, after `salvar_todas_sheets`:

```python
def remover_linhas_por_caminho_imagem(sheets, caminhos):
    """Remove, de todas as planilhas, as linhas cujo 'Caminho da Imagem' está em `caminhos`.

    Usado antes de gravar o resultado de uma reanálise de execução (ver
    services/extraction_pipeline.py:reanalisar_execucao): sem remover as
    linhas antigas dessas mesmas imagens primeiro, a mesma imagem contaria
    duas vezes no relatório mestre (a versão antiga E a nova).
    """
    resultado = {}
    for nome, df in sheets.items():
        if "Caminho da Imagem" in df.columns and not df.empty:
            resultado[nome] = df[~df["Caminho da Imagem"].isin(caminhos)].reset_index(drop=True)
        else:
            resultado[nome] = df
    return resultado
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report_editing.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/services/report_editing.py tests/test_report_editing.py
git commit -m "feat: add remover_linhas_por_caminho_imagem for reanalysis row replacement"
```

---

### Task 7: `reanalisar_execucao()` no pipeline

**Files:**
- Modify: `src/autoavaria/services/extraction_pipeline.py`
- Test: `tests/test_extraction_pipeline.py`

**Interfaces:**
- Consumes: `db.obter_execucao`, `db.iniciar_reanalise_de_execucao`, `db.finalizar_execucao`, `db.registrar_itens`, `db.registrar_consumo_tokens` (Task 1); `report_editing.carregar_todas_sheets`, `salvar_todas_sheets`, `remover_linhas_por_caminho_imagem` (Task 6); `ai_extraction.extrair_dados_de_lote`, `ai_extraction.processar_resultado_arquivo` (existing); `excel_report.salvar_relatorio_excel` (existing).
- Produces: `reanalisar_execucao(run_id: int, arquivo_excel: Optional[str] = None, callback_progresso: Optional[callable] = None) -> Dict[str, Any]` — returns `{"sucesso": bool, "run_id": int, "total_arquivos": int, "avarias": int, "uso_interno": int, "erros": int}` (or `{"sucesso": False, "erro": str, "run_id": int}` on failure).
- Consumed by: Task 8 (`routes/historico.py`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_extraction_pipeline.py`, a new class at the end of the file:

```python
class TestReanalisarExecucao:
    @pytest.fixture
    def execucao_existente(self, tmp_path, monkeypatch, tmp_db):
        """Uma execução já concluída, com 2 imagens já 'arquivadas' (fora da
        pasta de pendentes) - o caso normal de uma execução bem-sucedida."""
        from PIL import Image

        pasta_arquivadas = tmp_path / "arquivadas"
        pasta_arquivadas.mkdir()
        Image.new("RGB", (4, 4), color="red").save(pasta_arquivadas / "IMG-1.jpg")
        Image.new("RGB", (4, 4), color="blue").save(pasta_arquivadas / "IMG-2.jpg")

        excel = tmp_path / "Relatorio.xlsx"
        avarias = [
            {
                "Produto": "TOMATE", "Quantidade": 1, "Peso": "1kg",
                "Observação da Mensagem": "Nenhuma",
                "Caminho da Imagem": str(pasta_arquivadas / "IMG-1.jpg"),
                "Ver Imagem": str(pasta_arquivadas / "IMG-1.jpg"),
            },
            {
                "Produto": "ALFACE", "Quantidade": 1, "Peso": "0.5kg",
                "Observação da Mensagem": "Nenhuma",
                "Caminho da Imagem": str(pasta_arquivadas / "IMG-2.jpg"),
                "Ver Imagem": str(pasta_arquivadas / "IMG-2.jpg"),
            },
        ]
        pipeline.salvar_relatorio_excel(str(excel), avarias, [], [])

        run_id = tmp_db.iniciar_execucao("processamento", imagens_total=2)
        tmp_db.registrar_itens(run_id, "Avarias", avarias)
        tmp_db.finalizar_execucao(run_id, "concluido", avarias=2, uso_interno=0, erros=0)

        monkeypatch.setattr(pipeline, "ARQUIVO_SAIDA_EXCEL", excel)
        monkeypatch.setattr(
            pipeline, "carregar_configuracao",
            lambda: {
                "api": {"provider": "gemini", "gemini_api_key": "fake-key"},
                "processamento": {"request_delay": 0},
            },
        )
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        return {"run_id": run_id, "excel": excel, "arquivadas": pasta_arquivadas}

    def test_cria_nova_versao_vinculada_a_mesma_linhagem(self, execucao_existente):
        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "TOMATE REANALISADO", "peso": "1kg"}]}}, 10

        import os

        pipeline.ai_extraction.extrair_dados_de_lote = fake_extrair
        resultado = pipeline.reanalisar_execucao(execucao_existente["run_id"])

        assert resultado["sucesso"] is True
        nova_versao = pipeline.db.obter_execucao(resultado["run_id"])
        assert nova_versao["raiz_execucao_id"] == execucao_existente["run_id"]
        assert nova_versao["versao"] == 2

    def test_substitui_linhas_antigas_no_excel_sem_duplicar(self, execucao_existente, monkeypatch):
        import os

        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": f"{nome}-REANALISADO", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        pipeline.reanalisar_execucao(execucao_existente["run_id"])

        from autoavaria.services.report_editing import carregar_todas_sheets

        sheets = carregar_todas_sheets(str(execucao_existente["excel"]))
        produtos = list(sheets["Avarias"]["Produto"])
        assert produtos == ["IMG-1.jpg-REANALISADO", "IMG-2.jpg-REANALISADO"]  # 2 linhas, não 4

    def test_imagem_que_sumiu_do_disco_vira_erro_sem_derrubar_o_resto(self, execucao_existente, monkeypatch):
        import os

        (execucao_existente["arquivadas"] / "IMG-1.jpg").unlink()

        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "OK", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        resultado = pipeline.reanalisar_execucao(execucao_existente["run_id"])

        assert resultado["sucesso"] is True
        assert resultado["erros"] == 1
        assert resultado["avarias"] == 1

    def test_reporta_progresso_por_callback(self, execucao_existente, monkeypatch):
        import os

        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "OK", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        chamadas = []
        pipeline.reanalisar_execucao(execucao_existente["run_id"], callback_progresso=lambda info: chamadas.append(info))

        assert len(chamadas) == 2
        assert chamadas[0]["total"] == 2
        assert chamadas[-1]["atual"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction_pipeline.py::TestReanalisarExecucao -v`
Expected: FAIL with `AttributeError: module 'autoavaria.services.extraction_pipeline' has no attribute 'reanalisar_execucao'`.

- [ ] **Step 3: Implement**

In `src/autoavaria/services/extraction_pipeline.py`, add the import for the new Task 6 helper (near the top, alongside the existing `from .report_editing import ...`... — currently there's no such import in this file, add one):

```python
from .report_editing import carregar_todas_sheets, remover_linhas_por_caminho_imagem, salvar_todas_sheets
```

Add the function at the end of the file, after `reanalisar_erros`:

```python
def reanalisar_execucao(
    run_id: int,
    arquivo_excel: Optional[str] = None,
    callback_progresso: Optional[callable] = None,
) -> Dict[str, Any]:
    """Reanalisa todas as imagens de uma execução já concluída, criando uma
    nova versão dela (ver versionamento em services/db.py).

    Diferente de `reanalisar_erros` (que só reprocessa itens marcados como
    erro, sem criar versão nenhuma), esta função reprocessa TODOS os itens
    de uma execução - inclusive os que já deram certo - a pedido explícito
    do usuário (botão "Reanalisar" no Histórico).
    """
    print(f"\n🔄 INICIANDO REANÁLISE DA EXECUÇÃO #{run_id}")
    print("=" * 60)

    arquivo_excel = arquivo_excel or str(ARQUIVO_SAIDA_EXCEL)
    config = carregar_configuracao()
    request_delay = config.get("processamento", {}).get("request_delay", 2.0)

    execucao = db.obter_execucao(run_id)
    if not execucao:
        raise ValueError(f"Execução #{run_id} não encontrada")

    raiz_execucao_id = execucao["raiz_execucao_id"] or execucao["id"]
    itens = [item for item in execucao["itens"] if item.get("caminho_imagem")]

    novo_run_id = db.iniciar_reanalise_de_execucao(raiz_execucao_id, imagens_total=len(itens))

    try:
        if not itens:
            db.finalizar_execucao(novo_run_id, "concluido", mensagem="Nenhuma imagem com caminho registrado para reanalisar")
            return {"sucesso": True, "run_id": novo_run_id, "total_arquivos": 0, "avarias": 0, "uso_interno": 0, "erros": 0}

        provider = construir_provedor_de_config(config)
        print(f"✅ {provider.nome_provedor} configurado para a reanálise")

        # Reaproveita a correlação de mensagem já gravada na execução original
        # em vez de tentar reler um conversa.txt que pode nem existir mais
        # perto de imagens já arquivadas há muito tempo.
        mensagens_por_imagem = {
            os.path.basename(item["caminho_imagem"]): item["observacao_mensagem"]
            for item in itens
            if item.get("observacao_mensagem") and item["observacao_mensagem"] not in ("Nenhuma", "N/A")
        }

        caminhos_originais = {item["caminho_imagem"] for item in itens}
        novas_avarias, novos_usos_internos, novos_erros = [], [], []
        tokens_totais = 0

        for idx, item in enumerate(itens, 1):
            caminho_imagem = item["caminho_imagem"]
            nome_arquivo = os.path.basename(caminho_imagem)

            if callback_progresso:
                callback_progresso({"atual": idx, "total": len(itens), "arquivo": nome_arquivo})

            if not os.path.exists(caminho_imagem):
                novos_erros.append({
                    "Arquivo": nome_arquivo,
                    "Detalhes do Erro": "Arquivo de imagem não encontrado para reanálise",
                    "Observação da Mensagem": mensagens_por_imagem.get(nome_arquivo, "Nenhuma"),
                    "Caminho da Imagem": caminho_imagem,
                    "Ver Imagem": caminho_imagem,
                })
            else:
                try:
                    resultado, tokens = ai_extraction.extrair_dados_de_lote([caminho_imagem], provider, mensagens_por_imagem)
                    tokens_totais += tokens
                    ai_extraction.processar_resultado_arquivo(
                        nome_arquivo, resultado, mensagens_por_imagem, os.path.dirname(caminho_imagem),
                        novas_avarias, novos_usos_internos, novos_erros,
                    )
                except Exception as e:
                    novos_erros.append({
                        "Arquivo": nome_arquivo,
                        "Detalhes do Erro": f"Erro na reanálise: {e}",
                        "Observação da Mensagem": mensagens_por_imagem.get(nome_arquivo, "Nenhuma"),
                        "Caminho da Imagem": caminho_imagem,
                        "Ver Imagem": caminho_imagem,
                    })

            if idx < len(itens):
                time.sleep(request_delay)

        # Só remove as linhas antigas do Excel DEPOIS de ter os novos
        # resultados prontos (nem que seja tudo erro) - uma queda no meio do
        # processo nunca deixa o relatório sem as linhas de uma versão válida.
        sheets_atuais = carregar_todas_sheets(arquivo_excel) if os.path.exists(arquivo_excel) else {}
        sheets_sem_antigas = remover_linhas_por_caminho_imagem(sheets_atuais, caminhos_originais)
        if sheets_sem_antigas:
            salvar_todas_sheets(arquivo_excel, sheets_sem_antigas)

        salvar_relatorio_excel(arquivo_excel, novas_avarias, novos_usos_internos, novos_erros)
        db.registrar_itens(novo_run_id, "Avarias", novas_avarias)
        db.registrar_itens(novo_run_id, "Uso Interno", novos_usos_internos)
        db.registrar_itens(novo_run_id, "Erros de Análise", novos_erros)
        db.registrar_consumo_tokens(novo_run_id, tokens_totais, f"Reanálise de {len(itens)} imagens")
        db.finalizar_execucao(
            novo_run_id, "concluido", len(novas_avarias), len(novos_usos_internos),
            len(novos_erros), tokens_totais,
        )

        print(f"✅ REANÁLISE DA EXECUÇÃO #{run_id} CONCLUÍDA -> nova versão #{novo_run_id}")
        return {
            "sucesso": True, "run_id": novo_run_id, "total_arquivos": len(itens),
            "avarias": len(novas_avarias), "uso_interno": len(novos_usos_internos), "erros": len(novos_erros),
        }

    except Exception as e:
        print(f"\n❌ Erro crítico na reanálise da execução #{run_id}: {e}")
        import traceback

        traceback.print_exc()
        db.finalizar_execucao(novo_run_id, "erro", mensagem=str(e))
        return {"sucesso": False, "erro": str(e), "run_id": novo_run_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction_pipeline.py -v`
Expected: PASS (full file, including all pre-existing pipeline tests).

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/services/extraction_pipeline.py tests/test_extraction_pipeline.py
git commit -m "feat: add reanalisar_execucao to reprocess a whole run as a new version"
```

---

### Task 8: Rota `/historico/execucao/<run_id>/reanalisar`

**Files:**
- Modify: `src/autoavaria/routes/historico.py`
- Test: `tests/test_relatorio.py` or a new `tests/test_historico.py` (check whether a `tests/test_historico.py` already exists; if not, check `tests/test_relatorio.py`'s app/client fixture pattern first and mirror it in a new file — don't invent a third fixture convention)

**Interfaces:**
- Consumes: `reanalisar_execucao` (Task 7), `db_service.listar_versoes`, `db_service.obter_execucao` (Task 1), `app_state.processamento_ativo` / `app_state.progresso_atual` (existing, same module used by `/api/reanalisar_erros` in `routes/erros.py`).
- Produces: `POST /historico/execucao/<run_id>/reanalisar` → `{"success": bool, "message": str}`. Progress is exposed via the pre-existing `GET /status` and `GET /api/progresso_reanalise` endpoints (both just read `app_state.progresso_atual`), so no new polling endpoint is needed.
- Also modifies `GET /historico/execucao/<run_id>` to additionally pass `versoes` (list) and `eh_versao_mais_recente` (bool) to the template — consumed by Task 9.

- [ ] **Step 1: Write the failing tests**

First, run `Read tests/test_relatorio.py` (or check for `tests/test_historico.py`) to copy its exact `app`/`client` fixture setup. Then create/add:

```python
class TestHistoricoReanalisar:
    def test_bloqueia_reanalise_de_versao_que_nao_e_a_mais_recente(self, client, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        tmp_db.iniciar_reanalise_de_execucao(run_id)  # cria a versão 2, mais recente

        resposta = client.post(f"/historico/execucao/{run_id}/reanalisar")
        corpo = resposta.get_json()

        assert corpo["success"] is False
        assert "mais recente" in corpo["message"].lower()

    def test_execucao_inexistente_retorna_404(self, client):
        resposta = client.post("/historico/execucao/9999/reanalisar")
        assert resposta.status_code == 404

    def test_bloqueia_se_ja_ha_processamento_ativo(self, client, tmp_db, monkeypatch):
        from autoavaria.services import app_state

        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        monkeypatch.setattr(app_state, "processamento_ativo", True)

        resposta = client.post(f"/historico/execucao/{run_id}/reanalisar")
        corpo = resposta.get_json()
        assert corpo["success"] is False

    def test_reanalise_da_versao_mais_recente_inicia_com_sucesso(self, client, tmp_db, monkeypatch):
        from autoavaria.services import app_state

        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        monkeypatch.setattr(app_state, "processamento_ativo", False)

        chamadas = {}

        def fake_reanalisar_execucao(rid, callback_progresso=None):
            chamadas["run_id"] = rid
            return {"sucesso": True, "run_id": rid + 100, "total_arquivos": 0, "avarias": 0, "uso_interno": 0, "erros": 0}

        monkeypatch.setattr(
            "autoavaria.services.extraction_pipeline.reanalisar_execucao", fake_reanalisar_execucao
        )

        resposta = client.post(f"/historico/execucao/{run_id}/reanalisar")
        corpo = resposta.get_json()
        assert corpo["success"] is True

        import time

        time.sleep(0.2)  # dá tempo da thread de background rodar
        assert chamadas["run_id"] == run_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_historico.py::TestHistoricoReanalisar -v` (ou o nome de arquivo que você tiver usado)
Expected: FAIL with `404 Not Found` for all of them (route doesn't exist yet).

- [ ] **Step 3: Implement**

In `src/autoavaria/routes/historico.py`, add imports at the top:

```python
import threading

from ..services import app_state
```

Update `historico_execucao` (around line 36-49) to compute and pass version info:

```python
@app.route("/historico/execucao/<int:run_id>")
def historico_execucao(run_id):
    """Mostra o detalhe (itens extraídos) de uma execução específica.

    Os itens são reorganizados no mesmo formato ``{categoria: {colunas, dados,
    total}}`` usado pela página de Relatório, para reaproveitar exatamente a
    mesma exibição (cards de resumo, abas, tabela pesquisável/ordenável e
    visualização de imagem).
    """
    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        abort(404)
    raiz_execucao_id = execucao["raiz_execucao_id"] or execucao["id"]
    versoes = db_service.listar_versoes(raiz_execucao_id)
    eh_versao_mais_recente = not versoes or execucao["versao"] == max(v["versao"] for v in versoes)
    dados = _construir_dados_relatorio(execucao["itens"])
    return render_template(
        "historico_execucao.html",
        execucao=execucao,
        dados=dados,
        versoes=versoes,
        eh_versao_mais_recente=eh_versao_mais_recente,
    )
```

Add the new route after `historico_unificar` (end of file):

```python
@app.route("/historico/execucao/<int:run_id>/reanalisar", methods=["POST"])
def historico_reanalisar(run_id):
    """Reanalisa todas as imagens desta execução, criando uma nova versão."""
    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        abort(404)

    raiz_execucao_id = execucao["raiz_execucao_id"] or execucao["id"]
    versoes = db_service.listar_versoes(raiz_execucao_id)
    versao_mais_recente = max(v["versao"] for v in versoes) if versoes else execucao["versao"]
    if execucao["versao"] != versao_mais_recente:
        return jsonify({"success": False, "message": "Só é possível reanalisar a versão mais recente desta análise"}), 400

    if app_state.processamento_ativo:
        return jsonify({"success": False, "message": "Já existe um processamento em andamento"}), 400

    app_state.processamento_ativo = True
    app_state.progresso_atual = {
        "progresso": 0,
        "status": f"Iniciando reanálise da execução #{run_id}",
        "logs": [f"🔄 Iniciando reanálise da execução #{run_id}"],
    }

    def callback_progresso(info):
        progresso = int((info["atual"] / info["total"]) * 100) if info["total"] else 100
        app_state.progresso_atual["progresso"] = progresso
        app_state.progresso_atual["status"] = f"Reanalisando: {info['arquivo']}"
        app_state.progresso_atual["logs"].append(f"[{info['atual']}/{info['total']}] {info['arquivo']}")

    def executar_reanalise():
        try:
            from ..services.extraction_pipeline import reanalisar_execucao

            resultado = reanalisar_execucao(run_id, callback_progresso=callback_progresso)
            app_state.progresso_atual["progresso"] = 100
            app_state.progresso_atual["status"] = "Reanálise concluída"
            app_state.progresso_atual["resultado"] = resultado
            app_state.progresso_atual["logs"].append(
                f"✅ Reanálise concluída: nova versão #{resultado.get('run_id')}"
            )
        except Exception as e:
            app_state.progresso_atual["status"] = f"Erro na reanálise: {e}"
            app_state.progresso_atual["logs"].append(f"❌ Erro: {e}")
            app_state.progresso_atual["erro"] = str(e)
        finally:
            app_state.processamento_ativo = False

    threading.Thread(target=executar_reanalise, daemon=True).start()
    return jsonify({"success": True, "message": "Reanálise iniciada!"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_historico.py -v` (or whichever file you added the tests to) and then the full suite: `pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/routes/historico.py tests/test_historico.py
git commit -m "feat: add /historico/execucao/<id>/reanalisar route with version guard"
```

---

### Task 9: UI — botão "Reanalisar" e lista de versões

**Files:**
- Modify: `src/autoavaria/templates/historico_execucao.html`

**Interfaces:**
- Consumes: `versoes`, `eh_versao_mais_recente` (Task 8, template context); `POST /historico/execucao/<id>/reanalisar` (Task 8); global `monitorarProgresso()` (already loaded site-wide via `static/js/main.js`, used the same way by `upload.html`'s `iniciarProcessamento()`); `GET /status` (existing, already used by `main.js`).

*(No automated test — pure template/JS. Verify manually per Step 4.)*

- [ ] **Step 1: Add the "Versões desta análise" list**

In `src/autoavaria/templates/historico_execucao.html`, insert right after the header's closing `</div>` and before the `<!-- Resumo dos Dados -->` comment (i.e., right after line 58, before line 60):

```html
  {% if versoes|length > 1 %}
  <div class="col-12 mb-3">
    <div class="card border-0 shadow-sm">
      <div class="card-body py-2">
        <strong class="me-2"><i class="bi bi-clock-history me-1"></i>Versões desta análise:</strong>
        {% for versao in versoes %}
        <a
          href="{{ url_for('historico_execucao', run_id=versao.id) }}"
          class="badge text-decoration-none me-1 {{ 'bg-primary' if versao.id == execucao.id else 'bg-secondary' }}"
        >
          Versão {{ versao.versao }} — {{ versao.iniciado_em }}{% if loop.last %} (mais recente){% endif %}
        </a>
        {% endfor %}
      </div>
    </div>
  </div>
  {% endif %}
```

- [ ] **Step 2: Add the "Reanalisar" button (only on the latest version)**

In the same file, in the header's action button group, right before the "Unificar" button (before line 37):

```html
        {% if eh_versao_mais_recente %}
        <button
          class="btn btn-outline-warning me-2"
          id="btnReanalisar"
          onclick="iniciarReanalise()"
          title="Roda a análise de novo em todas as imagens desta execução, criando uma nova versão"
        >
          <i class="bi bi-arrow-clockwise"></i> Reanalisar
        </button>
        {% endif %}
```

- [ ] **Step 3: Add the JS to trigger and follow the reanalysis**

In the same file's `<script>` block, after the `iniciarUnificacaoExecucao()` function (end of file, before the closing `</script>`):

```javascript
  // ===================== REANÁLISE DA EXECUÇÃO INTEIRA =====================
  function iniciarReanalise() {
    if (
      !confirm(
        "Isso vai rodar a análise de novo em todas as imagens desta execução e criar uma nova versão dos resultados. Continuar?"
      )
    ) {
      return;
    }

    const btn = document.getElementById("btnReanalisar");
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-arrow-clockwise spin me-1"></i>Iniciando...';

    fetch(apiUrl("/reanalisar"), { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          mostrarAlerta("danger", data.message);
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Reanalisar';
          return;
        }
        mostrarAlerta("success", data.message);
        if (typeof monitorarProgresso === "function") monitorarProgresso();
        aguardarConclusaoDaReanalise();
      })
      .catch((err) => {
        mostrarAlerta("danger", "Erro de comunicação: " + err.message);
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Reanalisar';
      });
  }

  function aguardarConclusaoDaReanalise() {
    const intervalo = setInterval(() => {
      fetch("/status")
        .then((r) => r.json())
        .then((data) => {
          const terminou = data.progresso >= 100 || (data.status || "").includes("Erro");
          if (!terminou) return;
          clearInterval(intervalo);
          const novoRunId = data.resultado && data.resultado.run_id;
          setTimeout(() => {
            window.location.href = novoRunId ? `/historico/execucao/${novoRunId}` : window.location.href;
          }, 1500);
        })
        .catch(() => clearInterval(intervalo));
    }, 2000);
  }
```

- [ ] **Step 4: Manually verify in the browser**

Run the app, open a completed execution's page under `/historico/execucao/<id>`, confirm:
- The "Reanalisar" button appears (this is the only/latest version).
- Clicking it, confirming the prompt, shows the shared progress modal and, on completion, redirects to the new version's page.
- The new page shows a "Versões desta análise" bar with both versions, and the "Reanalisar" button now only appears on the newest one — visiting the old version's URL directly shows the version bar but no "Reanalisar" button.

- [ ] **Step 5: Commit**

```bash
git add src/autoavaria/templates/historico_execucao.html
git commit -m "feat: add Reanalisar button and version list to execution detail page"
```

---

## Self-Review Notes

- **Spec coverage:** "Forçar reprocessamento" checkbox → Tasks 2–5. "Reanalisar" button reusing archived images → Tasks 6–9. Versioning (`raiz_execucao_id`/`versao`, listable, linear-only) → Tasks 1, 8, 9. Excel-as-current-state (no double counting) → Task 6/7. Error handling (image missing, AI failure mid-batch) → Task 7 tests. All covered.
- **Placeholder scan:** no TBD/TODO left; every step has concrete code.
- **Type consistency:** `reanalisar_execucao` returns a dict with `run_id`/`avarias`/`uso_interno`/`erros`/`sucesso` keys consistently referenced in Task 8's route and its tests. `nome_para_gravar(..., forcar=False)` signature is consistent across Tasks 2–4. `ExtratorArquivos(..., forcar=False)` consistent across Tasks 3–4.
- **Out of scope (separate specs, per the design doc):** Configurações tab audit; Upload tab supported-format banner. Not part of this plan.
