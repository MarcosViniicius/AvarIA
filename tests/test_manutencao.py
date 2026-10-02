"""Testes de routes/manutencao.py - foco na ação 'reprocessar_tudo'.

Antes, para reprocessar um lote (ex.: testar de novo), o usuário precisava
descobrir sozinho que tinha que limpar "logs" E "imagens" separadamente -
duas ações desencontradas. `reprocessar_tudo` junta as duas, atomicamente,
sem tocar no relatório Excel nem no Histórico.
"""

import pytest

from avariaia import create_app
from avariaia.routes import manutencao as manutencao_route


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def ambiente(app, tmp_path, monkeypatch, tmp_db):
    pasta_imagens = tmp_path / "imagens"
    pasta_imagens.mkdir()
    (pasta_imagens / "IMG-1.jpg").write_bytes(b"foto1")
    (pasta_imagens / "IMG-2.jpg").write_bytes(b"foto2")

    pasta_arquivadas = tmp_path / "arquivadas"
    pasta_arquivadas.mkdir()
    (pasta_arquivadas / "IMG-0.jpg").write_bytes(b"foto ja processada e arquivada")

    log_mestre = tmp_path / "log_mestre.txt"
    log_mestre.write_text("2026-07-24 10:00:00 - Processado: IMG-1.jpg\n", encoding="utf-8")
    log_consumo = tmp_path / "log_consumo.txt"
    log_consumo.write_text("2026-07-24 10:00:00 - Tokens consumidos: 100\n", encoding="utf-8")

    excel = tmp_path / "Relatorio.xlsx"
    excel.write_bytes(b"conteudo do relatorio")  # não deve ser tocado

    monkeypatch.setattr(manutencao_route, "DIRETORIO_IMAGENS", str(pasta_imagens))
    monkeypatch.setattr(manutencao_route, "ARCHIVE_FOLDER", str(pasta_arquivadas))
    monkeypatch.setattr(manutencao_route, "LOG_PROCESSADOS_FILE", str(log_mestre))
    monkeypatch.setattr(manutencao_route, "LOG_CONSUMO_FILE", str(log_consumo))
    monkeypatch.setattr(manutencao_route, "ARQUIVO_SAIDA_EXCEL", str(excel))

    return {
        "imagens": pasta_imagens, "arquivadas": pasta_arquivadas, "log_mestre": log_mestre,
        "log_consumo": log_consumo, "excel": excel,
    }


class TestLimparImagens:
    """`tipo == "imagens"` avisa que os links "Ver Imagem" do Histórico vão
    quebrar - por isso precisa mesmo limpar as duas pastas (pendentes E
    arquivadas), senão a maior parte das imagens (as já arquivadas) ficaria
    intocada e o aviso passaria a ser mentira."""

    def test_apaga_imagens_pendentes_e_arquivadas(self, app, ambiente):
        client = app.test_client()
        resposta = client.post("/limpar_dados", json={"tipo": "imagens"})

        assert resposta.get_json()["success"] is True
        assert list(ambiente["imagens"].iterdir()) == []
        assert list(ambiente["arquivadas"].iterdir()) == []

    def test_nao_toca_no_relatorio_excel(self, app, ambiente):
        client = app.test_client()
        client.post("/limpar_dados", json={"tipo": "imagens"})
        assert ambiente["excel"].exists()
        assert ambiente["excel"].read_bytes() == b"conteudo do relatorio"


class TestReprocessarTudo:
    def test_apaga_imagens_e_logs(self, app, ambiente):
        client = app.test_client()
        resposta = client.post("/limpar_dados", json={"tipo": "reprocessar_tudo"})

        assert resposta.get_json()["success"] is True
        assert list(ambiente["imagens"].iterdir()) == []
        assert not ambiente["log_mestre"].exists()
        assert not ambiente["log_consumo"].exists()

    def test_nao_toca_nas_imagens_ja_arquivadas(self, app, ambiente):
        """reprocessar_tudo promete não apagar o Histórico - imagens já
        arquivadas (que sustentam o "Ver Imagem" de execuções antigas) não
        podem ser tocadas por essa ação, só a pasta de pendentes."""
        client = app.test_client()
        client.post("/limpar_dados", json={"tipo": "reprocessar_tudo"})
        assert [p.name for p in ambiente["arquivadas"].iterdir()] == ["IMG-0.jpg"]

    def test_nao_toca_no_relatorio_excel(self, app, ambiente):
        client = app.test_client()
        client.post("/limpar_dados", json={"tipo": "reprocessar_tudo"})
        assert ambiente["excel"].exists()
        assert ambiente["excel"].read_bytes() == b"conteudo do relatorio"

    def test_mensagem_de_sucesso_e_clara(self, app, ambiente):
        client = app.test_client()
        resposta = client.post("/limpar_dados", json={"tipo": "reprocessar_tudo"})
        mensagem = resposta.get_json()["message"].lower()
        assert "pronto" in mensagem or "zero" in mensagem
