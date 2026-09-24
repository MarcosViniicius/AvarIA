"""Reanálise seletiva: um tipo, vários itens ou todos.

Cobre `reanalisar_execucao(..., categorias, item_ids)` (nova versão com
cópia dos preservados), `reanalisar_selecao_mestre` (Excel mestre) e a rota
POST /api/reanalisar_mestre. Os casos base (tudo, sem filtro) continuam em
test_extraction_pipeline.py e test_historico.py.
"""

import os

import pytest

from autoavaria.services import extraction_pipeline as pipeline


class _ProviderFalso:
    nome_provedor = "fake"


def _fake_config():
    return {
        "api": {"provider": "gemini", "gemini_api_key": "fake-key"},
        "processamento": {"request_delay": 0},
    }


@pytest.fixture
def execucao_mista(tmp_path, monkeypatch, tmp_db):
    """Execução com 1 avaria + 1 erro, imagens presentes no disco."""
    from PIL import Image

    pasta = tmp_path / "arq"
    pasta.mkdir()
    Image.new("RGB", (4, 4), color="red").save(pasta / "BOA.jpg")
    Image.new("RGB", (4, 4), color="blue").save(pasta / "RUIM.jpg")

    excel = tmp_path / "Relatorio.xlsx"
    avarias = [{
        "Produto": "TOMATE", "Quantidade": 1, "Peso": "1kg",
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": str(pasta / "BOA.jpg"),
        "Ver Imagem": str(pasta / "BOA.jpg"),
    }]
    erros = [{
        "Arquivo": "RUIM.jpg", "Detalhes do Erro": "Falha na API",
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": str(pasta / "RUIM.jpg"),
        "Ver Imagem": str(pasta / "RUIM.jpg"),
    }]
    pipeline.salvar_relatorio_excel(str(excel), avarias, [], erros)

    run_id = tmp_db.iniciar_execucao("processamento", imagens_total=2)
    tmp_db.registrar_itens(run_id, "Avarias", avarias)
    tmp_db.registrar_itens(run_id, "Erros de Análise", erros)
    tmp_db.finalizar_execucao(run_id, "concluido", avarias=1, uso_interno=0, erros=1)

    monkeypatch.setattr(pipeline, "ARQUIVO_SAIDA_EXCEL", excel)
    monkeypatch.setattr(pipeline, "carregar_configuracao", _fake_config)
    monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

    def fake_extrair(lote, provider, mensagens):
        nome = os.path.basename(lote[0])
        return {nome: {"tipo": "Avaria", "itens": [{"produto": nome + "-NOVO", "peso": "2kg"}]}}, 5

    monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
    return {"run_id": run_id, "excel": excel, "pasta": pasta}


class TestValidacaoFiltros:
    def test_categorias_none_significa_tudo(self):
        assert pipeline._validar_categorias(None) is None

    def test_categorias_validas(self):
        assert pipeline._validar_categorias(["Avarias", "Erros de Análise"]) == ["Avarias", "Erros de Análise"]

    @pytest.mark.parametrize("valor", [[], ["Inexistente"], ["Avarias", "X"], "Avarias"])
    def test_categorias_invalidas(self, valor):
        with pytest.raises(ValueError):
            pipeline._validar_categorias(valor)

    def test_item_db_para_linha_por_categoria(self):
        item = {"produto": "P", "quantidade": 3, "peso": "1kg", "marca": "M",
                "codigo_barras": "123", "detalhes": "D",
                "observacao_mensagem": "O", "caminho_imagem": "C"}
        assert pipeline._item_db_para_linha("Avarias", item)["Produto"] == "P"
        assert pipeline._item_db_para_linha("Uso Interno", item)["Código de Barras"] == "123"
        assert pipeline._item_db_para_linha("Erros de Análise", item)["Arquivo"] == "P"


class TestReanalisarExecucaoSeletiva:
    def test_so_erros_preserva_avaria_na_nova_versao(self, execucao_mista):
        res = pipeline.reanalisar_execucao(execucao_mista["run_id"], categorias=["Erros de Análise"])
        assert res["sucesso"] is True
        assert res["selecionados"] == 1 and res["preservados"] == 1

        nova = pipeline.db.obter_execucao(res["run_id"])
        cats = sorted(i["categoria"] for i in nova["itens"])
        assert cats == ["Avarias", "Avarias"]  # 1 reanalisada + 1 copiada
        produtos = sorted(i["produto"] for i in nova["itens"])
        assert produtos == ["RUIM.jpg-NOVO", "TOMATE"]

    def test_item_ids_seleciona_um(self, execucao_mista, tmp_db):
        execucao = tmp_db.obter_execucao(execucao_mista["run_id"])
        alvo = next(i for i in execucao["itens"] if i["categoria"] == "Erros de Análise")
        res = pipeline.reanalisar_execucao(execucao_mista["run_id"], item_ids=[alvo["id"]])
        assert res["sucesso"] is True
        assert res["selecionados"] == 1 and res["preservados"] == 1

    def test_item_ids_tem_precedencia_sobre_categorias(self, execucao_mista, tmp_db):
        execucao = tmp_db.obter_execucao(execucao_mista["run_id"])
        alvo = next(i for i in execucao["itens"] if i["categoria"] == "Avarias")
        res = pipeline.reanalisar_execucao(
            execucao_mista["run_id"], categorias=["Erros de Análise"], item_ids=[alvo["id"]])
        nova = pipeline.db.obter_execucao(res["run_id"])
        produtos = sorted(i["produto"] for i in nova["itens"])
        assert "BOA.jpg-NOVO" in produtos  # reanalisou a avaria, não o erro

    def test_excel_troca_so_linha_selecionada(self, execucao_mista):
        from autoavaria.services.report_editing import carregar_todas_sheets

        pipeline.reanalisar_execucao(execucao_mista["run_id"], categorias=["Erros de Análise"])
        sheets = carregar_todas_sheets(str(execucao_mista["excel"]))
        assert list(sheets["Avarias"]["Produto"]) == ["TOMATE", "RUIM.jpg-NOVO"]
        erros_sheet = sheets.get("Erros de Análise")
        assert erros_sheet is None or erros_sheet.empty  # linha de erro antiga saiu

    def test_categoria_invalida_levanta(self, execucao_mista):
        with pytest.raises(ValueError):
            pipeline.reanalisar_execucao(execucao_mista["run_id"], categorias=["X"])

    def test_item_de_outra_execucao_levanta(self, execucao_mista):
        with pytest.raises(ValueError):
            pipeline.reanalisar_execucao(execucao_mista["run_id"], item_ids=[999999])

    def test_lista_vazia_levanta(self, execucao_mista):
        with pytest.raises(ValueError):
            pipeline.reanalisar_execucao(execucao_mista["run_id"], item_ids=[])
        with pytest.raises(ValueError):
            pipeline.reanalisar_execucao(execucao_mista["run_id"], categorias=[])


class TestReanalisarSelecaoMestre:
    def test_por_imagens(self, execucao_mista, tmp_path, monkeypatch):
        res = pipeline.reanalisar_selecao_mestre(
            imagens=["RUIM.jpg"], diretorio_imagens=str(execucao_mista["pasta"]),
            arquivo_excel=str(execucao_mista["excel"]))
        assert res["sucesso"] is True
        assert res["total_arquivos"] == 1 and res["corrigidos"] == 1

    def test_por_categoria_deriva_imagens_do_excel(self, execucao_mista):
        res = pipeline.reanalisar_selecao_mestre(
            categorias=["Erros de Análise"], diretorio_imagens=str(execucao_mista["pasta"]),
            arquivo_excel=str(execucao_mista["excel"]))
        assert res["sucesso"] is True
        assert res["total_arquivos"] == 1

    def test_sem_selecao_levanta(self, execucao_mista):
        with pytest.raises(ValueError):
            pipeline.reanalisar_selecao_mestre(
                diretorio_imagens=str(execucao_mista["pasta"]),
                arquivo_excel=str(execucao_mista["excel"]))

    def test_imagem_inexistente_conta_erro_sem_quebrar(self, execucao_mista):
        res = pipeline.reanalisar_selecao_mestre(
            imagens=["FANTASMA.jpg"], diretorio_imagens=str(execucao_mista["pasta"]),
            arquivo_excel=str(execucao_mista["excel"]))
        assert res["sucesso"] is True
        assert res["ainda_com_erro"] == 1 and res["corrigidos"] == 0


class TestRotaReanalisarMestre:
    @pytest.fixture
    def client(self, tmp_db, monkeypatch):
        import sys
        from pathlib import Path
        # app isolado sem tocar no DB real: tmp_db já redirecionou
        from autoavaria import create_app
        from autoavaria.services import app_state
        monkeypatch.setattr(app_state, "processamento_ativo", False)
        app_state.progresso_atual = {}
        return create_app().test_client()

    def test_sem_selecao_retorna_400(self, client):
        r = client.post("/api/reanalisar_mestre", json={})
        assert r.status_code == 400
        assert r.get_json()["success"] is False

    def test_categoria_invalida_retorna_400(self, client):
        r = client.post("/api/reanalisar_mestre", json={"categorias": ["X"]})
        assert r.status_code == 400

    def test_inicia_com_sucesso(self, client, monkeypatch):
        import time
        from autoavaria.services import app_state

        def fake(imagens=None, categorias=None, **kw):
            return {"sucesso": True, "total_arquivos": 1, "corrigidos": 1, "ainda_com_erro": 0}

        monkeypatch.setattr(
            "autoavaria.services.extraction_pipeline.reanalisar_selecao_mestre", fake)
        r = client.post("/api/reanalisar_mestre", json={"imagens": ["A.jpg"]})
        assert r.get_json()["success"] is True
        time.sleep(0.3)
        assert app_state.processamento_ativo is False
