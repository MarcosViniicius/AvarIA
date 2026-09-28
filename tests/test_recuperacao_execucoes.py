"""Testes da recuperacao de execucoes orfas (services/db.recuperar_execucoes_orfas).

Uma execucao so pode estar 'em_andamento' enquanto o processo que a criou esta
vivo. No boot, qualquer uma nesse estado e orfa - e se ficar assim esconde a
ultima execucao que realmente concluiu (bug que quebrou o envio ao invertexto).
"""

from autoavaria.services import db


def _run(status="em_andamento", itens=None):
    run_id = db.iniciar_execucao("processamento", imagens_total=1)
    if itens:
        db.registrar_itens(run_id, "Avarias", itens)
    if status != "em_andamento":
        db.finalizar_execucao(run_id, status)
    return run_id


def test_marca_orfa_como_erro(tmp_db):
    orfa = _run("em_andamento")

    assert db.recuperar_execucoes_orfas() == 1
    assert db.obter_execucao(orfa)["status"] == "erro"


def test_preserva_execucoes_concluidas(tmp_db):
    ok = _run("concluido", itens=[{"Produto": "TOMATE", "Quantidade": 1, "Caminho da Imagem": "t.jpg"}])

    assert db.recuperar_execucoes_orfas() == 0
    assert db.obter_execucao(ok)["status"] == "concluido"


def test_orfa_nao_esconde_a_ultima_execucao_boa(tmp_db):
    """Depois de recuperar, o topo do historico deixa de ser a execucao vazia."""
    boa = _run("concluido", itens=[{"Produto": "TOMATE", "Quantidade": 1, "Caminho da Imagem": "t.jpg"}])
    orfa = _run("em_andamento")  # criada por ultimo

    assert db.listar_execucoes(limite=1)[0]["id"] == orfa

    db.recuperar_execucoes_orfas()
    ultima = db.listar_execucoes(limite=1)[0]
    assert ultima["id"] == orfa
    assert ultima["status"] == "erro"  # marcada, nao "em andamento"


def test_orfa_recebe_mensagem_explicativa(tmp_db):
    orfa = _run("em_andamento")
    db.recuperar_execucoes_orfas()

    execucao = db.obter_execucao(orfa)
    assert "recuperada na inicialização" in execucao["mensagem"]
    assert execucao["finalizado_em"] is not None


def test_idempotente(tmp_db):
    _run("em_andamento")
    assert db.recuperar_execucoes_orfas() == 1
    assert db.recuperar_execucoes_orfas() == 0
