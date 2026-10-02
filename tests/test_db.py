"""Testes da camada de persistência (services/db.py), usando um banco SQLite
temporário isolado via a fixture `tmp_db` (nunca toca em database/avariaia.db)."""


def test_ciclo_de_vida_de_uma_execucao(tmp_db):
    run_id = tmp_db.iniciar_execucao("processamento", imagens_total=3)
    assert run_id > 0

    tmp_db.registrar_itens(
        run_id,
        "Avarias",
        [{"Produto": "Tomate", "Peso": "1kg", "Observação da Mensagem": "-", "Caminho da Imagem": "a.jpg"}],
    )
    tmp_db.registrar_consumo_tokens(run_id, 100, "teste")
    tmp_db.finalizar_execucao(run_id, "concluido", avarias=1, uso_interno=0, erros=0, tokens_consumidos=100)

    execucao = tmp_db.obter_execucao(run_id)
    assert execucao["status"] == "concluido"
    assert execucao["avarias"] == 1
    assert len(execucao["itens"]) == 1
    assert execucao["itens"][0]["produto"] == "Tomate"
    assert execucao["itens"][0]["peso"] == "1kg"


def test_obter_execucao_inexistente_retorna_none(tmp_db):
    assert tmp_db.obter_execucao(9999) is None


class TestCrudDeItens:
    def _criar_item_avaria(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.registrar_itens(
            run_id, "Avarias", [{"Produto": "Tomate", "Peso": "1kg", "Caminho da Imagem": "a.jpg"}]
        )
        item = tmp_db.obter_execucao(run_id)["itens"][0]
        return run_id, item["id"]

    def test_atualizar_campo_peso(self, tmp_db):
        run_id, item_id = self._criar_item_avaria(tmp_db)
        assert tmp_db.atualizar_item_campo(item_id, "Peso", "2kg") is True
        assert tmp_db.obter_item(item_id)["peso"] == "2kg"

    def test_atualizar_campo_invalido_retorna_false(self, tmp_db):
        run_id, item_id = self._criar_item_avaria(tmp_db)
        assert tmp_db.atualizar_item_campo(item_id, "Campo Que Nao Existe", "x") is False

    def test_atualizar_completo(self, tmp_db):
        run_id, item_id = self._criar_item_avaria(tmp_db)
        assert tmp_db.atualizar_item_completo(item_id, {"Produto": "Tomate Cereja", "Peso": "0.5kg"}) is True
        item = tmp_db.obter_item(item_id)
        assert item["produto"] == "Tomate Cereja"
        assert item["peso"] == "0.5kg"

    def test_mover_categoria_e_recalcular_contagens(self, tmp_db):
        run_id, item_id = self._criar_item_avaria(tmp_db)
        tmp_db.finalizar_execucao(run_id, "concluido", avarias=1, uso_interno=0, erros=0)

        assert tmp_db.mover_item_categoria(item_id, "Uso Interno") is True
        tmp_db.recalcular_contagens(run_id)

        execucao = next(e for e in tmp_db.listar_execucoes(50) if e["id"] == run_id)
        assert execucao["avarias"] == 0
        assert execucao["uso_interno"] == 1

    def test_excluir_item(self, tmp_db):
        run_id, item_id = self._criar_item_avaria(tmp_db)
        assert tmp_db.excluir_item(item_id) == run_id
        assert tmp_db.obter_item(item_id) is None

    def test_excluir_item_inexistente_retorna_none(self, tmp_db):
        assert tmp_db.excluir_item(9999) is None

    def test_adicionar_item(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        item_id = tmp_db.adicionar_item(run_id, "Uso Interno", {"Produto": "Saco de Lixo", "Marca": "X", "Código de Barras": "123"})
        item = tmp_db.obter_item(item_id)
        assert item["produto"] == "Saco de Lixo"
        assert item["marca"] == "X"
        assert item["codigo_barras"] == "123"


class TestRelatoriosUnificados:
    def test_registrar_e_listar(self, tmp_db):
        tmp_db.registrar_relatorio_unificado(arquivo_xlsx="Relatorio_Unificado_teste.xlsx", arquivo_txt=None)
        relatorios = tmp_db.listar_relatorios_unificados()
        assert len(relatorios) == 1
        assert relatorios[0]["arquivo_xlsx"] == "Relatorio_Unificado_teste.xlsx"

    def test_nao_duplica_mesmo_arquivo(self, tmp_db):
        tmp_db.registrar_relatorio_unificado(arquivo_xlsx="a.xlsx", arquivo_txt=None)
        tmp_db.registrar_relatorio_unificado(arquivo_xlsx="a.xlsx", arquivo_txt=None)
        assert len(tmp_db.listar_relatorios_unificados()) == 1

    def test_remover_por_arquivo(self, tmp_db):
        tmp_db.registrar_relatorio_unificado(arquivo_xlsx="a.xlsx", arquivo_txt=None)
        tmp_db.registrar_relatorio_unificado(arquivo_xlsx="b.xlsx", arquivo_txt=None)
        removidos = tmp_db.remover_relatorios_unificados_por_arquivo(["a.xlsx"])
        assert removidos == 1
        restantes = tmp_db.listar_relatorios_unificados()
        assert len(restantes) == 1
        assert restantes[0]["arquivo_xlsx"] == "b.xlsx"


class TestRegistrarUnificadoGerado:
    """O helper é o único ponto que grava um unificado, para os dois escopos
    (global e por execução) não divergirem no formato do ``resumo`` — foi
    exatamente essa divergência que fez o ``execucao_id`` ser gravado e nunca
    exibido."""

    def test_escopo_global(self, tmp_db):
        tmp_db.registrar_unificado_gerado(nome_arquivo="u.xlsx", formato="xlsx")
        rel = tmp_db.listar_relatorios_unificados()[0]
        assert rel["arquivo_xlsx"] == "u.xlsx"
        assert rel["arquivo_txt"] is None
        assert rel["resumo"]["escopo"] == "global"
        assert "execucao_id" not in rel["resumo"]

    def test_escopo_execucao(self, tmp_db):
        tmp_db.registrar_unificado_gerado(
            nome_arquivo="u.txt",
            formato="txt",
            execucao_id=22,
            total_itens=74,
            contagem_por_secao={"Avarias": 10},
        )
        rel = tmp_db.listar_relatorios_unificados()[0]
        assert rel["arquivo_txt"] == "u.txt"
        assert rel["arquivo_xlsx"] is None
        assert rel["resumo"]["escopo"] == "execucao"
        assert rel["resumo"]["execucao_id"] == 22
        assert rel["resumo"]["contagem_por_secao"] == {"Avarias": 10}
        assert rel["total_itens"] == 74

    def test_formato_txt_nao_marca_xlsx(self, tmp_db):
        tmp_db.registrar_unificado_gerado(nome_arquivo="u.txt", formato="txt")
        rel = tmp_db.listar_relatorios_unificados()[0]
        assert rel["arquivo_xlsx"] is None and rel["arquivo_txt"] == "u.txt"


def test_contar_itens_com_imagem(tmp_db):
    run_id = tmp_db.iniciar_execucao("processamento")
    tmp_db.registrar_itens(run_id, "Avarias", [{"Produto": "A", "Caminho da Imagem": "x.jpg"}])
    tmp_db.registrar_itens(run_id, "Avarias", [{"Produto": "B", "Caminho da Imagem": None}])
    assert tmp_db.contar_itens_com_imagem() == 1


class TestVersionamento:
    def test_execucao_nova_tem_raiz_propria_e_versao_1(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        execucao = tmp_db.obter_execucao(run_id)
        assert execucao["raiz_execucao_id"] == run_id
        assert execucao["versao"] == 1

    def test_reanalise_herda_raiz_e_incrementa_versao(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        reanalise_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        execucao_reanalise = tmp_db.obter_execucao(reanalise_id)
        assert execucao_reanalise["raiz_execucao_id"] == run_id
        assert execucao_reanalise["versao"] == 2
        assert execucao_reanalise["tipo"] == "reanalise"

    def test_terceira_versao_incrementa_a_partir_da_ultima(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.iniciar_reanalise_de_execucao(run_id)
        terceira_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        assert tmp_db.obter_execucao(terceira_id)["versao"] == 3

    def test_listar_versoes_retorna_em_ordem(self, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        reanalise_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        versoes = tmp_db.listar_versoes(run_id)
        assert [v["id"] for v in versoes] == [run_id, reanalise_id]
        assert [v["versao"] for v in versoes] == [1, 2]

    def test_execucoes_de_linhagens_diferentes_nao_se_misturam(self, tmp_db):
        run_a = tmp_db.iniciar_execucao("processamento")
        run_b = tmp_db.iniciar_execucao("processamento")
        tmp_db.iniciar_reanalise_de_execucao(run_a)
        assert len(tmp_db.listar_versoes(run_a)) == 2
        assert len(tmp_db.listar_versoes(run_b)) == 1


class TestMigracaoBancoLegado:
    """Rebrand AvarIA: o banco mudou de autoavaria.db para avariaia.db."""

    def _criar_sqlite(self, caminho, valor):
        import sqlite3

        con = sqlite3.connect(str(caminho))
        con.execute("CREATE TABLE marco (valor TEXT)")
        con.execute("INSERT INTO marco (valor) VALUES (?)", (valor,))
        con.commit()
        con.close()

    def _ler_marco(self, caminho):
        import sqlite3

        con = sqlite3.connect(str(caminho))
        valor = con.execute("SELECT valor FROM marco").fetchone()[0]
        con.close()
        return valor

    def _apontar_para(self, monkeypatch, tmp_path, novo):
        from avariaia.services import db as db_module

        monkeypatch.setattr(db_module, "DATABASE_DIR", tmp_path)
        monkeypatch.setattr(db_module, "DATABASE_FILE", novo)
        return db_module

    def test_copia_o_banco_antigo_e_preserva_backup(self, tmp_path, monkeypatch):
        legado = tmp_path / "autoavaria.db"
        self._criar_sqlite(legado, "historico-antigo")
        novo = tmp_path / "avariaia.db"
        db_module = self._apontar_para(monkeypatch, tmp_path, novo)

        assert db_module.migrar_banco_legado() is True

        assert novo.exists()
        assert self._ler_marco(novo) == "historico-antigo"
        assert not legado.exists()
        assert (tmp_path / "autoavaria.db.bak").exists()

    def test_nunca_sobrescreve_banco_novo_existente(self, tmp_path, monkeypatch):
        legado = tmp_path / "autoavaria.db"
        self._criar_sqlite(legado, "antigo")
        novo = tmp_path / "avariaia.db"
        self._criar_sqlite(novo, "atual")
        db_module = self._apontar_para(monkeypatch, tmp_path, novo)

        assert db_module.migrar_banco_legado() is False

        assert self._ler_marco(novo) == "atual"
        assert legado.exists()  # intocado

    def test_init_db_dispara_a_migracao(self, tmp_path, monkeypatch):
        legado = tmp_path / "autoavaria.db"
        self._criar_sqlite(legado, "x")
        novo = tmp_path / "avariaia.db"
        db_module = self._apontar_para(monkeypatch, tmp_path, novo)

        db_module.init_db()

        assert novo.exists()
        assert (tmp_path / "autoavaria.db.bak").exists()
        with db_module.get_connection() as conn:
            tabelas = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "processing_runs" in tabelas
        assert "report_items" in tabelas
