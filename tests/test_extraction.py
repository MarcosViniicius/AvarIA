"""Testes de services/extraction.py (extração de arquivos compactados).

Dois bugs relacionados, mesma causa raiz (reprocessar o mesmo lote não
contava como "novo processamento"):

1. A extração usava `ZipFile.extractall()`, que sobrescreve silenciosamente
   arquivos já extraídos - reenviar o mesmo .zip nunca virava trabalho novo,
   porque o pipeline decide "já processado" pelo nome do arquivo.
2. Ao corrigir (1) com renomeio automático por sufixo, sobrou um efeito
   colateral: reenviar o MESMO lote pra testar de novo passou a criar cópias
   idênticas byte-a-byte (mesmo conteúdo, nome com sufixo) - cada cópia era
   tratada como imagem nova e duplicava a linha no relatório. A correção
   final compara o CONTEÚDO na colisão: nome igual + conteúdo igual = mesmo
   arquivo, não duplica; nome igual + conteúdo diferente = renomeia com
   sufixo, preservando os dois.
"""

import tarfile
import zipfile

import pytest

from avariaia.services.extraction import ExtratorArquivos, nome_para_gravar


class TestNomeParaGravar:
    def test_nome_livre_e_mantido(self, tmp_path):
        assert nome_para_gravar(tmp_path, "foto.jpg", b"conteudo") == "foto.jpg"

    def test_colisao_com_conteudo_diferente_ganha_sufixo(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"conteudo antigo")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"conteudo novo") == "foto_2.jpg"

    def test_colisao_com_mesmo_conteudo_nao_duplica(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"exatamente o mesmo conteudo")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"exatamente o mesmo conteudo") is None

    def test_forcar_grava_mesmo_com_conteudo_identico(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"exatamente o mesmo conteudo")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"exatamente o mesmo conteudo", forcar=True) == "foto_2.jpg"

    def test_forcar_sem_colisao_mantem_nome(self, tmp_path):
        assert nome_para_gravar(tmp_path, "foto.jpg", b"conteudo", forcar=True) == "foto.jpg"

    def test_forcar_varias_colisoes_identicas_incrementam_sufixo(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"x")
        (tmp_path / "foto_2.jpg").write_bytes(b"x")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"x", forcar=True) == "foto_3.jpg"

    def test_varias_colisoes_com_conteudo_diferente_incrementam_o_sufixo(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"1")
        (tmp_path / "foto_2.jpg").write_bytes(b"2")
        (tmp_path / "foto_3.jpg").write_bytes(b"3")
        assert nome_para_gravar(tmp_path, "foto.jpg", b"4 - conteudo novo") == "foto_4.jpg"

    def test_conteudo_igual_a_uma_copia_ja_renomeada_tambem_nao_duplica(self, tmp_path):
        (tmp_path / "foto.jpg").write_bytes(b"original")
        (tmp_path / "foto_2.jpg").write_bytes(b"reenvio de teste")
        # terceiro reenvio, mesmo conteudo do segundo (_2) - não deve virar foto_3.jpg
        assert nome_para_gravar(tmp_path, "foto.jpg", b"reenvio de teste") is None

    def test_preserva_extensao(self, tmp_path):
        (tmp_path / "relatorio.png").write_bytes(b"x")
        assert nome_para_gravar(tmp_path, "relatorio.png", b"y") == "relatorio_2.png"

    def test_aceita_string_como_pasta(self, tmp_path):
        assert nome_para_gravar(str(tmp_path), "foto.jpg", b"conteudo") == "foto.jpg"


class TestNomeParaGravarVariasPastas:
    """Quando existe uma pasta de arquivamento separada (imagens já
    processadas, ver services/image_archive.py), a checagem de colisão
    precisa considerar as duas pastas - sem isso, reenviar uma imagem
    DIFERENTE com o nome de uma já arquivada seria salva sem sufixo e,
    como o nome já está no log de processados, seria ignorada como "já
    processada" sem nunca ser analisada."""

    def test_sem_colisao_em_nenhuma_pasta_mantem_nome(self, tmp_path):
        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        assert nome_para_gravar([pendentes, arquivadas], "foto.jpg", b"conteudo") == "foto.jpg"

    def test_colisao_so_na_pasta_de_arquivo_ganha_sufixo(self, tmp_path):
        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        (arquivadas / "foto.jpg").write_bytes(b"ja processada e arquivada")

        assert nome_para_gravar([pendentes, arquivadas], "foto.jpg", b"imagem diferente") == "foto_2.jpg"

    def test_mesmo_conteudo_so_na_pasta_de_arquivo_nao_duplica(self, tmp_path):
        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        (arquivadas / "foto.jpg").write_bytes(b"reenvio do mesmo lote")

        assert nome_para_gravar([pendentes, arquivadas], "foto.jpg", b"reenvio do mesmo lote") is None

    def test_colisao_na_pasta_pendente_tambem_verifica_arquivo_no_proximo_sufixo(self, tmp_path):
        pendentes = tmp_path / "pendentes"
        arquivadas = tmp_path / "arquivadas"
        pendentes.mkdir()
        arquivadas.mkdir()
        (pendentes / "foto.jpg").write_bytes(b"pendente atual")
        (arquivadas / "foto_2.jpg").write_bytes(b"ja arquivada com sufixo")

        assert nome_para_gravar([pendentes, arquivadas], "foto.jpg", b"imagem nova") == "foto_3.jpg"


def _criar_zip(caminho, arquivos: dict) -> None:
    with zipfile.ZipFile(caminho, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)


def _criar_tar(caminho, arquivos: dict) -> None:
    import io

    with tarfile.open(caminho, "w") as t:
        for nome, conteudo in arquivos.items():
            dados = conteudo.encode("utf-8")
            info = tarfile.TarInfo(name=nome)
            info.size = len(dados)
            t.addfile(info, io.BytesIO(dados))


class TestExtracaoZipNaoSobrescreve:
    """O caso real do bug: reenviar (reextrair) o mesmo .zip duas vezes."""

    def test_extracao_simples_grava_os_arquivos(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "foto1", "conversa.txt": "ola"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        assert extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False) is True
        assert (destino / "IMG-1.jpg").read_text() == "foto1"
        assert (destino / "conversa.txt").read_text() == "ola"

    def test_reextrair_o_mesmo_zip_nao_sobrescreve_e_conta_como_novo(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()

        # Simula: já processado uma vez, o arquivo já está na pasta de destino.
        (destino / "IMG-1.jpg").write_text("foto original ja processada")

        # Reenvio do mesmo lote (mesmo nome de arquivo dentro do zip).
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "foto reenviada para reprocessar"})
        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)

        # O original não foi tocado...
        assert (destino / "IMG-1.jpg").read_text() == "foto original ja processada"
        # ...e o reenvio ganhou um nome novo, que o pipeline vai tratar como pendente.
        assert (destino / "IMG-1_2.jpg").read_text() == "foto reenviada para reprocessar"

    def test_reextrair_o_zip_identico_nao_duplica(self, tmp_path):
        """Regressão: reenviar o MESMO lote (mesmo .zip, mesmo conteúdo) pra
        testar de novo estava criando cópias idênticas renomeadas (IMG-1.jpg,
        IMG-1_2.jpg, ...) que o pipeline tratava como imagens novas -
        dobrando a contagem (80 -> 160) e duplicando linhas no relatório."""
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "mesma foto", "conversa.txt": "7"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)

        # reenvio do MESMO zip (conteúdo idêntico) - simula o usuário testando de novo
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "mesma foto", "conversa.txt": "7"})
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)

        arquivos = sorted(p.name for p in destino.iterdir())
        assert arquivos == ["IMG-1.jpg", "conversa.txt"]  # nada duplicado

    def test_zip_com_subpastas_preserva_estrutura_relativa(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "lote.zip", {"fotos/IMG-1.jpg": "conteudo"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)
        assert (destino / "fotos" / "IMG-1.jpg").read_text() == "conteudo"

    @pytest.mark.parametrize("nome_membro", ["../fora.txt", "nested/../../fora.txt", r"..\fora.txt", r"C:\fora.txt"])
    def test_zip_nao_pode_gravar_fora_da_pasta_destino(self, tmp_path, nome_membro):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "malicioso.zip", {nome_membro: "nao gravar"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        resultado = extrator.extrair_arquivo(origem / "malicioso.zip", criar_subpasta=False)

        assert resultado is False
        assert not (tmp_path / "fora.txt").exists()
        assert list(destino.iterdir()) == []


class TestExtracaoConsideraPastaDeArquivo:
    """ExtratorArquivos(pasta_arquivo=...) - a pasta de imagens já arquivadas
    também entra na checagem de colisão, não só a pasta de destino."""

    def test_nome_ja_arquivado_com_conteudo_diferente_ganha_sufixo(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        arquivadas = tmp_path / "arquivadas"
        origem.mkdir()
        destino.mkdir()
        arquivadas.mkdir()
        (arquivadas / "IMG-1.jpg").write_text("imagem ja processada e arquivada")

        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "imagem nova, nome coincide"})
        extrator = ExtratorArquivos(
            pasta_origem=str(origem), pasta_destino=str(destino), pasta_arquivo=str(arquivadas)
        )
        extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False)

        assert not (destino / "IMG-1.jpg").exists()
        assert (destino / "IMG-1_2.jpg").read_text() == "imagem nova, nome coincide"

    def test_sem_pasta_arquivo_comportamento_e_identico_ao_anterior(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        _criar_zip(origem / "lote.zip", {"IMG-1.jpg": "conteudo"})

        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        assert extrator.extrair_arquivo(origem / "lote.zip", criar_subpasta=False) is True
        assert (destino / "IMG-1.jpg").read_text() == "conteudo"


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


class TestExtracaoTarNaoSobrescreve:
    def test_reextrair_o_mesmo_tar_nao_sobrescreve(self, tmp_path):
        origem = tmp_path / "origem"
        destino = tmp_path / "destino"
        origem.mkdir()
        destino.mkdir()
        (destino / "IMG-1.jpg").write_text("original")

        _criar_tar(origem / "lote.tar", {"IMG-1.jpg": "reenviado"})
        extrator = ExtratorArquivos(pasta_origem=str(origem), pasta_destino=str(destino))
        assert extrator.extrair_arquivo(origem / "lote.tar", criar_subpasta=False) is True

        assert (destino / "IMG-1.jpg").read_text() == "original"
        assert (destino / "IMG-1_2.jpg").read_text() == "reenviado"


class TestExtrairTodosRespeitaRemoverOriginais:
    """Regressão: extrair_todos() apagava o arquivo compactado incondicionalmente
    (e só o último de vários), ignorando o parâmetro remover_originais=False -
    contradizendo o próprio comentário de quem chama isso em produção
    ('Manter originais por segurança')."""

    def test_nao_apaga_originais_quando_remover_originais_e_falso(self, tmp_path):
        origem = tmp_path / "origem"
        origem.mkdir()
        _criar_zip(origem / "a.zip", {"IMG-1.jpg": "x"})
        _criar_zip(origem / "b.zip", {"IMG-2.jpg": "y"})

        extrator = ExtratorArquivos(pasta_origem=str(origem))
        extrator.extrair_todos(criar_subpastas=False, remover_originais=False)

        assert (origem / "a.zip").exists()
        assert (origem / "b.zip").exists()

    def test_apaga_todos_os_originais_quando_remover_originais_e_verdadeiro(self, tmp_path):
        origem = tmp_path / "origem"
        origem.mkdir()
        _criar_zip(origem / "a.zip", {"IMG-1.jpg": "x"})
        _criar_zip(origem / "b.zip", {"IMG-2.jpg": "y"})

        extrator = ExtratorArquivos(pasta_origem=str(origem))
        extrator.extrair_todos(criar_subpastas=False, remover_originais=True)

        assert not (origem / "a.zip").exists()
        assert not (origem / "b.zip").exists()
