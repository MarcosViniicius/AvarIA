"""Regressões do acervo encontradas na migração real.

1. `listar_imagens_pendentes` vazava o NOME FÍSICO (uuid) quando um arquivo
   estava no acervo: o passo de disco comparava o nome físico com os nomes
   originais registrados, não achava interseção e adicionava o arquivo de
   novo. O pipeline passaria a identidade errada (uuid) para o relatório.

2. Referência a cópia `IMG-x_2.jpg` (descartada na migração por ser conteúdo
   idêntico) precisa resolver para o original `IMG-x.jpg` — senão links que
   funcionavam antes ficam quebrados.

3. A rota `/imagem/<nome>` procurava o arquivo pelo nome no disco; com o
   acervo o físico é opaco, então TODA imagem migrada dava 404 (o botão "Ver
   Imagem" parava de funcionar). Precisa resolver pelo acervo.
"""

import os

import pytest
from PIL import Image


@pytest.fixture
def cenario(tmp_path, tmp_db, monkeypatch):
    from autoavaria.services import arquivos
    from autoavaria.services import extraction_pipeline as pipeline
    from autoavaria.services import image_archive

    pendentes = tmp_path / "imagens_para_analisar"
    arquivadas = tmp_path / "imagens_processadas"
    pendentes.mkdir()
    arquivadas.mkdir()

    monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
    monkeypatch.setattr(pipeline, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(pipeline, "ARCHIVE_FOLDER", arquivadas)
    monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "log.txt")
    monkeypatch.setattr(image_archive, "ARCHIVE_FOLDER", arquivadas)

    return {"pendentes": pendentes, "arquivadas": arquivadas,
            "acervo": arquivos, "pipeline": pipeline}


class TestNaoVazaNomeFisico:
    def test_pendente_do_acervo_devolve_nome_original(self, cenario):
        from PIL import Image

        imagem = cenario["pendentes"] / "origem.jpg"
        Image.new("RGB", (4, 4), "red").save(imagem)
        dados = imagem.read_bytes()
        os.remove(imagem)

        registro = cenario["acervo"].registrar("IMG-BONITA.jpg", dados=dados)
        # o físico em disco é opaco...
        assert registro["nome_fisico"] != "IMG-BONITA.jpg"
        assert os.path.isfile(registro["caminho"])

        pendentes = cenario["pipeline"].listar_imagens_pendentes(str(cenario["pendentes"]))
        # ...mas o pipeline só enxerga o nome de negócio.
        assert pendentes == ["IMG-BONITA.jpg"]
        assert registro["nome_fisico"] not in pendentes

    def test_nao_duplica_arquivo_do_acervo(self, cenario):
        imagem = cenario["pendentes"] / "x.jpg"
        Image.new("RGB", (4, 4), "blue").save(imagem)
        dados = imagem.read_bytes()
        os.remove(imagem)
        cenario["acervo"].registrar("IMG-UNICA.jpg", dados=dados)

        pendentes = cenario["pipeline"].listar_imagens_pendentes(str(cenario["pendentes"]))
        assert len(pendentes) == 1  # não aparece 2x (físico + original)


class TestResolveCopiaDescartada:
    def test_copia_resolve_para_original(self, cenario):
        """`IMG-x_2.jpg` (conteúdo idêntico, descartado) cai para `IMG-x.jpg`."""
        imagem = cenario["arquivadas"] / "tmp.jpg"
        Image.new("RGB", (4, 4), "green").save(imagem)
        dados = imagem.read_bytes()
        os.remove(imagem)

        cenario["acervo"].registrar("IMG-x.jpg", dados=dados, pasta=cenario["acervo"].PASTA_ARQUIVADAS)

        # Referência antiga aponta para a cópia que não existe mais.
        referencias = [
            str(cenario["pendentes"] / "IMG-x_2.jpg"),
            str(cenario["pendentes"] / "IMG-x_3.jpg"),
        ]
        for ref in referencias:
            resolvido = cenario["pipeline"]._resolver_caminho_imagem(ref)
            assert resolvido is not None, f"não resolveu {ref}"
            assert os.path.isfile(resolvido)

    def test_nome_sem_sufixo_continua_normal(self, cenario):
        imagem = cenario["arquivadas"] / "tmp2.jpg"
        Image.new("RGB", (4, 4), "black").save(imagem)
        dados = imagem.read_bytes()
        os.remove(imagem)
        cenario["acervo"].registrar("IMG-y.jpg", dados=dados, pasta=cenario["acervo"].PASTA_ARQUIVADAS)

        resolvido = cenario["pipeline"]._resolver_caminho_imagem(
            str(cenario["pendentes"] / "IMG-y.jpg")
        )
        assert resolvido is not None


class TestRotaImagem:
    def test_serve_imagem_do_acervo_pelo_nome_original(self, tmp_path, tmp_db, monkeypatch):
        """Bug real: `/imagem/<nome>` dava 404 em toda imagem migrada, porque
        procurava o nome no disco e o físico é opaco."""
        from autoavaria import create_app
        from autoavaria.services import arquivos
        from autoavaria.routes import relatorio as relatorio_route

        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
        monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
        monkeypatch.setattr(relatorio_route, "DIRETORIO_IMAGENS", pendentes)
        monkeypatch.setattr(relatorio_route, "ARCHIVE_FOLDER", arquivadas)

        imagem = tmp_path / "orig.jpg"
        Image.new("RGB", (8, 8), "red").save(imagem)
        dados = imagem.read_bytes()
        os.remove(imagem)
        # arquivada: o caso do botão "Ver Imagem" no histórico
        arquivos.registrar("IMG-BONITA.jpg", dados=dados, pasta=arquivos.PASTA_ARQUIVADAS)

        app = create_app()
        app.config["TESTING"] = True
        cliente = app.test_client()

        resposta = cliente.get("/imagem/IMG-BONITA.jpg")
        assert resposta.status_code == 200
        assert resposta.data == dados

    def test_nome_inexistente_da_404(self, tmp_path, tmp_db, monkeypatch):
        from autoavaria import create_app
        from autoavaria.services import arquivos
        from autoavaria.routes import relatorio as relatorio_route

        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
        monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
        monkeypatch.setattr(relatorio_route, "DIRETORIO_IMAGENS", pendentes)
        monkeypatch.setattr(relatorio_route, "ARCHIVE_FOLDER", arquivadas)

        app = create_app()
        app.config["TESTING"] = True
        assert app.test_client().get("/imagem/NAO-EXISTE.jpg").status_code == 404
