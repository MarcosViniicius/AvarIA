"""Testes da migração dos logs (log_mestre.txt / log_consumo_tokens.txt) para SQLite.

Contexto: os logs eram arquivos-texto lidos inteiros a cada verificação de
"esta imagem já foi processada?" — e havia DUAS implementações quase iguais
dessa leitura (extraction_pipeline.carregar_logs e
stats.carregar_logs_processados), que podiam divergir. Agora o SQLite é a
fonte primária e o arquivo continua sendo escrito como histórico/compatibilidade.

O ponto mais delicado é a DATA: a importação não pode carimbar tudo com o dia
da migração, senão a estatística de "último processamento" passa a mentir.
"""

import pytest

from avariaia.services import db


@pytest.fixture
def arquivos_log(tmp_path):
    """Cria os dois logs legados com dados no formato histórico."""
    processados = tmp_path / "log_mestre.txt"
    processados.write_text(
        "2026-08-31 23:37:29 - Processado: IMG-001.jpg\n"
        "2026-08-31 23:37:29 - Processado: IMG-002.jpg\n"
        "2026-09-23 22:39:57 - Processado: IMG-003.jpg\n"
        "IMG-legado-sem-data.jpg\n",
        encoding="utf-8",
    )
    consumo = tmp_path / "log_consumo_tokens.txt"
    consumo.write_text(
        "2026-08-31 23:37:35 - Tokens consumidos: 44,805 - 35 imagens\n"
        "2026-09-23 22:39:57 - Tokens consumidos: 95,552 - 74 imagens\n",
        encoding="utf-8",
    )
    return processados, consumo


class TestImportacaoPreservaData:
    def test_importa_nomes(self, tmp_db, arquivos_log):
        processados, consumo = arquivos_log
        db.importar_logs_dos_arquivos(processados, consumo)
        nomes = db.listar_arquivos_processados()
        assert {"IMG-001.jpg", "IMG-002.jpg", "IMG-003.jpg", "IMG-legado-sem-data.jpg"} <= nomes

    def test_preserva_a_data_original(self, tmp_db, arquivos_log):
        """A data do arquivo é a verdade — não o momento da importação."""
        processados, _ = arquivos_log
        db.importar_logs_dos_arquivos(processados, None)

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT processado_em FROM arquivos_processados WHERE nome = 'IMG-001.jpg'"
            ).fetchone()
        assert row["processado_em"] == "2026-08-31 23:37:29"

    def test_linha_legada_sem_data_nao_quebra(self, tmp_db, arquivos_log):
        processados, _ = arquivos_log
        db.importar_logs_dos_arquivos(processados, None)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT processado_em FROM arquivos_processados WHERE nome = 'IMG-legado-sem-data.jpg'"
            ).fetchone()
        assert row is not None
        assert row["processado_em"]  # ganha um carimbo, mas não quebra a importação

    def test_idempotente(self, tmp_db, arquivos_log):
        processados, consumo = arquivos_log
        db.importar_logs_dos_arquivos(processados, consumo)
        primeiro = len(db.listar_arquivos_processados())

        db.importar_logs_dos_arquivos(processados, consumo)
        assert len(db.listar_arquivos_processados()) == primeiro

    def test_importa_consumo_com_virgula_e_ponto(self, tmp_db, arquivos_log):
        _, consumo = arquivos_log
        db.importar_logs_dos_arquivos(None, consumo)

        registros = db.listar_consumo_log()
        valores = sorted(r["tokens"] for r in registros)
        assert valores == [44805, 95552]

    def test_consumo_nao_reimporta_quando_ja_tem_dado(self, tmp_db, arquivos_log):
        """Cada boot não pode acumular o histórico do arquivo de novo."""
        _, consumo = arquivos_log
        db.importar_logs_dos_arquivos(None, consumo)
        antes = len(db.listar_consumo_log())

        resultado = db.importar_logs_dos_arquivos(None, consumo)
        assert resultado["consumo"] == 0
        assert len(db.listar_consumo_log()) == antes


class TestRegistroEBusca:
    def test_registrar_e_idempotente(self, tmp_db):
        db.registrar_arquivo_processado("IMG-x.jpg")
        db.registrar_arquivo_processado("IMG-x.jpg")  # de novo
        assert db.listar_arquivos_processados() == {"IMG-x.jpg"}

    def test_limpar_devolve_quantidade(self, tmp_db):
        db.registrar_arquivo_processado("a.jpg")
        db.registrar_arquivo_processado("b.jpg")
        assert db.limpar_arquivos_processados() == 2
        assert db.listar_arquivos_processados() == set()


class TestStatsUsaBanco:
    def test_tokens_de_hoje_vem_do_banco(self, tmp_db, monkeypatch):
        """Sem arquivo de consumo, o total do dia sai da tabela."""
        from datetime import datetime

        from avariaia.services import stats

        hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.registrar_consumo_log(1000, "teste", hoje)

        monkeypatch.setattr(stats, "LOG_CONSUMO_FILE", "nao_existe.txt")
        monkeypatch.setattr(stats, "LOG_PROCESSADOS_FILE", "nao_existe.txt")

        resultado = stats.obter_estatisticas()
        assert resultado["tokens_consumidos_hoje"] == 1000
