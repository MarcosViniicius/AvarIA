"""Testes da sincronização Excel → banco na edição de dados.

Contexto: o Excel mestre não guarda o id do banco, então a correlação usa
`categoria + caminho_imagem` + os valores da linha. Havia dois casos de
múltiplas correspondências:

1. **O mesmo item em várias execuções** (a imagem foi reanalisada; o banco
   guarda por execução, o Excel acumula). São o mesmo dado: editar uma linha
   do Excel deve refletir em todas. Antes o código exigia correspondência
   ÚNICA e desistia — em 22% das linhas do mestre real. Era silencioso: o
   Histórico continuava com o valor antigo.

2. **Itens DIFERENTES na mesma foto** (ex.: "2 alface, 4 coentro"). Aí a
   ambiguidade é real e não dá para adivinhar — a edição fica no Excel e o
   usuário é avisado.
"""

import pytest

from autoavaria.services import db


def _item(produto, peso="1kg", categoria="Avarias", caminho="/img/foto.jpg", run_id=None):
    return {
        "Produto": produto,
        "Quantidade": 1,
        "Peso": peso,
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": caminho,
        "Ver Imagem": caminho,
        "_run_id": run_id,
    }


@pytest.fixture
def duas_execucoes_com_o_mesmo_item(tmp_db):
    """A mesma imagem gerou o mesmo item em duas execuções (duplicata)."""
    run_a = db.iniciar_execucao("processamento", imagens_total=1)
    run_b = db.iniciar_execucao("processamento", imagens_total=1)
    db.registrar_itens(run_a, "Avarias", [_item("TANGERINA", "1,856kg", caminho="/img/foto.jpg")])
    db.registrar_itens(run_b, "Avarias", [_item("TANGERINA", "1,856kg", caminho="/img/foto.jpg")])
    return run_a, run_b


class TestBuscarItensPorCaminho:
    def test_uma_correspondencia(self, tmp_db):
        run = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run, "Avarias", [_item("TOMATE")])
        ids = db.buscar_itens_por_caminho("Avarias", "/img/foto.jpg", _item("TOMATE"))
        assert len(ids) == 1

    def test_duplicatas_entre_execucoes_devolve_todas(self, tmp_db, duas_execucoes_com_o_mesmo_item):
        ids = db.buscar_itens_por_caminho(
            "Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")
        )
        assert len(ids) == 2, "as duas linhas iguais (uma por execução) devem ser encontradas"

    def test_itens_diferentes_na_mesma_foto_sem_valores_nao_chuta(self, tmp_db):
        """Sem `valores_atuais`, não há como saber qual dos itens da foto é."""
        run = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run, "Avarias", [
            _item("ALFACE", "1kg"),
            _item("COENTRO", "0,5kg"),
        ])
        assert db.buscar_itens_por_caminho("Avarias", "/img/foto.jpg") == []

    def test_itens_diferentes_na_mesma_foto_com_valores_desempata(self, tmp_db):
        run = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run, "Avarias", [
            _item("ALFACE", "1kg"),
            _item("COENTRO", "0,5kg"),
        ])
        ids = db.buscar_itens_por_caminho("Avarias", "/img/foto.jpg", _item("ALFACE", "1kg"))
        assert len(ids) == 1

    def test_valores_que_nao_batem_nao_retorna_nada(self, tmp_db):
        run = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run, "Avarias", [_item("ALFACE"), _item("COENTRO")])
        # produto que não existe na foto -> ambíguo, não chuta
        assert db.buscar_itens_por_caminho("Avarias", "/img/foto.jpg", _item("BATATA")) == []

    def test_sem_caminho_devolve_vazio(self, tmp_db):
        assert db.buscar_itens_por_caminho("Avarias", "", _item("TOMATE")) == []


class TestAtualizacaoEmLote:
    def test_atualiza_todas_as_duplicatas(self, tmp_db, duas_execucoes_com_o_mesmo_item):
        """O caso do bug: editar no Excel precisa refletir nas duas execuções."""
        ids = db.buscar_itens_por_caminho(
            "Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")
        )
        assert db.atualizar_itens_campo(ids, "Produto", "TANGERINA CORRIGIDA") == 2

        with db.get_connection() as conn:
            valores = {
                row["produto"]
                for row in conn.execute("SELECT produto FROM report_items WHERE id IN (?, ?)", ids)
            }
        assert valores == {"TANGERINA CORRIGIDA"}

    def test_atualizar_completo(self, tmp_db, duas_execucoes_com_o_mesmo_item):
        ids = db.buscar_itens_por_caminho(
            "Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")
        )
        alterados = db.atualizar_itens_completo(ids, {"Produto": "NOVA", "Peso": "2kg"})
        assert alterados == 2

    def test_excluir_itens_devolve_runs(self, tmp_db, duas_execucoes_com_o_mesmo_item):
        run_a, run_b = duas_execucoes_com_o_mesmo_item
        ids = db.buscar_itens_por_caminho(
            "Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")
        )
        runs = db.excluir_itens(ids)
        assert runs == {run_a, run_b}
        assert db.buscar_itens_por_caminho("Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")) == []

    def test_mover_categoria(self, tmp_db, duas_execucoes_com_o_mesmo_item):
        ids = db.buscar_itens_por_caminho(
            "Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")
        )
        assert db.mover_itens_categoria(ids, "Uso Interno") == 2
        with db.get_connection() as conn:
            cats = {
                row["categoria"]
                for row in conn.execute("SELECT categoria FROM report_items WHERE id IN (?, ?)", ids)
            }
        assert cats == {"Uso Interno"}

    def test_campo_invalido_nao_faz_nada(self, tmp_db):
        run = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run, "Avarias", [_item("TOMATE")])
        ids = db.buscar_itens_por_caminho("Avarias", "/img/foto.jpg", _item("TOMATE"))
        assert db.atualizar_itens_campo(ids, "CampoInexistente", "x") == 0

    def test_lista_vazia_e_segura(self, tmp_db):
        assert db.atualizar_itens_campo([], "Produto", "x") == 0
        assert db.atualizar_itens_completo([], {"Produto": "x"}) == 0
        assert db.excluir_itens([]) == set()
        assert db.mover_itens_categoria([], "Avarias") == 0


class TestCompatibilidade:
    def test_buscar_um_ainda_desiste_na_ambiguidade(self, tmp_db, duas_execucoes_com_o_mesmo_item):
        """A função antiga (um id) mantém o contrato: None quando há mais de um."""
        assert db.buscar_item_por_caminho(
            "Avarias", "/img/foto.jpg", _item("TANGERINA", "1,856kg")
        ) is None
