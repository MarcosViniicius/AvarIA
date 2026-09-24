"""Testes do catálogo de produtos (services/catalogo.py)."""

import pytest

from autoavaria.services import catalogo, db


class TestRegistrarEBuscar:
    def test_registra_e_busca_ean(self, tmp_db):
        assert catalogo.registrar("7897274410245", produto="LAVA-LOUÇAS", marca="GUARANI")
        entrada = catalogo.buscar("7897274410245")
        assert entrada["produto"] == "LAVA-LOUÇAS"
        assert entrada["marca"] == "GUARANI"
        assert entrada["tipo"] == "ean"

    def test_infere_tipo_plu_por_tamanho(self, tmp_db):
        catalogo.registrar("00140", produto="MANGA", preco_kg=6.99)
        entrada = catalogo.buscar("00140")
        assert entrada["tipo"] == "plu"

    def test_codigo_vazio_nao_registra(self, tmp_db):
        assert catalogo.registrar("") is False
        assert catalogo.registrar("   ") is False

    def test_busca_inexistente_devolve_none(self, tmp_db):
        assert catalogo.buscar("0000000000000") is None

    def test_atualizacao_nao_apaga_valor_existente_com_vazio(self, tmp_db):
        """Uma leitura ruim depois não deve apagar um dado bom já registrado."""
        catalogo.registrar("7897274410245", produto="LAVA-LOUÇAS", marca="GUARANI")
        catalogo.registrar("7897274410245", produto="", marca="")  # sem novidade
        entrada = catalogo.buscar("7897274410245")
        assert entrada["produto"] == "LAVA-LOUÇAS"
        assert entrada["marca"] == "GUARANI"

    def test_atualizacao_incrementa_vezes_visto(self, tmp_db):
        catalogo.registrar("7897274410245", produto="X")
        catalogo.registrar("7897274410245", produto="X")
        catalogo.registrar("7897274410245", produto="X")
        assert catalogo.buscar("7897274410245")["vezes_visto"] == 3


class TestAprender:
    def test_aprende_produto_de_resultado_ia(self, tmp_db):
        assert catalogo.aprender("7897274410245", produto="LAVA-LOUÇAS", marca="GUARANI")
        assert catalogo.buscar("7897274410245")["produto"] == "LAVA-LOUÇAS"

    def test_nao_aprende_sem_produto_nem_preco(self, tmp_db):
        assert catalogo.aprender("7897274410245", produto="") is False
        assert catalogo.buscar("7897274410245") is None

    def test_aprende_preco_kg_de_par_confiavel(self, tmp_db):
        # MANGA: total real R$5,16, peso real 0,738kg -> preço ~6,99/kg
        assert catalogo.aprender_preco_kg("00140", "MANGA", total_reais=5.16, peso_kg=0.738)
        entrada = catalogo.buscar("00140")
        assert entrada["preco_kg"] == pytest.approx(6.99, abs=0.01)

    def test_nao_aprende_preco_com_peso_zero(self, tmp_db):
        assert catalogo.aprender_preco_kg("00140", "MANGA", total_reais=5.16, peso_kg=0) is False


class TestPlausibilidadeDePeso:
    """Peso implausível não deve entrar no catálogo - vai para revisão."""

    def test_peso_absurdamente_alto_nao_e_aprendido(self, tmp_db):
        # 50kg num único tomate: claramente a IA leu a etiqueta errado.
        assert catalogo.aprender_preco_kg("00040", "TOMATE", total_reais=199.50, peso_kg=50.0) is False
        assert catalogo.buscar("00040") is None

    def test_peso_absurdamente_baixo_nao_e_aprendido(self, tmp_db):
        assert catalogo.aprender_preco_kg("00040", "TOMATE", total_reais=5.0, peso_kg=0.005) is False
        assert catalogo.buscar("00040") is None

    def test_peso_no_limite_da_faixa_e_aceito(self, tmp_db):
        assert catalogo.aprender_preco_kg("00040", "TOMATE", total_reais=30.0, peso_kg=catalogo.PESO_KG_MAXIMO)
        assert catalogo.buscar("00040") is not None

    def test_peso_implausivel_vai_para_fila_de_revisao(self, tmp_db):
        catalogo.aprender_preco_kg("00040", "TOMATE", total_reais=199.50, peso_kg=50.0)
        pendentes = catalogo.listar_revisoes_pendentes()
        assert len(pendentes) == 1
        assert pendentes[0]["codigo"] == "00040"
        assert pendentes[0]["peso_kg_proposto"] == pytest.approx(50.0)

    def test_peso_valido_nao_gera_revisao(self, tmp_db):
        catalogo.aprender_preco_kg("00140", "MANGA", total_reais=5.16, peso_kg=0.738)
        assert catalogo.listar_revisoes_pendentes() == []

    def test_revisao_repetida_para_mesmo_codigo_atualiza_em_vez_de_duplicar(self, tmp_db):
        catalogo.aprender_preco_kg("00040", "TOMATE", total_reais=199.50, peso_kg=50.0)
        catalogo.aprender_preco_kg("00040", "TOMATE", total_reais=250.0, peso_kg=60.0)
        pendentes = catalogo.listar_revisoes_pendentes()
        assert len(pendentes) == 1
        assert pendentes[0]["peso_kg_proposto"] == pytest.approx(60.0)


class TestEstaDesatualizado:
    def test_sem_timestamp_e_considerado_desatualizado(self, tmp_db):
        assert catalogo.esta_desatualizado(None) is True

    def test_timestamp_invalido_e_considerado_desatualizado(self, tmp_db):
        assert catalogo.esta_desatualizado("lixo-nao-e-data") is True

    def test_timestamp_recente_nao_esta_desatualizado(self, tmp_db):
        agora = db._now()
        assert catalogo.esta_desatualizado(agora) is False

    def test_timestamp_antigo_esta_desatualizado(self, tmp_db):
        import datetime as dt

        antigo = (dt.datetime.now() - dt.timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
        assert catalogo.esta_desatualizado(antigo, dias=30) is True

    def test_respeita_limite_de_dias_customizado(self, tmp_db):
        import datetime as dt

        ha_5_dias = (dt.datetime.now() - dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        assert catalogo.esta_desatualizado(ha_5_dias, dias=3) is True
        assert catalogo.esta_desatualizado(ha_5_dias, dias=10) is False


class TestListarEContar:
    def test_contar_por_tipo(self, tmp_db):
        catalogo.registrar("7897274410245", produto="A", tipo="ean")
        catalogo.registrar("00140", produto="B", tipo="plu")
        catalogo.registrar("00270", produto="C", tipo="plu")
        contagem = catalogo.contar()
        assert contagem["ean"] == 1
        assert contagem["plu"] == 2
        assert contagem["total"] == 3

    def test_listar_filtra_por_tipo(self, tmp_db):
        catalogo.registrar("7897274410245", produto="A", tipo="ean")
        catalogo.registrar("00140", produto="B", tipo="plu")
        eans = catalogo.listar(tipo="ean")
        assert len(eans) == 1
        assert eans[0]["codigo"] == "7897274410245"


class TestPopularDoHistorico:
    def test_popula_apenas_codigos_com_dv_valido(self, tmp_db):
        run_id = db.iniciar_execucao("processamento", imagens_total=2)
        db.registrar_itens(
            run_id,
            "Uso Interno",
            [
                {"Produto": "VALIDO", "Marca": "X", "Código de Barras": "7897274410245"},
                # dígito verificador quebrado - não deve virar entrada de catálogo
                {"Produto": "INVALIDO", "Marca": "Y", "Código de Barras": "7897274410241"},
            ],
        )
        resultado = catalogo.popular_do_historico()
        assert resultado["ean"] == 1
        assert catalogo.buscar("7897274410245")["produto"] == "VALIDO"
        assert catalogo.buscar("7897274410241") is None

    def test_idempotente(self, tmp_db):
        run_id = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(
            run_id, "Uso Interno",
            [{"Produto": "X", "Código de Barras": "7897274410245"}],
        )
        catalogo.popular_do_historico()
        antes = catalogo.buscar("7897274410245")
        resultado = catalogo.popular_do_historico()
        assert resultado["total"] == 1  # não duplica
        depois = catalogo.buscar("7897274410245")
        assert depois["vezes_visto"] == antes["vezes_visto"]
        assert depois["atualizado_em"] == antes["atualizado_em"]
