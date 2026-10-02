"""Testes de services/stats.py.

Regressão: "imagens_processadas" contava o tamanho bruto do log
(log_mestre.txt), não a interseção com o que realmente está na pasta. Depois
de "Limpar Imagens" (que apaga os arquivos mas não mexe no log), o dashboard
mostrava processadas > total - um número sem sentido.
"""

from avariaia.services import stats


def test_processadas_nunca_excede_total(tmp_path, monkeypatch, tmp_db):
    pasta = tmp_path / "imagens"
    pasta.mkdir()
    # só 1 imagem na pasta agora...
    (pasta / "IMG-1.jpg").write_bytes(b"x")

    # ...mas o log lista 3 (as outras 2 foram "limpas" da pasta sem tocar no log)
    log = tmp_path / "log.txt"
    log.write_text(
        "2026-01-01 10:00:00 - Processado: IMG-1.jpg\n"
        "2026-01-01 10:00:00 - Processado: IMG-2.jpg\n"
        "2026-01-01 10:00:00 - Processado: IMG-3.jpg\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(stats, "DIRETORIO_IMAGENS", str(pasta))
    monkeypatch.setattr(stats, "ARCHIVE_FOLDER", str(tmp_path / "arquivadas"))
    monkeypatch.setattr(stats, "LOG_PROCESSADOS_FILE", str(log))

    resultado = stats.obter_estatisticas()

    assert resultado["imagens_total"] == 1
    assert resultado["imagens_processadas"] == 1  # não 3
    assert resultado["imagens_pendentes"] == 0


def test_pendentes_conta_so_o_que_nao_esta_no_log(tmp_path, monkeypatch, tmp_db):
    pasta = tmp_path / "imagens"
    pasta.mkdir()
    (pasta / "IMG-1.jpg").write_bytes(b"x")
    (pasta / "IMG-2.jpg").write_bytes(b"x")

    log = tmp_path / "log.txt"
    log.write_text("2026-01-01 10:00:00 - Processado: IMG-1.jpg\n", encoding="utf-8")

    monkeypatch.setattr(stats, "DIRETORIO_IMAGENS", str(pasta))
    monkeypatch.setattr(stats, "ARCHIVE_FOLDER", str(tmp_path / "arquivadas"))
    monkeypatch.setattr(stats, "LOG_PROCESSADOS_FILE", str(log))

    resultado = stats.obter_estatisticas()

    assert resultado["imagens_total"] == 2
    assert resultado["imagens_processadas"] == 1
    assert resultado["imagens_pendentes"] == 1


def test_sem_pasta_nem_log_devolve_zeros(tmp_path, monkeypatch, tmp_db):
    monkeypatch.setattr(stats, "DIRETORIO_IMAGENS", str(tmp_path / "nao_existe"))
    monkeypatch.setattr(stats, "ARCHIVE_FOLDER", str(tmp_path / "arquivadas"))
    monkeypatch.setattr(stats, "LOG_PROCESSADOS_FILE", str(tmp_path / "nao_existe.txt"))

    resultado = stats.obter_estatisticas()

    assert resultado["imagens_total"] == 0
    assert resultado["imagens_processadas"] == 0
    assert resultado["imagens_pendentes"] == 0


def test_conta_imagens_arquivadas_como_processadas(tmp_path, monkeypatch, tmp_db):
    pendentes = tmp_path / "imagens"
    arquivadas = tmp_path / "arquivadas"
    pendentes.mkdir()
    arquivadas.mkdir()
    (pendentes / "IMG-pendente.jpg").write_bytes(b"x")
    (arquivadas / "IMG-processada.jpg").write_bytes(b"y")
    log = tmp_path / "log.txt"
    log.write_text("2026-01-01 10:00:00 - Processado: IMG-processada.jpg\n", encoding="utf-8")

    monkeypatch.setattr(stats, "DIRETORIO_IMAGENS", str(pendentes))
    monkeypatch.setattr(stats, "ARCHIVE_FOLDER", str(arquivadas))
    monkeypatch.setattr(stats, "LOG_PROCESSADOS_FILE", str(log))

    resultado = stats.obter_estatisticas()
    assert resultado["imagens_total"] == 2
    assert resultado["imagens_processadas"] == 1
    assert resultado["imagens_pendentes"] == 1
