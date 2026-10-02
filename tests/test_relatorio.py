"""Testes de routes/relatorio.py.

Foco no bug relatado: a aba "Relatório" mostrava o histórico inteiro
acumulado (todas as análises já feitas), em vez de só a última execução.
A tela agora é montada a partir da última execução registrada no banco
(services/db.py), com o Excel mestre completo como fallback só quando ainda
não existe nenhuma execução no banco (ex.: banco recém-criado).
"""

import pandas as pd
import pytest

from avariaia import create_app
from avariaia.routes import relatorio as relatorio_route
from avariaia.services import db


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def ambiente(app, tmp_path, monkeypatch, tmp_db):
    excel = tmp_path / "Relatorio.xlsx"
    imagens = tmp_path / "imagens"
    arquivadas = tmp_path / "arquivadas"
    imagens.mkdir()
    arquivadas.mkdir()

    monkeypatch.setattr(relatorio_route, "ARQUIVO_SAIDA_EXCEL", str(excel))
    monkeypatch.setattr(relatorio_route, "DIRETORIO_IMAGENS", str(imagens))
    monkeypatch.setattr(relatorio_route, "ARCHIVE_FOLDER", str(arquivadas))

    return {"excel": excel, "imagens": imagens, "arquivadas": arquivadas}


def _registrar_execucao(produto: str, quantidade: int = 1) -> int:
    run_id = db.iniciar_execucao("processamento", imagens_total=1)
    db.registrar_itens(
        run_id, "Avarias",
        [{"Produto": produto, "Quantidade": str(quantidade), "Peso": "1kg",
          "Observação da Mensagem": "Nenhuma", "Caminho da Imagem": f"{produto}.jpg"}],
    )
    db.finalizar_execucao(run_id, "concluido", avarias=1)
    return run_id


class TestRelatorioMostraSoAUltimaExecucao:
    def test_sem_execucao_no_banco_cai_para_o_excel_completo(self, app, ambiente):
        df = pd.DataFrame(
            [{"Produto": "BANANA", "Quantidade": 1, "Peso": "1kg",
              "Observação da Mensagem": "Nenhuma", "Caminho da Imagem": "x.jpg", "Ver Imagem": "x.jpg"}]
        )
        with pd.ExcelWriter(ambiente["excel"], engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Avarias", index=False)

        resposta = app.test_client().get("/relatorio")
        assert resposta.status_code == 200
        assert b"BANANA" in resposta.data

    def test_com_execucoes_mostra_so_a_ultima(self, app, ambiente, monkeypatch):
        """Não faz sentido raspar o HTML procurando o nome do produto (a tela
        tem texto de ajuda com nomes de produto de exemplo, ex.: o modal de
        "Unificar Relatório" cita "tomate" como exemplo) - a verificação real
        é sobre os DADOS passados ao template, capturados espiando
        render_template."""
        id_execucao_antiga = _registrar_execucao("PRODUTO_ANTIGO_XYZ")
        id_execucao_nova = _registrar_execucao("PRODUTO_NOVO_XYZ")

        capturado = {}
        render_original = relatorio_route.render_template

        def render_espiao(nome_template, **kwargs):
            capturado.update(kwargs)
            return render_original(nome_template, **kwargs)

        monkeypatch.setattr(relatorio_route, "render_template", render_espiao)

        resposta = app.test_client().get("/relatorio")
        assert resposta.status_code == 200

        produtos = [r["Produto"] for r in capturado["dados"]["Avarias"]["dados"]]
        assert produtos == ["PRODUTO_NOVO_XYZ"]
        assert capturado["execucao"]["id"] == id_execucao_nova
        assert id_execucao_antiga != id_execucao_nova

    def test_coluna_quantidade_aparece_nos_dados(self, app, ambiente, monkeypatch):
        _registrar_execucao("PRODUTO_QTD_XYZ", quantidade=7)

        capturado = {}
        render_original = relatorio_route.render_template

        def render_espiao(nome_template, **kwargs):
            capturado.update(kwargs)
            return render_original(nome_template, **kwargs)

        monkeypatch.setattr(relatorio_route, "render_template", render_espiao)

        resposta = app.test_client().get("/relatorio")
        assert resposta.status_code == 200

        assert "Quantidade" in capturado["dados"]["Avarias"]["colunas"]
        assert capturado["dados"]["Avarias"]["dados"][0]["Quantidade"] == 7

    def test_mostra_nota_de_execucao_com_link_para_historico(self, app, ambiente):
        _registrar_execucao("TOMATE")

        resposta = app.test_client().get("/relatorio")
        corpo = resposta.get_data(as_text=True)
        assert "última execução" in corpo.lower()
        assert "/historico" in corpo


class TestServirImagemChecaAsDuasPastas:
    def test_encontra_imagem_na_pasta_pendente(self, app, ambiente):
        (ambiente["imagens"] / "foto.jpg").write_bytes(b"conteudo jpeg")
        resposta = app.test_client().get("/imagem/foto.jpg")
        assert resposta.status_code == 200

    def test_encontra_imagem_na_pasta_arquivada(self, app, ambiente):
        (ambiente["arquivadas"] / "foto.jpg").write_bytes(b"conteudo jpeg arquivado")
        resposta = app.test_client().get("/imagem/foto.jpg")
        assert resposta.status_code == 200

    def test_404_quando_nao_existe_em_nenhuma_pasta(self, app, ambiente):
        resposta = app.test_client().get("/imagem/nao_existe.jpg")
        assert resposta.status_code == 404
