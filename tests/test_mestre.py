"""Testes da visão mestre (services/mestre.py): a fonte da verdade do relatório.

O Excel mestre virou export sob demanda; quem define o que aparece no relatório
e no download é esta visão, montada do banco e deduplicada. Estes testes fixam
as regras de dedup e o comportamento de versionamento (reanálise).
"""

import pytest

from avariaia.services import db, mestre


def _item(produto, peso="1kg", categoria="Avarias", caminho="a.jpg",
          codigo=None, detalhes=None, observacao="Nenhuma"):
    return {
        "Produto": produto,
        "Quantidade": 1,
        "Peso": peso,
        "Marca": "N/A",
        "Código de Barras": codigo,
        "Detalhes do Erro": detalhes,
        "Observação da Mensagem": observacao,
        "Caminho da Imagem": caminho,
        "Ver Imagem": caminho,
    }


def _criar_run(itens_por_categoria, tipo="processamento"):
    run = db.iniciar_execucao(tipo, imagens_total=len(itens_por_categoria))
    for categoria, itens in itens_por_categoria.items():
        db.registrar_itens(run, categoria, itens)
    db.finalizar_execucao(run, "concluido")
    return run


class TestDeduplicacao:
    def test_mesmo_item_em_duas_execucoes_vira_uma_linha(self, tmp_db):
        _criar_run({"Avarias": [_item("TANGERINA", "1,856kg", caminho="f.jpg")]})
        _criar_run({"Avarias": [_item("TANGERINA", "1,856kg", caminho="f.jpg")]})

        secoes = mestre.obter_secoes_mestre()
        assert secoes["Avarias"]["total"] == 1

    def test_peso_ponto_e_virgula_sao_o_mesmo(self, tmp_db):
        _criar_run({"Avarias": [_item("TOMATE", "1.856kg", caminho="f.jpg")]})
        _criar_run({"Avarias": [_item("TOMATE", "1,856kg", caminho="f.jpg")]})

        assert mestre.obter_secoes_mestre()["Avarias"]["total"] == 1

    def test_produtos_diferentes_na_mesma_foto_nao_se_juntam(self, tmp_db):
        _criar_run({"Avarias": [
            _item("ALFACE", "1kg", caminho="f.jpg"),
            _item("COENTRO", "0,5kg", caminho="f.jpg"),
        ]})
        assert mestre.obter_secoes_mestre()["Avarias"]["total"] == 2

    def test_uso_interno_dedup_por_produto_codigo_imagem(self, tmp_db):
        # Mesmo produto/código/imagem em 2 execuções -> 1 linha. Peso é ignorado
        # (item de estoque não tem peso).
        _criar_run({"Uso Interno": [_item("SACO", categoria="Uso Interno", codigo="789", caminho="f.jpg")]})
        _criar_run({"Uso Interno": [_item("SACO", categoria="Uso Interno", codigo="789", caminho="f.jpg")]})
        assert mestre.obter_secoes_mestre()["Uso Interno"]["total"] == 1

    def test_erros_dedup_por_detalhe_imagem(self, tmp_db):
        _criar_run({"Erros de Análise": [
            _item("x.jpg", categoria="Erros de Análise", detalhes="Falha na API", caminho="x.jpg")
        ]})
        _criar_run({"Erros de Análise": [
            _item("x.jpg", categoria="Erros de Análise", detalhes="Falha na API", caminho="x.jpg")
        ]})
        assert mestre.obter_secoes_mestre()["Erros de Análise"]["total"] == 1

    def test_a_versao_mais_recente_vence(self, tmp_db):
        """Entre duplicatas, vale a linha da execução mais nova."""
        _criar_run({"Avarias": [_item("TOMATE", "1kg", caminho="f.jpg", observacao="antiga")]})
        _criar_run({"Avarias": [_item("TOMATE", "1kg", caminho="f.jpg", observacao="nova")]})

        linhas = mestre.obter_secoes_mestre()["Avarias"]["dados"]
        assert len(linhas) == 1
        assert linhas[0]["Observação da Mensagem"] == "nova"


class TestVersionamento:
    def test_reanalise_nao_mostra_versao_antiga(self, tmp_db):
        run_orig = _criar_run({"Avarias": [_item("TOMATE", "1kg", caminho="f.jpg")]})

        # Nova versão da MESMA linhagem (como faz reanalisar_execucao).
        from avariaia.services import extraction_pipeline  # noqa: F401 (garante import cedo)
        novo = db.iniciar_reanalise_de_execucao(run_orig, imagens_total=1)
        db.registrar_itens(novo, "Avarias", [_item("TOMATE CORRIGIDO", "1kg", caminho="f.jpg")])
        db.finalizar_execucao(novo, "concluido", avarias=1)

        linhas = mestre.obter_secoes_mestre()["Avarias"]["dados"]
        assert len(linhas) == 1
        assert linhas[0]["Produto"] == "TOMATE CORRIGIDO"


class TestContagemEFormato:
    def test_contar_por_categoria_bate_com_as_secoes(self, tmp_db):
        _criar_run({
            "Avarias": [_item("TOMATE", caminho="a.jpg")],
            "Uso Interno": [_item("SACO", categoria="Uso Interno", codigo="1", caminho="b.jpg")],
        })
        secoes = mestre.obter_secoes_mestre()
        contagem = mestre.contar_por_categoria()
        for categoria, info in secoes.items():
            assert contagem[categoria] == info["total"]

    def test_linha_tem_id_linha(self, tmp_db):
        _criar_run({"Avarias": [_item("TOMATE", caminho="a.jpg")]})
        linha = mestre.obter_secoes_mestre()["Avarias"]["dados"][0]
        assert isinstance(linha["id_linha"], int)

    def test_sheets_nao_vazam_id_linha_nem_colunas_extras(self, tmp_db):
        _criar_run({
            "Avarias": [_item("TOMATE", caminho="a.jpg")],
            "Uso Interno": [_item("SACO", categoria="Uso Interno", codigo="1", caminho="b.jpg")],
            "Erros de Análise": [_item("x.jpg", categoria="Erros de Análise", detalhes="F", caminho="x.jpg")],
        })
        sheets = mestre.obter_sheets_mestre()
        assert list(sheets["Avarias"].columns) == mestre.COLUNAS_POR_CATEGORIA["Avarias"]
        assert "id_linha" not in sheets["Avarias"].columns
        assert len(sheets["Avarias"]) == 1

    def test_banco_vazio_devolve_vazio(self, tmp_db):
        assert mestre.obter_secoes_mestre() == {}
        assert mestre.contar_por_categoria() == {}
        assert mestre.obter_sheets_mestre() == {}


class TestListarTodosItens:
    def test_ordena_da_execucao_mais_nova_para_a_mais_antiga(self, tmp_db):
        run_a = _criar_run({"Avarias": [_item("ANTIGA", caminho="a.jpg")]})
        run_b = _criar_run({"Avarias": [_item("NOVA", caminho="b.jpg")]})

        itens = db.listar_todos_itens()
        assert itens[0]["produto"] == "NOVA"
        assert itens[-1]["produto"] == "ANTIGA"

    def test_item_manual_sem_execucao_entra_na_visao(self, tmp_db):
        """Linhas adicionadas à mão (run_id=None) não podem sumir do relatório."""
        db.adicionar_item(None, "Avarias", {"Produto": "BATATA", "Quantidade": "3", "Peso": "2kg"})

        secoes = mestre.obter_secoes_mestre()
        assert secoes["Avarias"]["total"] == 1
        assert secoes["Avarias"]["dados"][0]["Produto"] == "BATATA"

