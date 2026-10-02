"""Testes do upload de arquivos (routes/upload.py).

Com o acervo (services/arquivos.py), o arquivo físico tem nome ALEATÓRIO e a
identidade é o nome original, guardado no banco. O que estes testes travam:

- o nome original é preservado (é o que a UI, a conversa e o Excel usam);
- reenviar o mesmo CONTEÚDO não duplica (dedup por hash, mesmo que a cópia em
  disco tenha sido recomprimida ao ser arquivada — o bug das 74 imagens
  processadas duas vezes);
- reenviar o mesmo NOME com conteúdo diferente não colide nem sobrescreve;
- `forcar` permite reprocessar de propósito.
"""

import io

import pytest

from avariaia import create_app
from avariaia.routes import upload as upload_route


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app, tmp_path, tmp_path_factory, monkeypatch, tmp_db):
    from avariaia.services import arquivos

    pendentes = tmp_path / "pendentes"
    arquivadas = tmp_path_factory.mktemp("arquivadas")
    pendentes.mkdir(exist_ok=True)

    monkeypatch.setattr(upload_route, "UPLOAD_FOLDER", str(pendentes))
    monkeypatch.setattr(upload_route, "ARCHIVE_FOLDER", str(arquivadas))
    monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)

    return {"client": app.test_client(), "pendentes": pendentes, "arquivos": arquivos}


def _upload(client, conteudo, nome, **extra):
    data = {"files": (io.BytesIO(conteudo), nome), **extra}
    return client.post("/upload_files", data=data, content_type="multipart/form-data")


class TestUploadFilesRota:
    def test_upload_preserva_nome_original(self, client):
        corpo = _upload(client["client"], b"conteudo", "IMG-1.jpg").get_json()
        assert corpo["success"] is True
        assert corpo["files"] == ["IMG-1.jpg"]

        registros = client["arquivos"].buscar_por_nome_original("IMG-1.jpg")
        assert len(registros) == 1
        # o físico em disco é opaco, mas o nome de negócio é preservado
        assert registros[0]["nome_fisico"] != "IMG-1.jpg"

    def test_conteudo_identico_nao_duplica(self, client):
        _upload(client["client"], b"mesma foto", "IMG-1.jpg")
        corpo = _upload(client["client"], b"mesma foto", "IMG-2.jpg").get_json()

        assert corpo["files"] == []
        assert corpo["ignorados_duplicados"] == ["IMG-2.jpg"]
        assert len(client["arquivos"].listar()) == 1

    def test_mesmo_nome_conteudo_diferente_nao_colide(self, client):
        """O bug clássico: mesmo nome criava `_2`. Agora é um físico novo."""
        _upload(client["client"], b"versao 1", "IMG-1.jpg")
        corpo = _upload(client["client"], b"versao 2", "IMG-1.jpg").get_json()

        assert corpo["files"] == ["IMG-1.jpg"]  # nome de negócio é o mesmo
        registros = client["arquivos"].buscar_por_nome_original("IMG-1.jpg")
        assert len(registros) == 2  # duas versões registradas
        assert registros[0]["nome_fisico"] != registros[1]["nome_fisico"]

    def test_reenvio_do_mesmo_lote_nao_entra_na_fila(self, client):
        """Regressão (74 imagens processadas 2x): reenviar não pode criar
        identidade nova. O conteúdo idêntico é ignorado."""
        for nome in ("IMG-1.jpg", "IMG-2.jpg"):
            _upload(client["client"], f"conteudo-{nome}".encode(), nome)

        antes = len(client["arquivos"].listar())
        for nome in ("IMG-1.jpg", "IMG-2.jpg"):
            _upload(client["client"], f"conteudo-{nome}".encode(), nome)
        depois = len(client["arquivos"].listar())

        assert antes == depois == 2


class TestUploadFilesComForcar:
    def test_forcar_registra_mesmo_com_conteudo_identico(self, client):
        _upload(client["client"], b"mesma foto", "IMG-1.jpg")
        corpo = _upload(
            client["client"], b"mesma foto", "IMG-1.jpg",
            forcar_reprocessamento="true",
        ).get_json()

        assert corpo["files"] == ["IMG-1.jpg"]
        assert corpo["ignorados_duplicados"] == []
        assert len(client["arquivos"].buscar_por_nome_original("IMG-1.jpg")) == 2

    def test_sem_forcar_continua_ignorando_duplicados(self, client):
        _upload(client["client"], b"mesma foto", "IMG-1.jpg")
        corpo = _upload(client["client"], b"mesma foto", "IMG-1.jpg").get_json()
        assert corpo["ignorados_duplicados"] == ["IMG-1.jpg"]
