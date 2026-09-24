"""Testes do acervo de arquivos (services/arquivos.py).

Cobre o que motivou o modelo híbrido:
- nome físico aleatório => reenviar o mesmo nome NUNCA colide nem cria sufixo;
- dedup por hash do conteúdo ORIGINAL => reenviar o mesmo conteúdo não duplica,
  mesmo que a cópia em disco tenha sido recomprimida (hash diferente);
- mover de pasta (pendentes -> arquivadas) preserva o vínculo (é o id, não o
  caminho);
- nome original é preservado para exibição.
"""

import os

import pytest


@pytest.fixture
def acervo(tmp_db, tmp_path, monkeypatch):
    """Isola banco + pastas. Devolve o módulo services.arquivos."""
    from autoavaria.services import arquivos

    pendentes = tmp_path / "imagens_para_analisar"
    arquivadas = tmp_path / "imagens_processadas"
    monkeypatch.setattr(arquivos, "UPLOAD_FOLDER", pendentes)
    monkeypatch.setattr(arquivos, "ARCHIVE_FOLDER", arquivadas)
    return arquivos


class TestRegistroEDedup:
    def test_registra_e_preserva_nome_original(self, acervo):
        registro = acervo.registrar("IMG-0001.jpg", dados=b"conteudo-1")
        assert registro is not None
        assert registro["nome_original"] == "IMG-0001.jpg"
        # o físico é aleatório e não tem o nome original
        assert registro["nome_fisico"] != "IMG-0001.jpg"
        assert registro["nome_fisico"].endswith(".jpg")
        assert os.path.isfile(registro["caminho"])

    def test_mesmo_conteudo_nao_duplica(self, acervo):
        primeiro = acervo.registrar("FOTO.jpg", dados=b"abc")
        segundo = acervo.registrar("OUTRO-NOME.jpg", dados=b"abc")
        assert primeiro is not None
        assert segundo is None  # mesmo hash => dedup
        assert len(acervo.listar()) == 1

    def test_reenvio_do_mesmo_nome_com_conteudo_novo_nao_colide(self, acervo):
        """O bug original: nome repetido criava `_2`. Agora gera físico próprio."""
        a = acervo.registrar("IMG-x.jpg", dados=b"versao-1")
        b = acervo.registrar("IMG-x.jpg", dados=b"versao-2")
        assert a is not None and b is not None
        assert a["nome_fisico"] != b["nome_fisico"]
        assert a["nome_original"] == b["nome_original"] == "IMG-x.jpg"
        assert len(acervo.buscar_por_nome_original("IMG-x.jpg")) == 2

    def test_conteudo_recomprimido_nao_engana_o_dedup(self, acervo):
        """Simula o caso real: o arquivo em disco é recomprimido (hash muda),
        mas o hash registrado é o do conteúdo original."""
        original = b"bytes-originais-da-foto"
        registro = acervo.registrar("FOTO.jpg", dados=original)
        assert registro["hash_sha256"] == acervo.hash_bytes(original)

        # Alguém reescreve o arquivo físico (recompressão) - o metadado não muda.
        with open(registro["caminho"], "wb") as f:
            f.write(b"bytes-recomprimidos-diferentes")

        # Reenviar o ORIGINAL ainda é reconhecido como já existente.
        assert acervo.registrar("FOTO.jpg", dados=original) is None


class TestMoverEntrePastas:
    def test_mover_preserva_id_e_nome_fisico(self, acervo):
        registro = acervo.registrar("IMG.jpg", dados=b"x")
        caminho_antes = registro["caminho"]
        assert os.path.isfile(caminho_antes)

        assert acervo.mover(registro["id"], acervo.PASTA_ARQUIVADAS) is True

        atualizado = acervo.obter(registro["id"])
        assert atualizado["pasta"] == acervo.PASTA_ARQUIVADAS
        assert atualizado["nome_fisico"] == registro["nome_fisico"]  # vínculo intacto
        assert atualizado["nome_original"] == "IMG.jpg"
        assert not os.path.exists(caminho_antes)
        assert os.path.isfile(atualizado["caminho"])

    def test_mover_pasta_invalida_falha(self, acervo):
        registro = acervo.registrar("IMG.jpg", dados=b"y")
        with pytest.raises(ValueError):
            acervo.mover(registro["id"], "pasta-inexistente")


class TestLeituraDeDisco:
    def test_registrar_a_partir_de_arquivo_existente(self, acervo, tmp_path):
        origem = tmp_path / "na-pasta.jpg"
        origem.write_bytes(b"conteudo-no-disco")
        registro = acervo.registrar("foto.jpg", caminho_origem=origem)
        assert registro is not None
        assert os.path.isfile(registro["caminho"])

    def test_remover_apaga_fisico_e_metadado(self, acervo):
        registro = acervo.registrar("IMG.jpg", dados=b"z")
        assert acervo.remover(registro["id"]) is True
        assert acervo.obter(registro["id"]) is None
        assert not os.path.exists(registro["caminho"])
