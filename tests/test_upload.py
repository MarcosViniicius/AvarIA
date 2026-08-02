"""Testes do upload de arquivos (routes/upload.py).

Foco no bug relatado: reenviar um arquivo com o mesmo nome de um já
existente sobrescrevia o antigo silenciosamente. Se o antigo já tivesse
sido processado, o pipeline continuava achando (pelo nome) que o conteúdo
novo também já estava processado, e o reenvio nunca era analisado de novo.
"""

import io
from pathlib import Path

import pytest

from autoavaria import create_app
from autoavaria.routes import upload as upload_route


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app, tmp_path, tmp_path_factory, monkeypatch):
    # UPLOAD_FOLDER é lido do módulo a cada chamada da rota, então o
    # monkeypatch funciona mesmo com o app já criado (module-scoped) -
    # evita recriar a aplicação inteira (init_db, popular catálogo etc.)
    # a cada teste, que é o que deixava essa suíte lenta.
    monkeypatch.setattr(upload_route, "UPLOAD_FOLDER", str(tmp_path))
    # Pasta de arquivo separada de tmp_path (que os testes já usam como
    # conteúdo de UPLOAD_FOLDER) - senão apareceria como entrada extra em
    # qualquer `tmp_path.iterdir()`.
    monkeypatch.setattr(upload_route, "ARCHIVE_FOLDER", str(tmp_path_factory.mktemp("arquivadas")))
    return app.test_client()


class TestUploadFilesRota:
    def test_upload_simples_mantem_nome_original(self, client, tmp_path):
        data = {"files": (io.BytesIO(b"conteudo"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()
        assert corpo["success"] is True
        assert corpo["files"] == ["IMG-1.jpg"]
        assert corpo["renomeados"] == []
        assert (tmp_path / "IMG-1.jpg").read_bytes() == b"conteudo"

    def test_upload_com_nome_repetido_nao_sobrescreve(self, client, tmp_path):
        (tmp_path / "IMG-1.jpg").write_bytes(b"foto original ja processada")

        data = {"files": (io.BytesIO(b"foto nova, mesmo nome"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()

        assert corpo["success"] is True
        assert corpo["files"] == ["IMG-1_2.jpg"]
        assert len(corpo["renomeados"]) == 1
        assert corpo["renomeados"][0] == {"original": "IMG-1.jpg", "salvo_como": "IMG-1_2.jpg"}

        # o arquivo original não foi tocado
        assert (tmp_path / "IMG-1.jpg").read_bytes() == b"foto original ja processada"
        # o novo entrou com outro nome, preservando os dois
        assert (tmp_path / "IMG-1_2.jpg").read_bytes() == b"foto nova, mesmo nome"

    def test_mensagem_avisa_sobre_renomeio(self, client, tmp_path):
        (tmp_path / "IMG-1.jpg").write_bytes(b"x")
        data = {"files": (io.BytesIO(b"y"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        assert "sufixo" in resposta.get_json()["message"].lower()

    def test_upload_com_conteudo_identico_nao_duplica(self, client, tmp_path):
        """Regressão: reenviar o mesmo lote pra testar de novo estava criando
        cópias idênticas renomeadas, que o pipeline tratava como imagens
        novas e duplicava no relatório (80 imagens reconhecidas como 160)."""
        (tmp_path / "IMG-1.jpg").write_bytes(b"mesma foto")

        data = {"files": (io.BytesIO(b"mesma foto"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()

        assert corpo["success"] is True
        assert corpo["files"] == []
        assert corpo["ignorados_duplicados"] == ["IMG-1.jpg"]
        assert sorted(p.name for p in tmp_path.iterdir()) == ["IMG-1.jpg"]  # nada duplicado

    def test_upload_colidindo_com_nome_ja_arquivado_ganha_sufixo(self, client, tmp_path):
        """A imagem já foi processada e arquivada (saiu de UPLOAD_FOLDER, ver
        services/image_archive.py) - reenviar uma imagem DIFERENTE com o
        mesmo nome precisa ganhar sufixo, não ser salva por cima do nome já
        usado (senão o pipeline ignoraria essa imagem nova como "já
        processada", já que o nome está no log)."""
        pasta_arquivadas = Path(upload_route.ARCHIVE_FOLDER)
        (pasta_arquivadas / "IMG-1.jpg").write_bytes(b"foto ja processada e arquivada")

        data = {"files": (io.BytesIO(b"foto diferente, nome coincide"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()

        assert corpo["success"] is True
        assert corpo["files"] == ["IMG-1_2.jpg"]
        assert not (tmp_path / "IMG-1.jpg").exists()
        assert (tmp_path / "IMG-1_2.jpg").read_bytes() == b"foto diferente, nome coincide"

    def test_upload_com_conteudo_identico_ao_ja_arquivado_nao_duplica(self, client, tmp_path):
        pasta_arquivadas = Path(upload_route.ARCHIVE_FOLDER)
        (pasta_arquivadas / "IMG-1.jpg").write_bytes(b"mesma foto, ja arquivada")

        data = {"files": (io.BytesIO(b"mesma foto, ja arquivada"), "IMG-1.jpg")}
        resposta = client.post("/upload_files", data=data, content_type="multipart/form-data")
        corpo = resposta.get_json()

        assert corpo["success"] is True
        assert corpo["files"] == []
        assert corpo["ignorados_duplicados"] == ["IMG-1.jpg"]
        assert list(tmp_path.iterdir()) == []  # nada salvo em UPLOAD_FOLDER
