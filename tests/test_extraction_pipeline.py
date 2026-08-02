"""Testes do pipeline de processamento (services/extraction_pipeline.py).

Foco na garantia mais importante do pipeline: uma imagem só é marcada como
"processada" (log_mestre.txt) DEPOIS que o resultado dela foi gravado em
disco. Sem isso, uma execução interrompida no meio marca imagens como
processadas sem salvar nada — e elas nunca mais são reanalisadas
automaticamente (perda de dados silenciosa).
"""

import json

import pytest

import autoavaria.services.extraction_pipeline as pipeline


class _ProviderFalso:
    """Provider de mentira: o pipeline só precisa dele para logar o nome do provedor —
    a análise em si é substituída por um fake de `extrair_dados_de_lote` em cada teste."""

    nome_provedor = "Provedor de Teste"


@pytest.fixture
def ambiente_isolado(tmp_path, monkeypatch, tmp_db):
    """Redireciona imagens/Excel/logs do pipeline para uma pasta temporária."""
    from PIL import Image

    pasta_imagens = tmp_path / "imagens"
    pasta_imagens.mkdir()
    for i in range(1, 5):
        Image.new("RGB", (4, 4), color="red").save(pasta_imagens / f"IMG-{i}.jpg")

    excel = tmp_path / "Relatorio.xlsx"
    log_mestre = tmp_path / "log_mestre.txt"
    log_consumo = tmp_path / "log_consumo.txt"
    pasta_arquivadas = tmp_path / "arquivadas"

    monkeypatch.setattr(pipeline, "UPLOAD_FOLDER", pasta_imagens)
    monkeypatch.setattr(pipeline, "ARQUIVO_SAIDA_EXCEL", excel)
    monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", log_mestre)
    monkeypatch.setattr(pipeline, "LOG_CONSUMO_FILE", log_consumo)
    monkeypatch.setattr(pipeline, "CANCEL_FILE", tmp_path / ".cancel")
    monkeypatch.setattr(pipeline, "ARCHIVE_FOLDER", pasta_arquivadas)

    config_fake = {
        "api": {"provider": "gemini", "gemini_api_key": "fake-key", "modelo_selecionado": "gemini-2.5-flash"},
        "processamento": {"tamanho_lote": 2, "max_workers": 1, "request_delay": 0, "temperatura": 0.1,
                          "max_tokens": 4000, "timeout": 60},
    }
    monkeypatch.setattr(pipeline, "carregar_configuracao", lambda: config_fake)

    return {"imagens": pasta_imagens, "excel": excel, "log_mestre": log_mestre, "arquivadas": pasta_arquivadas}


def _resposta_ok(nomes):
    return json.dumps({n: {"tipo": "Avaria", "itens": [{"produto": "TOMATE", "peso": "1kg"}]} for n in nomes})


def _imagens_com_dado_no_excel(caminho_excel) -> set:
    """Nomes de arquivo que realmente têm alguma linha salva no relatório."""
    import os

    from autoavaria.services.report_editing import carregar_todas_sheets

    if not caminho_excel.exists():
        return set()

    nomes = set()
    for _, df in carregar_todas_sheets(str(caminho_excel)).items():
        if "Caminho da Imagem" in df.columns:
            for caminho in df["Caminho da Imagem"].dropna():
                nomes.add(os.path.basename(str(caminho)))
    return nomes


class TestLogSoDepoisDeGravar:
    def test_interrupcao_no_meio_nao_marca_imagem_sem_dado_salvo(self, ambiente_isolado, monkeypatch):
        """Regressão (perda de dados): um lote que não chegou a ser gravado NÃO pode
        ficar marcado como processado — senão nunca mais seria reanalisado.

        A invariante verificada é "todo arquivo marcado como processado tem dado
        salvo", que vale independentemente de qual lote o executor devolve primeiro
        (as_completed não garante a ordem de submissão)."""
        chamadas = {"n": 0}

        def fake_extrair(lote, provider, mensagens):
            chamadas["n"] += 1
            nomes = [p.split("\\")[-1].split("/")[-1] for p in lote]
            if chamadas["n"] == 1:
                return json.loads(_resposta_ok(nomes)), 100
            raise KeyboardInterrupt("processo morto no meio do 2º lote")

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        with pytest.raises(KeyboardInterrupt):
            pipeline.main()

        processados = pipeline.carregar_logs()
        com_dado = _imagens_com_dado_no_excel(ambiente_isolado["excel"])

        assert processados <= com_dado, (
            f"Imagens marcadas como processadas sem dado salvo: {processados - com_dado}"
        )
        # E o processamento não pode ter marcado tudo como pronto.
        assert len(processados) < 4

    def test_grava_o_lote_antes_de_marcar_como_processado(self, ambiente_isolado, monkeypatch):
        """A ordem das operações é o que garante a invariante acima: primeiro
        salvar no Excel, só depois escrever no log de processados."""
        ordem = []

        def fake_extrair(lote, provider, mensagens):
            nomes = [p.split("\\")[-1].split("/")[-1] for p in lote]
            return json.loads(_resposta_ok(nomes)), 100

        salvar_original = pipeline.salvar_relatorio_excel
        log_original = pipeline.registrar_log
        arquivar_original = pipeline.image_archive.arquivar_imagem

        def salvar_espiao(*args, **kwargs):
            ordem.append("salvar_excel")
            return salvar_original(*args, **kwargs)

        def log_espiao(*args, **kwargs):
            ordem.append("registrar_log")
            return log_original(*args, **kwargs)

        def arquivar_espiao(*args, **kwargs):
            ordem.append("arquivar_imagem")
            return arquivar_original(*args, **kwargs)

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())
        monkeypatch.setattr(pipeline, "salvar_relatorio_excel", salvar_espiao)
        monkeypatch.setattr(pipeline, "registrar_log", log_espiao)
        monkeypatch.setattr(pipeline.image_archive, "arquivar_imagem", arquivar_espiao)

        pipeline.main()

        assert ordem.index("salvar_excel") < ordem.index("registrar_log")
        # Arquivar é sempre o último passo do lote: só depois de gravar e
        # marcar como processado, nunca antes (senão uma interrupção no meio
        # poderia deixar uma imagem "sumida" da pasta sem dado gravado).
        assert ordem.index("registrar_log") < ordem.index("arquivar_imagem")
        # E isso se repete a cada lote (2 lotes de 2 imagens = 2 gravações).
        assert ordem.count("salvar_excel") == 2

    def test_execucao_completa_marca_todas_as_imagens(self, ambiente_isolado, monkeypatch):
        def fake_extrair(lote, provider, mensagens):
            nomes = [p.split("\\")[-1].split("/")[-1] for p in lote]
            return json.loads(_resposta_ok(nomes)), 100

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        pipeline.main()

        assert len(pipeline.carregar_logs()) == 4
        assert ambiente_isolado["excel"].exists()

    def test_lote_que_estoura_vira_linhas_de_erro_em_vez_de_sumir(self, ambiente_isolado, monkeypatch):
        """Um lote que falha deve deixar rastro na aba de Erros (permitindo reanálise),
        nunca desaparecer silenciosamente."""
        def fake_extrair(lote, provider, mensagens):
            raise RuntimeError("falha inesperada da API")

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        pipeline.main()

        from autoavaria.services.report_editing import carregar_todas_sheets

        sheets = carregar_todas_sheets(str(ambiente_isolado["excel"]))
        assert len(sheets["Erros de Análise"]) == 4
        assert "falha inesperada da API" in sheets["Erros de Análise"]["Detalhes do Erro"].iloc[0]

        # Imagens com erro ficam na pasta de pendentes - reanalisar_erros()
        # precisa achá-las lá por nome para poder reprocessá-las.
        assert len(list(ambiente_isolado["imagens"].iterdir())) == 4
        assert not ambiente_isolado["arquivadas"].exists() or not any(
            ambiente_isolado["arquivadas"].iterdir()
        )


class TestArquivamentoDeImagensProcessadas:
    """Imagens processadas com sucesso saem da pasta de pendentes e vão para
    a pasta de arquivo (ver services/image_archive.py) - é o que evita a
    pasta de upload crescer para sempre a cada nova análise."""

    def test_imagens_com_sucesso_saem_da_pasta_pendente_e_vao_para_o_arquivo(
        self, ambiente_isolado, monkeypatch
    ):
        def fake_extrair(lote, provider, mensagens):
            nomes = [p.split("\\")[-1].split("/")[-1] for p in lote]
            return json.loads(_resposta_ok(nomes)), 100

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        pipeline.main()

        assert list(ambiente_isolado["imagens"].iterdir()) == []
        nomes_arquivados = {p.name for p in ambiente_isolado["arquivadas"].iterdir()}
        assert nomes_arquivados == {"IMG-1.jpg", "IMG-2.jpg", "IMG-3.jpg", "IMG-4.jpg"}

    def test_imagens_com_erro_ficam_na_pasta_pendente(self, ambiente_isolado, monkeypatch):
        def fake_extrair(lote, provider, mensagens):
            # Sempre devolve erro para IMG-1, sucesso para as demais.
            resultado = {}
            for p in lote:
                nome = p.split("\\")[-1].split("/")[-1]
                if nome == "IMG-1.jpg":
                    resultado[nome] = {"tipo": "Erro", "detalhes": "falha simulada"}
                else:
                    resultado[nome] = {"tipo": "Avaria", "itens": [{"produto": "TOMATE", "peso": "1kg"}]}
            return resultado, 100

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        pipeline.main()

        pendentes = {p.name for p in ambiente_isolado["imagens"].iterdir()}
        arquivadas = {p.name for p in ambiente_isolado["arquivadas"].iterdir()}
        assert pendentes == {"IMG-1.jpg"}
        assert arquivadas == {"IMG-2.jpg", "IMG-3.jpg", "IMG-4.jpg"}


class TestReanaliseArquivaImagemCorrigida:
    """Quando reanalisar_erros() consegue corrigir um item, a imagem dele
    também precisa sair da pasta de pendentes - senão o arquivamento só
    funcionaria no fluxo principal, e imagens corrigidas via reanálise
    ficariam esquecidas na pasta de pendentes para sempre."""

    def test_imagem_corrigida_e_arquivada(self, tmp_path, monkeypatch, tmp_db):
        from PIL import Image

        pasta_imagens = tmp_path / "imagens"
        pasta_imagens.mkdir()
        Image.new("RGB", (4, 4), color="red").save(pasta_imagens / "IMG-1.jpg")

        excel = tmp_path / "Relatorio.xlsx"
        erro = {
            "Arquivo": "IMG-1.jpg",
            "Detalhes do Erro": "falha simulada",
            "Observação da Mensagem": "Nenhuma",
            "Caminho da Imagem": str(pasta_imagens / "IMG-1.jpg"),
            "Ver Imagem": str(pasta_imagens / "IMG-1.jpg"),
        }
        pipeline.salvar_relatorio_excel(str(excel), [], [], [erro])

        pasta_arquivadas = tmp_path / "arquivadas"
        monkeypatch.setattr(pipeline, "ARCHIVE_FOLDER", pasta_arquivadas)
        monkeypatch.setattr(
            pipeline,
            "carregar_configuracao",
            lambda: {
                "api": {"provider": "gemini", "gemini_api_key": "fake-key"},
                "processamento": {"request_delay": 0},
            },
        )
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        def fake_extrair(lote, provider, mensagens):
            return {"IMG-1.jpg": {"tipo": "Avaria", "itens": [{"produto": "TOMATE", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        resultado = pipeline.reanalisar_erros(diretorio_imagens=str(pasta_imagens), arquivo_excel=str(excel))

        assert resultado["corrigidos"] == 1
        assert not (pasta_imagens / "IMG-1.jpg").exists()
        assert (pasta_arquivadas / "IMG-1.jpg").exists()

    def test_imagem_ainda_com_erro_nao_e_arquivada(self, tmp_path, monkeypatch, tmp_db):
        from PIL import Image

        pasta_imagens = tmp_path / "imagens"
        pasta_imagens.mkdir()
        Image.new("RGB", (4, 4), color="red").save(pasta_imagens / "IMG-1.jpg")

        excel = tmp_path / "Relatorio.xlsx"
        erro = {
            "Arquivo": "IMG-1.jpg",
            "Detalhes do Erro": "falha simulada",
            "Observação da Mensagem": "Nenhuma",
            "Caminho da Imagem": str(pasta_imagens / "IMG-1.jpg"),
            "Ver Imagem": str(pasta_imagens / "IMG-1.jpg"),
        }
        pipeline.salvar_relatorio_excel(str(excel), [], [], [erro])

        pasta_arquivadas = tmp_path / "arquivadas"
        monkeypatch.setattr(pipeline, "ARCHIVE_FOLDER", pasta_arquivadas)
        monkeypatch.setattr(
            pipeline,
            "carregar_configuracao",
            lambda: {
                "api": {"provider": "gemini", "gemini_api_key": "fake-key"},
                "processamento": {"request_delay": 0},
            },
        )
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        def fake_extrair_ainda_com_erro(lote, provider, mensagens):
            return {"IMG-1.jpg": {"tipo": "Erro", "detalhes": "ainda falhando"}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair_ainda_com_erro)

        resultado = pipeline.reanalisar_erros(diretorio_imagens=str(pasta_imagens), arquivo_excel=str(excel))

        assert resultado["corrigidos"] == 0
        assert (pasta_imagens / "IMG-1.jpg").exists()
        assert not pasta_arquivadas.exists() or not any(pasta_arquivadas.iterdir())


class TestLinhaDeErro:
    def test_monta_linha_com_todas_as_colunas_da_aba_de_erros(self):
        linha = pipeline._linha_de_erro("IMG-9.jpg", "algum erro", {"IMG-9.jpg": "obs"}, "/imagens")
        assert linha["Arquivo"] == "IMG-9.jpg"
        assert linha["Detalhes do Erro"] == "algum erro"
        assert linha["Observação da Mensagem"] == "obs"
        assert linha["Caminho da Imagem"].endswith("IMG-9.jpg")


class TestModoSemIA:
    """Cobre o motivo de existir o modo sem IA: processar sem nenhuma API key."""

    @pytest.fixture
    def ambiente_com_codigo_de_barras(self, tmp_path, monkeypatch, tmp_db):
        """Como `ambiente_isolado`, mas com imagens que têm um EAN-13 de verdade
        (o modo sem IA não tem o que extrair de um quadrado vermelho liso)."""
        zxingcpp = pytest.importorskip("zxingcpp")
        cv2 = pytest.importorskip("cv2")

        pasta_imagens = tmp_path / "imagens"
        pasta_imagens.mkdir()
        bc = zxingcpp.create_barcode("7897274410245", format=zxingcpp.EAN13)
        imagem = zxingcpp.write_barcode_to_image(bc, scale=4)
        import numpy as np

        cv2.imwrite(str(pasta_imagens / "IMG-1.jpg"), np.array(imagem))

        excel = tmp_path / "Relatorio.xlsx"
        log_mestre = tmp_path / "log_mestre.txt"
        log_consumo = tmp_path / "log_consumo.txt"

        monkeypatch.setattr(pipeline, "UPLOAD_FOLDER", pasta_imagens)
        monkeypatch.setattr(pipeline, "ARQUIVO_SAIDA_EXCEL", excel)
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", log_mestre)
        monkeypatch.setattr(pipeline, "LOG_CONSUMO_FILE", log_consumo)
        monkeypatch.setattr(pipeline, "CANCEL_FILE", tmp_path / ".cancel")

        # SEM chave de API nenhuma - é exatamente o ponto do modo sem IA.
        config_fake = {
            "api": {"provider": "gemini", "gemini_api_key": "", "modelo_selecionado": "x"},
            "processamento": {
                "tamanho_lote": 5, "max_workers": 1, "request_delay": 0,
                "temperatura": 0.1, "max_tokens": 4000, "timeout": 60,
                "modo_extracao": "sem_ia",
            },
        }
        monkeypatch.setattr(pipeline, "carregar_configuracao", lambda: config_fake)
        return {"imagens": pasta_imagens, "excel": excel}

    def test_processa_sem_nenhuma_api_key(self, ambiente_com_codigo_de_barras):
        from autoavaria.services.report_editing import carregar_todas_sheets

        pipeline.main()  # usa modo_extracao do config ("sem_ia"), sem provider

        sheets = carregar_todas_sheets(str(ambiente_com_codigo_de_barras["excel"]))
        assert len(sheets["Uso Interno"]) == 1
        assert sheets["Uso Interno"]["Código de Barras"].iloc[0] == "7897274410245"

    def test_modo_explicito_por_parametro_tem_prioridade_sobre_config(
        self, tmp_path, monkeypatch, tmp_db
    ):
        """Passar modo_extracao=... para main() deve valer mesmo se o config disser outra coisa."""
        from PIL import Image

        pasta_imagens = tmp_path / "imagens"
        pasta_imagens.mkdir()
        Image.new("RGB", (4, 4), color="red").save(pasta_imagens / "IMG-1.jpg")

        monkeypatch.setattr(pipeline, "UPLOAD_FOLDER", pasta_imagens)
        monkeypatch.setattr(pipeline, "ARQUIVO_SAIDA_EXCEL", tmp_path / "Relatorio.xlsx")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "log.txt")
        monkeypatch.setattr(pipeline, "LOG_CONSUMO_FILE", tmp_path / "consumo.txt")
        monkeypatch.setattr(pipeline, "CANCEL_FILE", tmp_path / ".cancel")
        # Config diz "ia" mas SEM chave - se o parâmetro não tivesse prioridade,
        # isso derrubaria a execução com erro de API key ausente.
        monkeypatch.setattr(
            pipeline, "carregar_configuracao",
            lambda: {
                "api": {"provider": "gemini", "gemini_api_key": ""},
                "processamento": {"tamanho_lote": 5, "max_workers": 1, "request_delay": 0,
                                  "temperatura": 0.1, "max_tokens": 4000, "timeout": 60,
                                  "modo_extracao": "ia"},
            },
        )

        # Não deve levantar: modo_extracao="sem_ia" não exige API key, mesmo
        # com o config apontando para "ia".
        pipeline.main(modo_extracao="sem_ia")

        log = (tmp_path / "log.txt").read_text(encoding="utf-8")
        assert "IMG-1.jpg" in log


class TestCarregarLogs:
    def test_le_formato_atual_com_timestamp(self, tmp_path, monkeypatch):
        log = tmp_path / "log.txt"
        log.write_text("2026-07-24 23:27:36 - Processado: IMG-1.jpg\n", encoding="utf-8")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", log)
        assert pipeline.carregar_logs() == {"IMG-1.jpg"}

    def test_le_formato_legado_so_com_o_nome(self, tmp_path, monkeypatch):
        log = tmp_path / "log.txt"
        log.write_text("IMG-antigo.jpg\n", encoding="utf-8")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", log)
        assert pipeline.carregar_logs() == {"IMG-antigo.jpg"}

    def test_sem_arquivo_retorna_vazio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "nao_existe.txt")
        assert pipeline.carregar_logs() == set()


class TestListarImagensPendentes:
    """Fonte única de verdade sobre o que é 'novo' - usada pelo pipeline
    (extraction_pipeline.main) e pela rota de processamento
    (routes/processing.py). Antes existiam duas implementações divergentes;
    esta é a que deve valer nos dois lugares."""

    def test_imagem_nao_processada_aparece_como_pendente(self, tmp_path, monkeypatch):
        pasta = tmp_path / "imagens"
        pasta.mkdir()
        (pasta / "IMG-1.jpg").write_bytes(b"x")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "log.txt")
        assert pipeline.listar_imagens_pendentes(str(pasta)) == ["IMG-1.jpg"]

    def test_imagem_ja_processada_e_excluida(self, tmp_path, monkeypatch):
        pasta = tmp_path / "imagens"
        pasta.mkdir()
        (pasta / "IMG-1.jpg").write_bytes(b"x")
        log = tmp_path / "log.txt"
        log.write_text("2026-07-24 10:00:00 - Processado: IMG-1.jpg\n", encoding="utf-8")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", log)
        assert pipeline.listar_imagens_pendentes(str(pasta)) == []

    def test_arquivo_reenviado_com_nome_renomeado_conta_como_novo(self, tmp_path, monkeypatch):
        """Caso real do bug relatado: reenviar a mesma foto (agora salva com
        sufixo pelo upload) deve ser tratado como conteúdo novo a processar."""
        pasta = tmp_path / "imagens"
        pasta.mkdir()
        (pasta / "IMG-1.jpg").write_bytes(b"foto original")
        (pasta / "IMG-1_2.jpg").write_bytes(b"foto reenviada")
        log = tmp_path / "log.txt"
        log.write_text("2026-07-24 10:00:00 - Processado: IMG-1.jpg\n", encoding="utf-8")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", log)
        assert pipeline.listar_imagens_pendentes(str(pasta)) == ["IMG-1_2.jpg"]

    def test_ignora_arquivos_nao_imagem(self, tmp_path, monkeypatch):
        pasta = tmp_path / "imagens"
        pasta.mkdir()
        (pasta / "IMG-1.jpg").write_bytes(b"x")
        (pasta / "conversa.txt").write_bytes(b"texto")
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "log.txt")
        assert pipeline.listar_imagens_pendentes(str(pasta)) == ["IMG-1.jpg"]

    def test_diretorio_inexistente_devolve_vazio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "log.txt")
        assert pipeline.listar_imagens_pendentes(str(tmp_path / "nao_existe")) == []

    def test_usa_upload_folder_por_padrao(self, tmp_path, monkeypatch):
        pasta = tmp_path / "imagens"
        pasta.mkdir()
        (pasta / "IMG-1.jpg").write_bytes(b"x")
        monkeypatch.setattr(pipeline, "UPLOAD_FOLDER", pasta)
        monkeypatch.setattr(pipeline, "LOG_PROCESSADOS_FILE", tmp_path / "log.txt")
        assert pipeline.listar_imagens_pendentes() == ["IMG-1.jpg"]


class TestReanalisarExecucao:
    @pytest.fixture
    def execucao_existente(self, tmp_path, monkeypatch, tmp_db):
        """Uma execução já concluída, com 2 imagens já 'arquivadas' (fora da
        pasta de pendentes) - o caso normal de uma execução bem-sucedida."""
        from PIL import Image

        pasta_arquivadas = tmp_path / "arquivadas"
        pasta_arquivadas.mkdir()
        Image.new("RGB", (4, 4), color="red").save(pasta_arquivadas / "IMG-1.jpg")
        Image.new("RGB", (4, 4), color="blue").save(pasta_arquivadas / "IMG-2.jpg")

        excel = tmp_path / "Relatorio.xlsx"
        avarias = [
            {
                "Produto": "TOMATE", "Quantidade": 1, "Peso": "1kg",
                "Observação da Mensagem": "Nenhuma",
                "Caminho da Imagem": str(pasta_arquivadas / "IMG-1.jpg"),
                "Ver Imagem": str(pasta_arquivadas / "IMG-1.jpg"),
            },
            {
                "Produto": "ALFACE", "Quantidade": 1, "Peso": "0.5kg",
                "Observação da Mensagem": "Nenhuma",
                "Caminho da Imagem": str(pasta_arquivadas / "IMG-2.jpg"),
                "Ver Imagem": str(pasta_arquivadas / "IMG-2.jpg"),
            },
        ]
        pipeline.salvar_relatorio_excel(str(excel), avarias, [], [])

        run_id = tmp_db.iniciar_execucao("processamento", imagens_total=2)
        tmp_db.registrar_itens(run_id, "Avarias", avarias)
        tmp_db.finalizar_execucao(run_id, "concluido", avarias=2, uso_interno=0, erros=0)

        monkeypatch.setattr(pipeline, "ARQUIVO_SAIDA_EXCEL", excel)
        monkeypatch.setattr(
            pipeline, "carregar_configuracao",
            lambda: {
                "api": {"provider": "gemini", "gemini_api_key": "fake-key"},
                "processamento": {"request_delay": 0},
            },
        )
        monkeypatch.setattr(pipeline, "construir_provedor_de_config", lambda cfg: _ProviderFalso())

        return {"run_id": run_id, "excel": excel, "arquivadas": pasta_arquivadas}

    def test_cria_nova_versao_vinculada_a_mesma_linhagem(self, execucao_existente):
        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "TOMATE REANALISADO", "peso": "1kg"}]}}, 10

        import os

        pipeline.ai_extraction.extrair_dados_de_lote = fake_extrair
        resultado = pipeline.reanalisar_execucao(execucao_existente["run_id"])

        assert resultado["sucesso"] is True
        nova_versao = pipeline.db.obter_execucao(resultado["run_id"])
        assert nova_versao["raiz_execucao_id"] == execucao_existente["run_id"]
        assert nova_versao["versao"] == 2

    def test_substitui_linhas_antigas_no_excel_sem_duplicar(self, execucao_existente, monkeypatch):
        import os

        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": f"{nome}-REANALISADO", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        pipeline.reanalisar_execucao(execucao_existente["run_id"])

        from autoavaria.services.report_editing import carregar_todas_sheets

        sheets = carregar_todas_sheets(str(execucao_existente["excel"]))
        produtos = list(sheets["Avarias"]["Produto"])
        assert produtos == ["IMG-1.jpg-REANALISADO", "IMG-2.jpg-REANALISADO"]  # 2 linhas, não 4

    def test_imagem_que_sumiu_do_disco_vira_erro_sem_derrubar_o_resto(self, execucao_existente, monkeypatch):
        import os

        (execucao_existente["arquivadas"] / "IMG-1.jpg").unlink()

        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "OK", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        resultado = pipeline.reanalisar_execucao(execucao_existente["run_id"])

        assert resultado["sucesso"] is True
        assert resultado["erros"] == 1
        assert resultado["avarias"] == 1

    def test_reporta_progresso_por_callback(self, execucao_existente, monkeypatch):
        import os

        def fake_extrair(lote, provider, mensagens):
            nome = os.path.basename(lote[0])
            return {nome: {"tipo": "Avaria", "itens": [{"produto": "OK", "peso": "1kg"}]}}, 10

        monkeypatch.setattr(pipeline.ai_extraction, "extrair_dados_de_lote", fake_extrair)

        chamadas = []
        pipeline.reanalisar_execucao(execucao_existente["run_id"], callback_progresso=lambda info: chamadas.append(info))

        assert len(chamadas) == 2
        assert chamadas[0]["total"] == 2
        assert chamadas[-1]["atual"] == 2
