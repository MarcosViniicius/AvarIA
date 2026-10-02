"""Unificação ESCOPADA à execução exibida na tela de Relatório.

Regressão do bug real: a tela mostra apenas a última execução, mas o botão
"Unificar Relatório" usava a visão mestre (todas as execuções acumuladas) —
o relatório unificado vinha com dados de execuções antigas.

O que este arquivo garante:
- a página de Relatório configura o modal para a execução exibida (runId);
- `/api/opcoes_unificacao?run_id=N` responde pelas seções daquela execução;
- `/historico/execucao/<id>/unificar` respeita secoes/colunas e não mistura
  execuções anteriores;
- o envio ao invertexto usa o mesmo recorte (não publica o relatório inteiro).
"""

import pytest

from autoavaria import create_app
from autoavaria.services import db, execucao_export, invertexto
from autoavaria.services.report_editing import carregar_todas_sheets


@pytest.fixture
def client(tmp_db, monkeypatch):
    from autoavaria.services import app_state

    monkeypatch.setattr(app_state, "processamento_ativo", False)
    app_state.progresso_atual = {}
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def resultados(tmp_path, monkeypatch):
    pasta = tmp_path / "resultados"
    pasta.mkdir()
    monkeypatch.setattr(execucao_export, "RESULTADOS_DIR", pasta)
    return pasta


def _execucao(avarias=None, uso_interno=None, erros=None):
    run_id = db.iniciar_execucao("processamento", imagens_total=1)
    if avarias:
        db.registrar_itens(run_id, "Avarias", avarias)
    if uso_interno:
        db.registrar_itens(run_id, "Uso Interno", uso_interno)
    if erros:
        db.registrar_itens(run_id, "Erros de Análise", erros)
    db.finalizar_execucao(run_id, "concluido", avarias=len(avarias or []))
    return run_id


def _avaria(produto, peso, caminho=None):
    return {
        "Produto": produto,
        "Quantidade": "1",
        "Peso": peso,
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": caminho or f"{produto}.jpg",
    }


def _uso(produto, codigo, quantidade="1"):
    return {
        "Produto": produto,
        "Quantidade": quantidade,
        "Marca": "N/A",
        "Código de Barras": codigo,
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": f"{produto}.jpg",
    }


def _erro(arquivo, detalhe="falha"):
    return {
        "Arquivo": arquivo,
        "Detalhes do Erro": detalhe,
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": f"{arquivo}",
    }


def _gerar(client, run_id, corpo):
    resposta = client.post(f"/historico/execucao/{run_id}/unificar", json=corpo)
    return resposta


class TestPaginaRelatorioEscopada:
    def test_modal_configura_a_execucao_exibida(self, client):
        run_id = _execucao(avarias=[_avaria("TOMATE", "3kg")])

        html = client.get("/relatorio").get_data(as_text=True)

        assert 'escopo: "execucao"' in html
        assert f"runId: {run_id}" in html
        # O bloco de seleção de seções/colunas precisa existir de verdade
        # (antes o include não recebia com_selecao e ele nunca renderizava).
        assert "Personalizar Exportação" in html


class TestOpcoesEscopadas:
    def test_run_id_da_execucao_responde(self, client):
        run_id = _execucao(avarias=[_avaria("TOMATE", "3kg")])

        resposta = client.get(f"/api/opcoes_unificacao?run_id={run_id}")

        assert resposta.status_code == 200
        dados = resposta.get_json()
        assert "Avarias" in dados["secoes"]
        assert "Produto" in dados["colunas_por_secao"]["Avarias"]

    def test_run_id_inexistente_retorna_404(self, client):
        resposta = client.get("/api/opcoes_unificacao?run_id=999999")
        assert resposta.status_code == 404


class TestUnificarEscopoExecucao:
    def test_nao_mistura_execucao_anterior(self, client, resultados):
        _execucao(avarias=[_avaria("PRODUTO_ANTIGO", "1kg")])
        run_novo = _execucao(avarias=[_avaria("PRODUTO_NOVO", "2kg")])

        resposta = _gerar(client, run_novo, {"formato": "xlsx"})
        assert resposta.status_code == 200

        sheets = carregar_todas_sheets(str(resultados / resposta.get_json()["filename"]))
        produtos = list(sheets["Avarias"]["Produto"])
        assert produtos == ["PRODUTO_NOVO"]

    def test_respeita_secoes_e_colunas(self, client, resultados):
        run_id = _execucao(
            avarias=[_avaria("TOMATE", "3kg")],
            uso_interno=[_uso("AGUA SANITARIA", "7896221600159")],
        )

        resposta = _gerar(client, run_id, {
            "formato": "xlsx",
            "secoes": ["Avarias"],
            "colunas": {"Avarias": ["Produto", "Quantidade Total"]},
        })
        assert resposta.status_code == 200

        sheets = carregar_todas_sheets(str(resultados / resposta.get_json()["filename"]))
        assert list(sheets.keys()) == ["Avarias"]
        assert list(sheets["Avarias"].columns) == ["Produto", "Quantidade Total"]
        assert sheets["Avarias"].iloc[0]["Produto"] == "TOMATE"

    def test_selecao_sem_itens_retorna_400(self, client, resultados):
        run_id = _execucao(uso_interno=[_uso("AGUA SANITARIA", "7896221600159")])

        resposta = _gerar(client, run_id, {"formato": "xlsx", "secoes": ["Avarias"]})

        assert resposta.status_code == 400
        assert resposta.get_json()["success"] is False

    def test_erros_entram_no_xlsx_quando_selecionados(self, client, resultados):
        run_id = _execucao(
            avarias=[_avaria("TOMATE", "3kg")],
            erros=[_erro("RUIM.jpg")],
        )

        resposta = _gerar(client, run_id, {
            "formato": "xlsx",
            "secoes": ["Avarias", "Erros de Análise"],
        })
        assert resposta.status_code == 200

        sheets = carregar_todas_sheets(str(resultados / resposta.get_json()["filename"]))
        assert "Erros de Análise" in sheets
        assert list(sheets["Erros de Análise"]["Arquivo"]) == ["RUIM.jpg"]

    def test_txt_nao_inclui_erros_mesmo_selecionados(self, client, resultados):
        run_id = _execucao(
            avarias=[_avaria("TOMATE", "3kg")],
            erros=[_erro("RUIM.jpg")],
        )

        resposta = _gerar(client, run_id, {
            "formato": "txt",
            "secoes": ["Avarias", "Erros de Análise"],
        })
        assert resposta.status_code == 200
        conteudo = resposta.get_json()["contenido"]
        assert "TOMATE" in conteudo
        assert "RUIM.jpg" not in conteudo


class TestInvertextoEscopado:
    def test_envio_respeita_secoes_escolhidas(self, client, monkeypatch):
        run_id = _execucao(
            avarias=[_avaria("TOMATE", "3kg")],
            uso_interno=[_uso("AGUA SANITARIA", "7896221600159")],
        )
        capturado = {}

        def fake_enviar(texto, token=None):
            capturado["texto"] = texto
            return True, "ok"

        monkeypatch.setattr(invertexto, "configurado", lambda: True)
        monkeypatch.setattr(invertexto, "enviar", fake_enviar)

        resposta = client.post(
            f"/historico/execucao/{run_id}/enviar_invertexto",
            json={"secoes": ["Avarias"]},
        )

        assert resposta.status_code == 200
        assert "TOMATE" in capturado["texto"]
        assert "AGUA SANITARIA" not in capturado["texto"]
