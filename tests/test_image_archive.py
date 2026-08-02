"""Testes de services/image_archive.py (arquivamento + recompressão de
imagens já processadas)."""

import io

from PIL import Image

from autoavaria.services.image_archive import arquivar_imagem


def _criar_jpeg(caminho, tamanho=(2000, 1200)):
    img = Image.new("RGB", tamanho, color=(200, 50, 50))
    img.save(caminho, "JPEG", quality=95)


def _criar_png(caminho, tamanho=(300, 200)):
    img = Image.new("RGBA", tamanho, color=(10, 200, 10, 255))
    img.save(caminho, "PNG")


class TestArquivarImagem:
    def test_arquivo_origem_inexistente_retorna_false(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        assert arquivar_imagem("nao_existe.jpg", origem, destino) is False
        assert not destino.exists() or not any(destino.iterdir())

    def test_jpeg_e_recomprimido_e_redimensionado_mantendo_nome(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        caminho_origem = origem / "foto.jpg"
        _criar_jpeg(caminho_origem, tamanho=(3000, 2000))
        tamanho_original = caminho_origem.stat().st_size

        assert arquivar_imagem("foto.jpg", origem, destino) is True

        assert not caminho_origem.exists()
        caminho_destino = destino / "foto.jpg"
        assert caminho_destino.exists()
        with Image.open(caminho_destino) as img:
            assert max(img.size) <= 1600
        assert caminho_destino.stat().st_size <= tamanho_original

    def test_png_e_otimizado_sem_trocar_formato_nem_redimensionar(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        caminho_origem = origem / "print.png"
        _criar_png(caminho_origem, tamanho=(300, 200))

        assert arquivar_imagem("print.png", origem, destino) is True

        caminho_destino = destino / "print.png"
        assert caminho_destino.exists()
        assert not caminho_origem.exists()
        with Image.open(caminho_destino) as img:
            assert img.format == "PNG"
            assert img.size == (300, 200)

    def test_imagem_corrompida_cai_para_copia_sem_recompressao(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        caminho_origem = origem / "corrompida.jpg"
        caminho_origem.write_bytes(b"isto nao e uma imagem valida")

        assert arquivar_imagem("corrompida.jpg", origem, destino) is True

        assert not caminho_origem.exists()
        caminho_destino = destino / "corrompida.jpg"
        assert caminho_destino.read_bytes() == b"isto nao e uma imagem valida"

    def test_destino_default_e_archive_folder(self, tmp_path, monkeypatch):
        from autoavaria.services import image_archive

        origem = tmp_path / "origem"
        archive = tmp_path / "imagens_processadas"
        origem.mkdir()
        monkeypatch.setattr(image_archive, "ARCHIVE_FOLDER", archive)

        caminho_origem = origem / "foto.jpg"
        _criar_jpeg(caminho_origem)

        assert arquivar_imagem("foto.jpg", origem) is True
        assert (archive / "foto.jpg").exists()
