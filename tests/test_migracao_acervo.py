"""Testes da migração do acervo (services/migracao_acervo.py)."""

import os

import pytest
from PIL import Image


@pytest.fixture
def cenario(tmp_path, tmp_db, monkeypatch):
    """Pastas de pendentes/arquivadas isoladas + log de processados falso."""
    from autoavaria.services import arquivos, migracao_acervo

    pendentes = tmp_path / "imagens_para_analisar"
    arquivadas = tmp_path / "imagens_processadas"
    pendentes.mkdir()
    arquivadas.mkdir()

    monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
    monkeypatch.setattr(migracao_acervo, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(migracao_acervo, "ARCHIVE_FOLDER", arquivadas)

    # Duas imagens pendentes e uma já processada (deve ir para 'arquivadas').
    Image.new("RGB", (8, 8), "red").save(pendentes / "IMG-1.jpg")
    Image.new("RGB", (8, 8), "green").save(pendentes / "IMG-2.jpg")
    Image.new("RGB", (8, 8), "blue").save(arquivadas / "IMG-3.jpg")

    monkeypatch.setattr(migracao_acervo, "_log_processados", lambda: {"IMG-3.jpg"})

    return {
        "pendentes": pendentes,
        "arquivadas": arquivadas,
        "acervo": arquivos,
        "migracao": migracao_acervo,
    }


class TestMigracao:
    def test_dry_run_nao_altera_nada(self, cenario):
        resultado = cenario["migracao"].migrar(aplicar=False)
        assert resultado["total_migrados"] == 3
        # Nada foi movido nem registrado.
        assert (cenario["pendentes"] / "IMG-1.jpg").exists()
        assert (cenario["arquivadas"] / "IMG-3.jpg").exists()
        assert cenario["acervo"].listar() == []

    def test_migra_preserva_nome_original_e_move_processadas(self, cenario):
        resultado = cenario["migracao"].migrar()
        assert resultado["total_migrados"] == 3
        assert not resultado["erros"]

        registros = {r["nome_original"]: r for r in cenario["acervo"].listar()}
        assert set(registros) == {"IMG-1.jpg", "IMG-2.jpg", "IMG-3.jpg"}

        # A que já estava no log vai para 'arquivadas'; as outras ficam pendentes.
        assert registros["IMG-1.jpg"]["pasta"] == cenario["acervo"].PASTA_PENDENTES
        assert registros["IMG-2.jpg"]["pasta"] == cenario["acervo"].PASTA_PENDENTES
        assert registros["IMG-3.jpg"]["pasta"] == cenario["acervo"].PASTA_ARQUIVADAS

        # Nome físico é opaco e o vínculo é pelo nome original.
        for registro in registros.values():
            assert registro["nome_fisico"] != registro["nome_original"]
            assert os.path.isfile(registro["caminho"])

        # Os arquivos antigos saíram das pastas originais.
        assert not (cenario["pendentes"] / "IMG-1.jpg").exists()
        assert not (cenario["arquivadas"] / "IMG-3.jpg").exists()

    def test_idempotente(self, cenario):
        cenario["migracao"].migrar()
        antes = len(cenario["acervo"].listar())
        segundo = cenario["migracao"].migrar()
        depois = len(cenario["acervo"].listar())

        assert antes == depois == 3
        assert segundo["total_migrados"] == 0
        assert segundo["total_pulados"] == 3

    def test_imagens_continuam_abriveis_apos_migrar(self, cenario):
        """A resolução por nome original deve achar a imagem migrada."""
        from autoavaria.services import extraction_pipeline as pipeline

        cenario["migracao"].migrar()
        registro = cenario["acervo"].buscar_por_nome_original("IMG-1.jpg")[0]

        # _resolver_caminho_imagem precisa resolver pelo acervo.
        caminho = pipeline._resolver_caminho_imagem(str(cenario["pendentes"] / "IMG-1.jpg"))
        assert caminho is not None
        assert os.path.basename(caminho) == registro["nome_fisico"]
