"""Testes da limpeza de exportações antigas (services/maintenance.py)."""

from avariaia.services import maintenance


def test_mantem_apenas_os_n_mais_recentes(tmp_path, tmp_db):
    pasta = tmp_path / "resultados"
    pasta.mkdir()
    for i in range(35):
        arquivo = pasta / f"Relatorio_Unificado_2026010{i:02d}_000000.xlsx"
        arquivo.write_text("fake")
        tmp_db.registrar_relatorio_unificado(arquivo_xlsx=arquivo.name, arquivo_txt=None)

    for i in range(10):
        arquivo = pasta / f"Historico_Execucao_1_2026010{i:02d}_000000.xlsx"
        arquivo.write_text("fake")

    removidos = maintenance.limpar_exportacoes_antigas(pasta, manter=30)

    assert removidos == {"unificados": 5, "execucoes": 0}
    assert len(list(pasta.iterdir())) == 40
    assert len(tmp_db.listar_relatorios_unificados(limite=100)) == 30


def test_nao_remove_nada_se_dentro_do_limite(tmp_path, tmp_db):
    pasta = tmp_path / "resultados"
    pasta.mkdir()
    for i in range(5):
        (pasta / f"Relatorio_Unificado_2026010{i}_000000.xlsx").write_text("fake")

    removidos = maintenance.limpar_exportacoes_antigas(pasta, manter=30)

    assert removidos == {"unificados": 0, "execucoes": 0}
    assert len(list(pasta.iterdir())) == 5


def test_pasta_inexistente_nao_falha(tmp_path):
    pasta_fake = tmp_path / "nao_existe"
    removidos = maintenance.limpar_exportacoes_antigas(pasta_fake, manter=30)
    assert removidos == {"unificados": 0, "execucoes": 0}


def test_ignora_arquivos_que_nao_batem_o_padrao(tmp_path):
    (tmp_path / "outro_arquivo.xlsx").write_text("fake")
    (tmp_path / "README.md").write_text("fake")

    removidos = maintenance.limpar_exportacoes_antigas(tmp_path, manter=0)

    assert removidos == {"unificados": 0, "execucoes": 0}
    assert len(list(tmp_path.iterdir())) == 2
