"""Testes de regressão dos bugs de reenvio e de coluna interna na unificação.

Contexto (bugs reais, corrigidos):

1. Reenvio processava de novo. A imagem é RECOMPRIMIDA ao ser arquivada
   (services/image_archive.py), então o hash do arquivo guardado difere do
   original. `nome_para_gravar` comparava conteúdo e concluía "arquivo
   diferente" ao reenviar o mesmo lote, criando `IMG-x_2.jpg` — um nome
   inédito que entrava na fila e era analisado (e cobrado) de novo. O
   pipeline identifica "já processado" pelo NOME (log_mestre.txt), então é
   `nomes_processados` que decide.

2. `id_linha` vazava para o relatório unificado. É coluna técnica da tela de
   Histórico (services/relatorio_view.py); ao consolidar um grupo, fixava o
   id de um item arbitrário do grupo e ia parar no Excel gerado.
"""

import os

import pandas as pd
import pytest
from PIL import Image

from autoavaria.services.extraction import nome_para_gravar
from autoavaria.services.execucao_export import _unificar_sem_colunas_internas
from autoavaria.services.unification import (
    unificar_itens_avarias,
    unificar_itens_uso_interno,
)


@pytest.fixture
def pastas_imagem(tmp_path):
    """(pasta_pendentes, pasta_archive) com uma imagem JÁ arquivada.

    O arquivo em `archive` passa por recompressão (como no arquivamento real),
    então seu conteúdo difere do original — que é exatamente o cenário em que
    o dedup por hash falhava.
    """
    pendentes = tmp_path / "imagens_para_analisar"
    archive = tmp_path / "imagens_processadas"
    pendentes.mkdir()
    archive.mkdir()

    original = tmp_path / "original.jpg"
    Image.new("RGB", (2400, 1800), (200, 100, 50)).save(original, "JPEG", quality=95)
    dados_originais = original.read_bytes()

    # "Arquivamento": recomprime (muda o hash) e move para o archive.
    with Image.open(original) as img:
        img.thumbnail((1600, 1600))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(archive / "FOTO.jpg", "JPEG", quality=70, optimize=True)

    return str(pendentes), str(archive), dados_originais


class TestReenvioNaoReprocessa:
    def test_nome_processado_nao_gera_sufixo(self, pastas_imagem):
        """O caso do bug: sem nomes_processados criava _2; com ele, None."""
        pendentes, archive, dados = pastas_imagem

        # Documenta o comportamento que causava o bug (hash mudou na recompressão).
        assert nome_para_gravar([pendentes, archive], "FOTO.jpg", dados) == "FOTO_2.jpg"

        assert (
            nome_para_gravar(
                [pendentes, archive], "FOTO.jpg", dados,
                nomes_processados={"FOTO.jpg"},
            )
            is None
        )

    def test_forcar_permite_reprocessar_de_proposito(self, pastas_imagem):
        pendentes, archive, dados = pastas_imagem
        resultado = nome_para_gravar(
            [pendentes, archive], "FOTO.jpg", dados,
            forcar=True, nomes_processados={"FOTO.jpg"},
        )
        assert resultado == "FOTO_2.jpg"

    def test_nome_inédito_continua_sendo_gravado(self, pastas_imagem):
        """Imagem nova (nome fora do log) não é afetada pela correção."""
        pendentes, archive, dados = pastas_imagem
        assert (
            nome_para_gravar(
                [pendentes, archive], "NOVA.jpg", dados,
                nomes_processados={"FOTO.jpg"},
            )
            == "NOVA.jpg"
        )

    def test_sem_nomes_processados_mantem_comportamento_antigo(self, pastas_imagem):
        """A API segue compatível com quem não passa a lista."""
        pendentes, archive, dados = pastas_imagem
        assert nome_para_gravar([pendentes, archive], "INEDITA.jpg", dados) == "INEDITA.jpg"


class TestSemColunaInternaNaUnificacao:
    def test_avarias_nao_leva_id_linha(self):
        linhas = [
            {"id_linha": 10, "Produto": "TOMATE", "Quantidade": 1, "Peso": "1,334kg"},
            {"id_linha": 11, "Produto": "TOMATE", "Quantidade": 1, "Peso": "1,762kg"},
        ]
        df = _unificar_sem_colunas_internas(linhas, unificar_itens_avarias)
        assert "id_linha" not in df.columns
        assert len(df) == 1  # agrupou as duas linhas
        assert df.iloc[0]["Quantidade Total"] == "3,096 kg"

    def test_uso_interno_nao_leva_id_linha(self):
        linhas = [
            {
                "id_linha": 5, "Produto": "CAFE", "Quantidade": 1,
                "Marca": "UNIAO", "Código de Barras": "7891910030477",
                "Observação da Mensagem": "Nenhuma",
            },
            {
                "id_linha": 6, "Produto": "CAFÉ TORRA MÉDIA", "Quantidade": 1,
                "Marca": "Camil", "Código de Barras": "7891910030477",
                "Observação da Mensagem": "Nenhuma",
            },
        ]
        df = _unificar_sem_colunas_internas(linhas, unificar_itens_uso_interno)
        assert "id_linha" not in df.columns
        assert len(df) == 1  # mesmo código de barras -> uma linha
        assert df.iloc[0]["Quantidade Total"] == "2"

    def test_lista_vazia_devolve_dataframe_vazio(self):
        assert _unificar_sem_colunas_internas([], unificar_itens_avarias).empty
