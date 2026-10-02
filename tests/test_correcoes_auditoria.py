"""Regressões da auditoria de bugs (fora do escopo da unificação).

Cobre as correções de:
- segurança: path traversal no download do unificado e no /imagem;
- /processar liberando o flag em saídas antecipadas;
- /api/reanalisar_mestre com `imagens` em formato inválido;
- reanálise seletiva: item sem imagem preservado UMA vez + contadores reais;
- quantidade com unidade começando por "g" ("7 garrafas");
- dedup do mestre com a categoria na chave;
- segredos mascarados (token do invertexto / prefixo da API key);
- upload: extensão preservada em nomes não-ASCII e reenvio após acervo órfão;
- edição que falha no banco responde `success: false`.
"""

from pathlib import Path

import pytest

from avariaia import create_app
from avariaia.services import app_state, db


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setattr(app_state, "processamento_ativo", False)
    app_state.progresso_atual = {}
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# Segurança de caminhos
# ---------------------------------------------------------------------------


class TestSegurancaDeCaminhos:
    def test_download_unificado_rejeita_traversal(self, client):
        # No Windows, `..\..\..\config\config.json` subiria da pasta resultados
        # até a config (API keys). O nome precisa ser rejeitado sem tocar disco.
        resposta = client.get(
            "/download_relatorio_unificado/"
            "Relatorio_Unificado_..%5C..%5C..%5Cconfig%5Cconfig.json"
        )
        assert resposta.status_code == 400

    def test_download_unificado_rejeita_extensao_inesperada(self, client):
        resposta = client.get(
            "/download_relatorio_unificado/Relatorio_Unificado_evil.py"
        )
        assert resposta.status_code == 400

    def test_imagem_rejeita_caminho_fora_das_pastas(self, client):
        resposta = client.get("/imagem/..%5C..%5CWindows%5Cwin.ini")
        assert resposta.status_code == 404

    def test_imagem_rejeita_drive_letter(self, client):
        resposta = client.get("/imagem/C:%5CWindows%5Cwin.ini")
        assert resposta.status_code == 404


# ---------------------------------------------------------------------------
# Processamento não pode ficar preso
# ---------------------------------------------------------------------------


class TestProcessamentoNaoTrava:
    def test_sem_imagens_libera_o_flag(self, client, tmp_path, monkeypatch):
        from avariaia.routes import processing as processing_route

        pasta_vazia = tmp_path / "imagens_vazias"
        pasta_vazia.mkdir()
        monkeypatch.setattr(processing_route, "DIRETORIO_IMAGENS", str(pasta_vazia))
        monkeypatch.setattr(app_state, "processamento_ativo", False)

        resposta = client.post("/processar", json={})

        assert resposta.status_code == 200
        assert resposta.get_json()["success"] is False
        # Antes o flag ficava True para sempre e todo processamento/reanálise
        # seguinte respondia "já em andamento" até reiniciar o servidor.
        assert app_state.processamento_ativo is False

    def test_reanalise_mestre_com_imagens_invalidas_nao_trava(self, client):
        resposta = client.post(
            "/api/reanalisar_mestre",
            json={"imagens": 5, "categorias": ["Avarias"]},
        )

        assert resposta.status_code == 400
        assert resposta.get_json()["success"] is False
        assert app_state.processamento_ativo is False


# ---------------------------------------------------------------------------
# Reanálise seletiva: sem duplicar e com contadores reais
# ---------------------------------------------------------------------------


class TestReanaliseSemDuplicar:
    def test_item_sem_imagem_preservado_uma_vez_e_contado(self, tmp_db, tmp_path, monkeypatch):
        from avariaia.services import extraction_pipeline as pipeline

        run_id = db.iniciar_execucao("processamento", imagens_total=2)
        (tmp_path / "ok.jpg").write_bytes(b"x")  # precisa existir para a reanálise
        db.registrar_itens(run_id, "Avarias", [
            {"Produto": "SEM_FOTO", "Quantidade": 1, "Peso": "N/A", "Caminho da Imagem": None},
            {"Produto": "COM_FOTO", "Quantidade": 1, "Peso": "1kg",
             "Caminho da Imagem": str(tmp_path / "ok.jpg")},
        ])
        db.finalizar_execucao(run_id, "concluido", avarias=2)

        monkeypatch.setattr(pipeline, "carregar_configuracao", lambda: {
            "api": {"provider": "gemini", "gemini_api_key": "x"},
            "processamento": {"request_delay": 0},
        })
        monkeypatch.setattr(
            pipeline, "construir_provedor_de_config",
            lambda cfg: type("P", (), {"nome_provedor": "fake"})(),
        )

        def fake_extrair(lote, provider, mensagens):
            nome = lote[0][0] if isinstance(lote[0], (tuple, list)) else lote[0]
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "COM_FOTO_NOVO", "peso": "2kg"}]}}, 0

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        itens = db.obter_execucao(run_id)["itens"]
        sem_foto = next(i for i in itens if i["produto"] == "SEM_FOTO")
        com_foto = next(i for i in itens if i["produto"] == "COM_FOTO")

        resultado = pipeline.reanalisar_execucao(
            run_id, item_ids=[sem_foto["id"], com_foto["id"]]
        )
        nova = db.obter_execucao(resultado["run_id"])

        avarias = [i["produto"] for i in nova["itens"] if i["categoria"] == "Avarias"]
        # Antes o item sem imagem entrava em `preservados` E em `sem_imagem`,
        # aparecendo duplicado na nova versão.
        assert avarias.count("SEM_FOTO") == 1
        assert sorted(avarias) == ["COM_FOTO_NOVO", "SEM_FOTO"]
        # Contadores do Histórico refletem os itens reais da versão (reanálise
        # + preservados), não só os reanalisados.
        assert nova["avarias"] == 2


# ---------------------------------------------------------------------------
# Quantidade / conversa
# ---------------------------------------------------------------------------


class TestQuantidadeComG:
    @pytest.mark.parametrize("texto,esperado", [
        ("7 garrafas", 7),
        ("3 garrafas de água", 3),
        ("500g", None),      # peso continua sendo ignorado
        ("0,738kg\n7", 7),   # linha de peso não contamina a legenda
        ("3 grupos", None),  # "g" de outra palavra não é grama
    ])
    def test_extrai_quantidade_sem_falso_positivo_de_peso(self, texto, esperado):
        from avariaia.services.conversa import extrair_quantidade

        assert extrair_quantidade(texto) == esperado


# ---------------------------------------------------------------------------
# Dedup do mestre
# ---------------------------------------------------------------------------


class TestMestreDedupPorCategoria:
    def test_mesma_imagem_em_categorias_diferentes_nao_colide(self, tmp_db):
        from avariaia.services import mestre

        run_id = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run_id, "Avarias", [
            {"Produto": "X", "Quantidade": 1, "Peso": None, "Caminho da Imagem": "c.jpg"},
        ])
        db.registrar_itens(run_id, "Uso Interno", [
            {"Produto": "X", "Quantidade": 1, "Código de Barras": None,
             "Caminho da Imagem": "c.jpg"},
        ])
        db.finalizar_execucao(run_id, "concluido", avarias=1, uso_interno=1)

        secoes = mestre.obter_secoes_mestre()

        # Sem o prefixo de categoria na chave, uma das duas sumia.
        assert secoes["Avarias"]["total"] == 1
        assert secoes["Uso Interno"]["total"] == 1


# ---------------------------------------------------------------------------
# Segredos
# ---------------------------------------------------------------------------


class TestSegredosMascarados:
    def test_config_sem_chaves_mascara_token_do_invertexto(self):
        from avariaia.routes.configuracoes import _config_sem_chaves

        saida = _config_sem_chaves({
            "api": {"gemini_api_key": "AIzaSySEGREDO"},
            "invertexto": {"token": "token-secreto", "url": "https://exemplo"},
        })

        assert saida["api"]["gemini_api_key"] == "***"
        assert saida["invertexto"]["token"] == "***"
        assert saida["invertexto"]["url"] == "https://exemplo"

    def test_mensagem_de_config_nao_expoe_prefixo_da_chave(self, monkeypatch):
        from avariaia.services import config_service

        monkeypatch.setattr(config_service, "carregar_configuracao", lambda: {
            "api": {"provider": "gemini", "gemini_api_key": "AIzaSySEGREDO123456"},
            "processamento": {},
        })

        ok, mensagem = config_service.verificar_e_corrigir_configuracao()

        assert ok is True
        assert "AIza" not in mensagem


# ---------------------------------------------------------------------------
# Upload: extensão preservada
# ---------------------------------------------------------------------------


class TestNomeDeUpload:
    @pytest.mark.parametrize("entrada,esperado", [
        ("foto.jpg", "foto.jpg"),
        ("测试.zip", "arquivo.zip"),
        ("relatório final.zip", "relatorio_final.zip"),
        ("a b.JPG", "a_b.jpg"),
    ])
    def test_preserva_extensao_em_nomes_nao_ascii(self, entrada, esperado):
        from avariaia.routes.upload import _nome_original_seguro

        assert _nome_original_seguro(entrada) == esperado


# ---------------------------------------------------------------------------
# Acervo: reenvio após limpeza e registros fantasma
# ---------------------------------------------------------------------------


@pytest.fixture
def pastas_acervo(tmp_path, monkeypatch):
    from avariaia.services import arquivos

    pendentes = tmp_path / "pendentes"
    arquivadas = tmp_path / "arquivadas"
    pendentes.mkdir()
    arquivadas.mkdir()
    monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
    return {"pendentes": pendentes, "arquivadas": arquivadas}


class TestAcervoFantasma:
    def test_reenvio_nao_e_bloqueado_por_registro_orfao(self, pastas_acervo, tmp_db):
        from avariaia.services import arquivos

        primeiro = arquivos.registrar("IMG-1.jpg", dados=b"conteudo")
        assert primeiro is not None
        (pastas_acervo["pendentes"] / primeiro["nome_fisico"]).unlink()

        # Antes: dedup pelo hash recusava o reenvio e o arquivo nunca voltava
        # a existir (nem para processar, nem para o Dashboard).
        segundo = arquivos.registrar("IMG-1.jpg", dados=b"conteudo")

        assert segundo is not None
        assert (pastas_acervo["pendentes"] / segundo["nome_fisico"]).exists()

    def test_agrupamento_por_hash_continua_quando_o_fisico_existe(self, pastas_acervo, tmp_db):
        from avariaia.services import arquivos

        assert arquivos.registrar("IMG-1.jpg", dados=b"conteudo") is not None
        assert arquivos.registrar("IMG-1.jpg", dados=b"conteudo") is None

    def test_limpar_por_pasta_preserva_arquivadas(self, pastas_acervo, tmp_db):
        from avariaia.services import arquivos

        arquivos.registrar("A.jpg", dados=b"a")
        arquivos.registrar("B.jpg", dados=b"b", pasta=arquivos.PASTA_ARQUIVADAS)

        assert arquivos.limpar(arquivos.PASTA_PENDENTES) == 1
        assert [r["nome_original"] for r in arquivos.listar()] == ["B.jpg"]

        assert arquivos.limpar() == 1
        assert arquivos.listar() == []

    def test_limpar_dados_imagens_limpa_o_acervo(self, client, tmp_path, monkeypatch):
        from avariaia.routes import manutencao
        from avariaia.services import arquivos

        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
        monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
        monkeypatch.setattr(manutencao, "DIRETORIO_IMAGENS", str(pendentes))
        monkeypatch.setattr(manutencao, "ARCHIVE_FOLDER", str(arquivadas))

        arquivos.registrar("IMG-1.jpg", dados=b"x")

        resposta = client.post("/limpar_dados", json={"tipo": "imagens"})

        assert resposta.get_json()["success"] is True
        assert arquivos.listar() == []
        assert list(pendentes.iterdir()) == []


# ---------------------------------------------------------------------------
# Edição: falha do banco precisa aparecer
# ---------------------------------------------------------------------------


class TestEdicaoNaoEngoleErro:
    def test_falha_do_banco_responde_success_false(self, client, monkeypatch):
        run_id = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run_id, "Avarias", [
            {"Produto": "TOMATE", "Quantidade": 1, "Peso": "1kg", "Caminho da Imagem": "t.jpg"},
        ])
        db.finalizar_execucao(run_id, "concluido", avarias=1)
        item = db.obter_execucao(run_id)["itens"][0]

        def explodir(*args, **kwargs):
            raise RuntimeError("banco indisponível")

        monkeypatch.setattr(db, "atualizar_itens_campo", explodir)

        resposta = client.post("/salvar_edicao", json={
            "sheet_name": "Avarias",
            "linha_id": item["id"],
            "campo": "Produto",
            "novo_valor": "TOMATE 2",
        })

        dados = resposta.get_json()
        assert dados["success"] is False
        assert "banco indisponível" in dados["message"]


# ---------------------------------------------------------------------------
# Checagens estáticas de frontend (regressões que já ocorreram)
# ---------------------------------------------------------------------------


class TestFrontendSemRegressao:
    def test_editar_dados_sem_onclick_inline_no_botao_salvar(self):
        fonte = Path("avariaia/static/js/editar_dados.js").read_text(encoding="utf-8")
        # O onclick inline coexistia com o handler delegado e disparava dois POSTs.
        assert 'setAttribute("onclick", "salvarNovaLinha()")' not in fonte
        assert 'setAttribute("onclick", "salvarEdicaoCompleta()")' not in fonte
        assert "currentLineId !== null" in fonte  # delegação decide pelo estado

    def test_upload_le_o_campo_certo_de_duplicados(self):
        fonte = Path("avariaia/static/js/pages/upload.js").read_text(encoding="utf-8")
        assert "data.ignorados_duplicados" in fonte
        assert "data.rejeitados" not in fonte

    def test_logs_escapa_antes_do_innerhtml(self):
        fonte = Path("avariaia/static/js/pages/logs.js").read_text(encoding="utf-8")
        assert "escapeHtml(texto)" in fonte
        assert "escapeHtml(timestamp)" in fonte

    def test_relatorio_sem_clones_de_linha(self):
        fonte = Path("avariaia/static/js/relatorio.min.js").read_text(encoding="utf-8")
        # O virtual scroll anterior trocava as linhas por clones, matando os
        # listeners (Editar/Excluir) e escondendo os checkboxes da reanálise.
        assert "cloneNode" not in fonte
        # A paginação localiza o <ul> pelo id padrão da tabela.
        assert 'replace(/-table$/, "-pagination")' in fonte
        assert "function ordenarTabela" in fonte

    def test_relatorio_acoes_botoes_ligados(self):
        fonte = Path("avariaia/static/js/relatorio-acoes.js").read_text(encoding="utf-8")
        assert "exportarTabelaCSV" in fonte
        assert "imprimirTabela" in fonte
        assert "refreshBtn" in fonte
