"""
PIPELINE DE PROCESSAMENTO (orquestração)

Ponto de entrada equivalente ao antigo script extrair-dados.py: carrega a
configuração, varre imagens_para_analisar/, chama a IA em lotes (via
ai_extraction), grava o relatório Excel (via excel_report) e registra o
histórico da execução no banco SQLite (via db). Também expõe a reanálise de
erros usada pela tela de relatório.
"""

import concurrent.futures
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from ..core.paths import (
    ARCHIVE_FOLDER,
    ARQUIVO_SAIDA_EXCEL,
    CONFIG_FILE,
    DATA_ROOT,
    LOG_CONSUMO_FILE,
    LOG_PROCESSADOS_FILE,
    UPLOAD_FOLDER,
)
from . import ai_extraction, catalogo, conversa, db, image_archive
from .ai import construir_provedor_de_config, obter_api_key_do_provedor
from .excel_report import salvar_relatorio_excel
from .extraction_engines import MODO_IA, MODO_SEM_IA, MODOS_DISPONIVEIS, construir_motor
from .report_editing import (
    carregar_todas_sheets,
    fazer_backup,
    remover_linhas_por_caminho_imagem,
    salvar_todas_sheets,
)
from .reports import criar_gerenciador

EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")
MAX_RETRIES = 3
CANCEL_FILE = DATA_ROOT / ".cancel_processing"


def carregar_configuracao() -> Dict[str, Any]:
    """Carrega configurações do arquivo config/config.json."""
    config_padrao = {
        "api": {
            "provider": "gemini",
            "gemini_api_key": "",
            "openai_api_key": "",
            "anthropic_api_key": "",
        },
        "processamento": {
            "modelo_gemini": "gemini-1.5-flash",
            "temperatura": 0.1,
            "max_tokens": 1000,
            "timeout": 30,
        },
    }

    try:
        if CONFIG_FILE.exists():
            print(f"📄 Arquivo de configuração encontrado: {CONFIG_FILE}")
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                provider_name = (config.get("api", {}).get("provider") or "gemini").lower()
                api_key = obter_api_key_do_provedor(config, provider_name)
                if api_key and api_key.strip() and api_key != "SUA_CHAVE_AI_AQUI":
                    print(f"✅ API Key do provedor '{provider_name}' encontrada na configuração")
                else:
                    print(f"⚠️ API Key do provedor '{provider_name}' não encontrada ou inválida")
                return config
        print("⚠️ Nenhum arquivo de configuração encontrado, usando configuração padrão")
        return config_padrao
    except Exception as e:
        print(f"⚠️ Erro ao carregar configuração: {e}")
        return config_padrao


class ProcessingConfig:
    """Configurações centralizadas do processamento, validadas na criação."""

    def __init__(
        self,
        config: Dict[str, Any],
        provider_name: str,
        api_key: str,
        tamanho_lote: int,
        max_workers: int,
        requer_ia: bool = True,
    ):
        # Fallbacks alinhados com config_padrao em services/config_service.py -
        # na prática quase nunca disparam (a config sempre chega com essas
        # chaves preenchidas), mas divergir deles é uma armadilha à toa.
        self.temperatura = config.get("processamento", {}).get("temperatura", 0.1)
        self.max_tokens = config.get("processamento", {}).get("max_tokens", 4000)
        self.timeout = config.get("processamento", {}).get("timeout", 60)
        self._provider_name = provider_name
        self._api_key = api_key
        self._tamanho_lote = tamanho_lote
        self._max_workers = max_workers
        self._requer_ia = requer_ia
        self.validate_settings()

    def validate_settings(self) -> None:
        # No modo sem IA (só código de barras) não há provedor nem chave para
        # validar - o motor não faz nenhuma chamada de IA.
        if self._requer_ia and (
            not self._api_key or self._api_key.strip() == "" or "SUA_CHAVE_AI_AQUI" in self._api_key
        ):
            print("❌ Problemas encontrados na configuração da API:")
            print(f"   - Provedor selecionado: {self._provider_name}")
            print(f"   - API Key: {'Vazia' if not self._api_key or self._api_key.strip() == '' else 'Inválida'}")
            print(f"   - Arquivo de config usado: {CONFIG_FILE}")
            print("💡 Soluções:")
            print("   1. Verifique se o arquivo config/config.json existe")
            print(f"   2. Configure a API Key do provedor '{self._provider_name}' na interface web (aba Configurações)")
            print("   3. Certifique-se de que a chave não está vazia")
            raise ValueError(f"Chave da API do provedor '{self._provider_name}' não configurada. Configure na interface web.")
        if self._tamanho_lote <= 0:
            raise ValueError("Tamanho do lote deve ser maior que zero.")
        if self._max_workers <= 0:
            raise ValueError("Número de workers deve ser maior que zero.")


# ================================
# UTILITÁRIOS E LOGS
# ================================


def verificar_cancelamento() -> bool:
    """Verifica se o processamento foi cancelado."""
    if CANCEL_FILE.exists():
        try:
            CANCEL_FILE.unlink()
        except OSError:
            pass
        return True
    return False


def carregar_logs() -> set:
    """Carrega o conjunto de nomes de arquivos já processados (lê o log_mestre.txt)."""
    if not LOG_PROCESSADOS_FILE.exists():
        return set()
    try:
        arquivos_processados = set()
        with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                # Formato atual: "2026-07-23 23:27:36 - Processado: IMG-0001.jpg"
                if " - Processado: " in linha:
                    arquivos_processados.add(linha.split(" - Processado: ")[-1])
                else:
                    # Formato legado: apenas o nome do arquivo
                    arquivos_processados.add(linha)
        return arquivos_processados
    except IOError as e:
        print(f"⚠️ Erro ao ler log de arquivos processados: {e}")
        return set()


def listar_imagens_pendentes(diretorio_imagens: Optional[str] = None) -> list:
    """Lista, em ordem, os arquivos de imagem de `diretorio_imagens` que ainda
    não estão em log_mestre.txt.

    Fonte única desta verificação — antes existiam duas implementações
    quase idênticas (uma aqui, outra em routes/processing.py), e a de lá
    comparava nome de arquivo contra a LINHA INTEIRA do log (incluindo o
    timestamp), o que nunca dava match e fazia aquele contador de "novas
    imagens" mentir. Consolidado para as duas nunca mais divergirem.
    """
    diretorio_imagens = diretorio_imagens or str(UPLOAD_FOLDER)
    if not os.path.isdir(diretorio_imagens):
        return []
    processadas = carregar_logs()
    return sorted(
        f
        for f in os.listdir(diretorio_imagens)
        if f.lower().endswith(EXTENSOES_IMAGEM) and f not in processadas
    )


def registrar_log(nome_arquivo: str) -> None:
    """Registra um arquivo como processado no log."""
    try:
        LOG_PROCESSADOS_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PROCESSADOS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} - Processado: {nome_arquivo}\n")
    except Exception as e:
        print(f"❌ Erro ao salvar log de arquivos: {e}")


def registrar_consumo_log(total_tokens: int, detalhes_extras: str = "") -> None:
    """Salva o consumo total de tokens com data e hora em um arquivo de log."""
    try:
        LOG_CONSUMO_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - Tokens consumidos: {total_tokens:,}"
        if detalhes_extras:
            log_entry += f" - {detalhes_extras}"
        with open(LOG_CONSUMO_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
        print(f"📝 Log de consumo salvo: {total_tokens:,} tokens")
    except Exception as e:
        print(f"❌ Erro inesperado ao salvar log: {e}")


def _linha_de_erro(nome_arquivo: str, detalhe: str, mensagens_por_imagem: Dict[str, str], diretorio_imagens: str) -> Dict[str, str]:
    """Monta uma linha da aba "Erros de Análise" para um arquivo que não pôde ser analisado."""
    caminho_absoluto = os.path.abspath(os.path.join(diretorio_imagens, nome_arquivo))
    return {
        "Arquivo": nome_arquivo,
        "Detalhes do Erro": detalhe,
        "Observação da Mensagem": mensagens_por_imagem.get(nome_arquivo, "Nenhuma"),
        "Caminho da Imagem": caminho_absoluto,
        "Ver Imagem": caminho_absoluto,
    }


def _resolver_caminho_imagem(caminho_registrado: str) -> Optional[str]:
    """Resolve o caminho histórico de uma imagem pendente ou arquivada.

    Execuções antigas registram o caminho da pasta de pendentes, embora a
    imagem seja movida para ARCHIVE_FOLDER ao concluir. Preferimos o caminho
    gravado e, se ele não existir, procuramos pelo nome nas pastas oficiais.
    """
    if not caminho_registrado:
        return None
    caminho_registrado = os.path.abspath(caminho_registrado)
    if os.path.isfile(caminho_registrado):
        return caminho_registrado

    nome = os.path.basename(caminho_registrado)
    for pasta in (UPLOAD_FOLDER, ARCHIVE_FOLDER):
        candidato = os.path.abspath(os.path.join(str(pasta), nome))
        if os.path.isfile(candidato):
            return candidato
    return None


def _persistir_lote(run_id: Optional[int], avarias, usos_internos, erros) -> None:
    """Grava os resultados de UM lote no Excel e no banco.

    Chamado a cada lote (em vez de só no fim de tudo) para que uma
    interrupção no meio do processamento não descarte o trabalho já feito
    nem deixe imagens marcadas como processadas sem dado correspondente.
    """
    if not (avarias or usos_internos or erros):
        return

    salvar_relatorio_excel(str(ARQUIVO_SAIDA_EXCEL), avarias, usos_internos, erros)

    if run_id is not None:
        db.registrar_itens(run_id, "Avarias", avarias)
        db.registrar_itens(run_id, "Uso Interno", usos_internos)
        db.registrar_itens(run_id, "Erros de Análise", erros)


# ================================
# PIPELINE PRINCIPAL
# ================================


def main(
    modo_extracao: Optional[str] = None,
    callback_progresso: Optional[callable] = None,
) -> bool:
    """Processa as imagens novas em imagens_para_analisar/ e atualiza o relatório mestre.

    Args:
        modo_extracao: "ia" (padrão), "sem_ia" (só código de barras, sem custo
            de IA) ou "hibrido" (código de barras primeiro, IA no que faltar).
            Se omitido, usa `processamento.modo_extracao` do config.json.
    """
    print("\n" + "=" * 70)
    print("🚀 ANALISADOR MESTRE DE IMAGENS E MENSAGENS")
    print(f"⏰ Início: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 70 + "\n")

    run_id: Optional[int] = None
    try:
        config = carregar_configuracao()
        provider_name = (config.get("api", {}).get("provider") or "gemini").lower()
        api_key = obter_api_key_do_provedor(config, provider_name)
        tamanho_lote = config.get("processamento", {}).get("tamanho_lote", 12)
        max_workers = config.get("processamento", {}).get("max_workers", 3)
        request_delay = config.get("processamento", {}).get("request_delay", 2.0)
        modo_extracao = (modo_extracao or config.get("processamento", {}).get("modo_extracao") or MODO_IA).lower()
        requer_ia = modo_extracao != MODO_SEM_IA

        processing_config = ProcessingConfig(
            config, provider_name, api_key, tamanho_lote, max_workers, requer_ia=requer_ia
        )

        print("⚙️  CONFIGURAÇÕES DE PROCESSAMENTO:")
        print("-" * 50)
        print(f"   🎯 Modo de extração: {MODOS_DISPONIVEIS.get(modo_extracao, modo_extracao)}")
        print(f"   📦 Tamanho do lote: {tamanho_lote} imagens por requisição")
        print(f"   ⚡ Workers paralelos: {max_workers} threads")
        print(f"   ⏱️  Delay entre requisições: {request_delay}s")
        if requer_ia:
            print(f"   🤖 Provedor: {provider_name} | Modelo: {config.get('api', {}).get('modelo_selecionado', '?')}")
            print(f"   🌡️  Temperatura: {processing_config.temperatura}")
            print(f"   📊 Max Tokens: {processing_config.max_tokens}")
        print("-" * 50 + "\n")

        if not UPLOAD_FOLDER.exists():
            UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            print(f"📁 Diretório criado: {UPLOAD_FOLDER}")
            print("⚠️  ATENÇÃO: Adicione suas imagens (.jpg, .png) e o arquivo .txt de mensagens")
            return True

        imagens_processadas = carregar_logs()
        print(f"📝 Histórico: {len(imagens_processadas)} arquivos já processados anteriormente\n")

        provider = None
        if requer_ia:
            print(f"🔑 Configurando acesso à API do provedor '{provider_name}'...")
            provider = construir_provedor_de_config(config)
            print(f"✅ {provider.nome_provedor} configurado e pronto para uso\n")

        dias_para_reverificar = config.get("processamento", {}).get(
            "dias_para_reverificar_peso", catalogo.DIAS_PARA_REVERIFICAR_PADRAO
        )
        motor = construir_motor(modo_extracao, provider, dias_para_reverificar=dias_para_reverificar)
        print(f"⚙️  Motor de extração ativo: {motor.nome}\n")

        diretorio_imagens = str(UPLOAD_FOLDER)
        imagens_para_processar = [
            os.path.join(diretorio_imagens, f)
            for f in listar_imagens_pendentes(diretorio_imagens)
        ]

        if not imagens_para_processar:
            print("✅ PROCESSAMENTO COMPLETO: Todas as imagens já foram analisadas\n")
            return True

        run_id = db.iniciar_execucao("processamento", imagens_total=len(imagens_para_processar))

        lotes_de_imagens = [
            imagens_para_processar[i : i + tamanho_lote]
            for i in range(0, len(imagens_para_processar), tamanho_lote)
        ]

        print("📊 ESTATÍSTICAS DE PROCESSAMENTO:")
        print("-" * 50)
        print(f"   🖼️  Novas imagens detectadas: {len(imagens_para_processar)}")
        print(f"   📦 Lotes criados: {len(lotes_de_imagens)} (máx. {tamanho_lote} imagens/lote)")
        print("-" * 50 + "\n")

        contextos = conversa.mapear_contextos(diretorio_imagens)
        mensagens_por_imagem = {img: ctx.texto for img, ctx in contextos.items() if ctx.texto}
        novas_avarias, novos_usos_internos, novos_erros = [], [], []
        total_tokens_consumidos = 0

        print(f"🔄 INICIANDO ANÁLISE ({motor.nome})...")
        if requer_ia:
            print("   Prioridade: Texto > Imagem (otimizado para precisão)\n")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_lote = {}
            for idx, lote in enumerate(lotes_de_imagens):
                if idx > 0 and requer_ia:
                    time.sleep(request_delay)
                future_to_lote[executor.submit(motor.processar_lote, lote, contextos)] = lote

            with tqdm(total=len(imagens_para_processar), desc="Analisando", unit="img") as pbar:
                for future in concurrent.futures.as_completed(future_to_lote):
                    cancelamento_solicitado = verificar_cancelamento()

                    lote_processado_caminhos = future_to_lote[future]
                    lote_processado_nomes = [os.path.basename(p) for p in lote_processado_caminhos]

                    # Resultados DESTE lote, isolados: eles são gravados em disco
                    # antes de o lote ser marcado como processado (ver abaixo).
                    avarias_lote, usos_lote, erros_lote = [], [], []
                    try:
                        resultados_lote, tokens_do_lote = future.result()
                        total_tokens_consumidos += tokens_do_lote
                        for nome_arquivo in lote_processado_nomes:
                            ai_extraction.processar_resultado_arquivo(
                                nome_arquivo, resultados_lote, mensagens_por_imagem, diretorio_imagens,
                                avarias_lote, usos_lote, erros_lote,
                            )
                    except Exception as e:
                        print(f"❌ Erro crítico no processamento do lote: {e}")
                        # Registrar como erro (em vez de sumir): assim os arquivos
                        # aparecem na aba "Erros de Análise" e podem ser reanalisados.
                        for nome in lote_processado_nomes:
                            erros_lote.append(_linha_de_erro(nome, f"Erro no processamento do lote: {e}",
                                                             mensagens_por_imagem, diretorio_imagens))

                    # ORDEM IMPORTA: gravar primeiro, marcar como processado depois.
                    # Se o processo for interrompido/morto no meio da execução, os
                    # arquivos ainda não gravados continuam "não processados" e são
                    # reanalisados na próxima execução, em vez de sumirem para sempre.
                    _persistir_lote(run_id, avarias_lote, usos_lote, erros_lote)
                    for nome in lote_processado_nomes:
                        registrar_log(nome)

                    # Arquivar (mover + recomprimir) as imagens processadas com
                    # sucesso, para saírem da pasta de pendentes. Imagens com
                    # erro ficam onde estão - reanalisar_erros() precisa achá-las
                    # por nome em diretorio_imagens para poder reprocessá-las.
                    nomes_com_erro_lote = {erro["Arquivo"] for erro in erros_lote}
                    for nome in lote_processado_nomes:
                        if nome not in nomes_com_erro_lote:
                            image_archive.arquivar_imagem(nome, diretorio_imagens, ARCHIVE_FOLDER)

                    pbar.update(len(lote_processado_nomes))

                    if callback_progresso:
                        callback_progresso({
                            "atual": pbar.n,
                            "total": len(imagens_para_processar),
                            "arquivo": lote_processado_nomes[-1] if lote_processado_nomes else "",
                        })

                    if cancelamento_solicitado:
                        # Este future já terminou (as_completed só o entrega
                        # nesse ponto): persistimos o lote antes de encerrar,
                        # para não pagar pela análise e descartar seu resultado.
                        print("\n⚠️ Processamento cancelado após salvar o lote concluído")
                        executor.shutdown(wait=False, cancel_futures=True)
                        db.finalizar_execucao(
                            run_id,
                            "cancelado",
                            len(novas_avarias) + len(avarias_lote),
                            len(novos_usos_internos) + len(usos_lote),
                            len(novos_erros) + len(erros_lote),
                            total_tokens_consumidos,
                            "Cancelado pelo usuário",
                        )
                        return False

                    novas_avarias.extend(avarias_lote)
                    novos_usos_internos.extend(usos_lote)
                    novos_erros.extend(erros_lote)

        db.registrar_consumo_tokens(run_id, total_tokens_consumidos, f"{len(imagens_para_processar)} imagens")
        db.finalizar_execucao(
            run_id, "concluido", len(novas_avarias), len(novos_usos_internos),
            len(novos_erros), total_tokens_consumidos,
        )

        total_imagens = len(imagens_para_processar)
        detalhes = (
            f"Processamento de {total_imagens} imagens, {len(novas_avarias)} avarias, "
            f"{len(novos_usos_internos)} uso interno, {len(novos_erros)} erros"
        )
        registrar_consumo_log(total_tokens_consumidos, detalhes)

        print("\n" + "=" * 70)
        print("✅ ANÁLISE CONCLUÍDA COM SUCESSO!")
        print(f"   ✅ Avarias identificadas: {len(novas_avarias)}")
        print(f"   🏭 Uso interno identificado: {len(novos_usos_internos)}")
        print(f"   ❌ Erros encontrados: {len(novos_erros)}")
        print(f"   🪙 Total de tokens consumidos: {total_tokens_consumidos:,}")
        print(f"   💾 Relatório salvo em: {ARQUIVO_SAIDA_EXCEL}")
        print("=" * 70 + "\n")
        return True

    except Exception as e:
        print("\n❌ ERRO CRÍTICO na execução principal:")
        print(f"   Detalhes: {e}")
        import traceback

        traceback.print_exc()
        if run_id is not None:
            db.finalizar_execucao(run_id, "erro", mensagem=str(e))
        return False


def reanalisar_erros(
    diretorio_imagens: Optional[str] = None,
    arquivo_excel: Optional[str] = None,
    callback_progresso: Optional[callable] = None,
) -> Dict[str, Any]:
    """Reanalisa apenas os itens que falharam na análise anterior."""
    print("\n🔄 INICIANDO REANÁLISE DE ERROS")
    print("=" * 60)

    diretorio_imagens = diretorio_imagens or str(UPLOAD_FOLDER)
    arquivo_excel = arquivo_excel or str(ARQUIVO_SAIDA_EXCEL)

    config = carregar_configuracao()
    request_delay = config.get("processamento", {}).get("request_delay", 2.0)

    run_id: Optional[int] = None
    try:
        gerenciador = criar_gerenciador(arquivo_excel)
        arquivos_com_erro = gerenciador.obter_arquivos_com_erro()
        run_id = db.iniciar_execucao("reanalise", imagens_total=len(arquivos_com_erro))

        if not arquivos_com_erro:
            print("✅ Nenhum erro pendente para reanalisar")
            db.finalizar_execucao(run_id, "concluido", mensagem="Nenhum erro pendente")
            return {
                "sucesso": True, "total_arquivos": 0, "processados": 0,
                "corrigidos": 0, "ainda_com_erro": 0, "detalhes": [],
            }

        print(f"📋 Encontrados {len(arquivos_com_erro)} arquivos com erro")

        provider = construir_provedor_de_config(config)
        print(f"✅ {provider.nome_provedor} configurado para a reanálise")
        mensagens_por_imagem = conversa.mapear_mensagens_para_imagens(diretorio_imagens)

        itens_corrigidos = 0
        ainda_com_erro = 0
        tokens_totais = 0
        avarias_da_execucao = 0
        usos_da_execucao = 0
        detalhes_resultado = []
        erros_da_execucao = []

        for idx, nome_arquivo in enumerate(arquivos_com_erro, 1):
            if callback_progresso:
                callback_progresso({"atual": idx, "total": len(arquivos_com_erro), "arquivo": nome_arquivo})

            print(f"\n[{idx}/{len(arquivos_com_erro)}] Reanalisando: {nome_arquivo}")
            caminho_imagem = os.path.join(diretorio_imagens, nome_arquivo)

            if not os.path.exists(caminho_imagem):
                print(f"   ⚠️ Arquivo não encontrado: {caminho_imagem}")
                detalhes_resultado.append({"arquivo": nome_arquivo, "status": "falha", "motivo": "Arquivo não encontrado"})
                erros_da_execucao.append(_linha_de_erro(
                    nome_arquivo, "Arquivo não encontrado", mensagens_por_imagem, diretorio_imagens
                ))
                ainda_com_erro += 1
                gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", "Arquivo não encontrado")
                continue

            try:
                resultado, tokens = ai_extraction.extrair_dados_de_lote([caminho_imagem], provider, mensagens_por_imagem)
                tokens_totais += tokens
                dados = resultado.get(nome_arquivo)

                if dados and dados.get("tipo") != "Erro":
                    print(f"   ✅ Corrigido com sucesso: {dados.get('tipo')}")
                    tipo = dados.get("tipo")
                    novas_avarias, novos_usos_internos, novos_erros = [], [], []

                    ai_extraction.processar_resultado_arquivo(
                        nome_arquivo, resultado, mensagens_por_imagem, diretorio_imagens,
                        novas_avarias, novos_usos_internos, novos_erros,
                    )

                    salvar_relatorio_excel(arquivo_excel, novas_avarias, novos_usos_internos, novos_erros)
                    if novos_erros:
                        erros_da_execucao.extend(novos_erros)
                        ainda_com_erro += 1
                        motivo = novos_erros[0].get("Detalhes do Erro", "Resultado inválido")
                        gerenciador.marcar_erro_como_reprocessado(nome_arquivo, sucesso=False)
                        detalhes_resultado.append({"arquivo": nome_arquivo, "status": "falha", "motivo": motivo})
                        gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", motivo)
                    else:
                        db.registrar_itens(run_id, "Avarias", novas_avarias)
                        db.registrar_itens(run_id, "Uso Interno", novos_usos_internos)
                        avarias_da_execucao += len(novas_avarias)
                        usos_da_execucao += len(novos_usos_internos)

                        gerenciador.marcar_erro_como_reprocessado(nome_arquivo, sucesso=True)
                        image_archive.arquivar_imagem(nome_arquivo, diretorio_imagens, ARCHIVE_FOLDER)

                        itens_corrigidos += 1
                        detalhes_resultado.append({"arquivo": nome_arquivo, "status": "sucesso", "tipo": tipo})
                        gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "sucesso", f"Tipo: {tipo}")
                else:
                    erro_detalhes = dados.get("detalhes", "Erro desconhecido") if dados else "Sem resposta"
                    print(f"   ❌ Ainda com erro: {erro_detalhes}")
                    ainda_com_erro += 1
                    detalhes_resultado.append({"arquivo": nome_arquivo, "status": "falha", "motivo": erro_detalhes})
                    gerenciador.marcar_erro_como_reprocessado(nome_arquivo, sucesso=False)
                    gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", erro_detalhes)
                    erros_da_execucao.append(_linha_de_erro(
                        nome_arquivo, erro_detalhes, mensagens_por_imagem, diretorio_imagens
                    ))

                if idx < len(arquivos_com_erro):
                    time.sleep(request_delay)

            except Exception as e:
                print(f"   ❌ Erro ao reanalisar: {e}")
                ainda_com_erro += 1
                detalhes_resultado.append({"arquivo": nome_arquivo, "status": "falha", "motivo": str(e)})
                gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", str(e))
                erros_da_execucao.append(_linha_de_erro(
                    nome_arquivo, str(e), mensagens_por_imagem, diretorio_imagens
                ))

        print("\n" + "=" * 60)
        print("✅ REANÁLISE CONCLUÍDA")
        print(f"   📊 Total de arquivos: {len(arquivos_com_erro)}")
        print(f"   ✅ Corrigidos: {itens_corrigidos}")
        print(f"   ❌ Ainda com erro: {ainda_com_erro}")
        print("=" * 60)

        db.registrar_consumo_tokens(run_id, tokens_totais, f"Reanálise de {len(arquivos_com_erro)} arquivos")
        db.registrar_itens(run_id, "Erros de Análise", erros_da_execucao)
        db.finalizar_execucao(
            run_id,
            "concluido",
            avarias=avarias_da_execucao,
            uso_interno=usos_da_execucao,
            erros=ainda_com_erro,
            tokens_consumidos=tokens_totais,
        )

        return {
            "sucesso": True,
            "total_arquivos": len(arquivos_com_erro),
            "processados": len(arquivos_com_erro),
            "corrigidos": itens_corrigidos,
            "ainda_com_erro": ainda_com_erro,
            "detalhes": detalhes_resultado,
        }

    except Exception as e:
        print(f"\n❌ Erro crítico na reanálise: {e}")
        import traceback

        traceback.print_exc()
        if run_id is not None:
            db.finalizar_execucao(run_id, "erro", mensagem=str(e))
        return {
            "sucesso": False, "erro": str(e), "total_arquivos": 0,
            "processados": 0, "corrigidos": 0, "ainda_com_erro": 0, "detalhes": [],
        }


CATEGORIAS_REANALISE = ("Avarias", "Uso Interno", "Erros de Análise")


def _validar_categorias(categorias) -> Optional[List[str]]:
    """Valida o filtro de categorias da reanálise seletiva.

    Retorna a lista normalizada ou None (sem filtro = tudo). Levanta
    ValueError para categoria desconhecida ou lista vazia explícita.
    """
    if categorias is None:
        return None
    if not isinstance(categorias, (list, tuple)) or not categorias:
        raise ValueError("Nenhuma categoria selecionada para reanálise")
    desconhecidas = [c for c in categorias if c not in CATEGORIAS_REANALISE]
    if desconhecidas:
        raise ValueError(f"Categorias inválidas para reanálise: {desconhecidas}")
    return list(categorias)


def _item_db_para_linha(categoria: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um item do banco (colunas report_items) para linha de Excel.

    É o inverso de `db.registrar_itens`: permite copiar itens NÃO
    selecionados para a nova versão sem passar pela IA.
    """
    observacao = item.get("observacao_mensagem")
    caminho = item.get("caminho_imagem")
    if categoria == "Erros de Análise":
        return {
            "Arquivo": item.get("produto"),
            "Detalhes do Erro": item.get("detalhes"),
            "Observação da Mensagem": observacao,
            "Caminho da Imagem": caminho,
            "Ver Imagem": caminho,
        }
    if categoria == "Uso Interno":
        return {
            "Produto": item.get("produto"),
            "Quantidade": item.get("quantidade"),
            "Marca": item.get("marca"),
            "Código de Barras": item.get("codigo_barras"),
            "Observação da Mensagem": observacao,
            "Caminho da Imagem": caminho,
            "Ver Imagem": caminho,
        }
    return {
        "Produto": item.get("produto"),
        "Quantidade": item.get("quantidade"),
        "Peso": item.get("peso"),
        "Observação da Mensagem": observacao,
        "Caminho da Imagem": caminho,
        "Ver Imagem": caminho,
    }


def reanalisar_execucao(
    run_id: int,
    arquivo_excel: Optional[str] = None,
    callback_progresso: Optional[callable] = None,
    categorias: Optional[List[str]] = None,
    item_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Reanalisa imagens de uma execução já concluída, criando uma nova versão.

    Sem filtros, reprocessa TODOS os itens (comportamento original). Com
    `categorias` (ex.: ["Erros de Análise"]) ou `item_ids` (ids do banco),
    reprocessa só a seleção: os demais itens são COPIADOS para a nova versão,
    de modo que cada versão continua representando a execução inteira.

    `item_ids` tem precedência sobre `categorias` quando ambos são dados.
    Diferente de `reanalisar_erros` (só erro do Excel mestre, sem versão),
    esta função sempre versiona (ver versionamento em services/db.py).
    """
    print(f"\n🔄 INICIANDO REANÁLISE DA EXECUÇÃO #{run_id}")
    print("=" * 60)

    arquivo_excel = arquivo_excel or str(ARQUIVO_SAIDA_EXCEL)
    config = carregar_configuracao()
    request_delay = config.get("processamento", {}).get("request_delay", 2.0)

    execucao = db.obter_execucao(run_id)
    if not execucao:
        raise ValueError(f"Execução #{run_id} não encontrada")

    raiz_execucao_id = execucao["raiz_execucao_id"] or execucao["id"]
    itens = execucao["itens"]

    # ---- Seleção: um item, vários ou todos ----
    categorias_filtro = _validar_categorias(categorias)
    if item_ids is not None:
        if not isinstance(item_ids, (list, tuple)) or not item_ids:
            raise ValueError("Nenhum item selecionado para reanálise")
        ids_validos = {item["id"] for item in itens}
        desconhecidos = [i for i in item_ids if i not in ids_validos]
        if desconhecidos:
            raise ValueError(f"Itens não pertencem à execução #{run_id}: {desconhecidos}")
        itens_alvo = [item for item in itens if item["id"] in set(item_ids)]
    elif categorias_filtro is not None:
        itens_alvo = [item for item in itens if item.get("categoria") in categorias_filtro]
    else:
        itens_alvo = list(itens)

    if not itens_alvo:
        raise ValueError("A seleção não contém itens para reanálise")

    # Itens com imagem vão para a IA; sem caminho não há o que reanalisar e
    # são preservados como estão na nova versão.
    com_imagem = [item for item in itens_alvo if item.get("caminho_imagem")]
    sem_imagem = [item for item in itens_alvo if not item.get("caminho_imagem")]
    caminhos_alvo = {item["caminho_imagem"] for item in com_imagem}

    # Uma mesma imagem pode ter gerado MAIS DE UMA linha na análise original
    # (ex.: uma foto de um palete com 2 produtos avariados vira 2 linhas em
    # "Avarias", ambas com o mesmo "caminho_imagem"). Deduplicar por caminho
    # aqui garante que a IA seja chamada uma única vez por imagem - do
    # contrário a mesma imagem seria reanalisada 2x e os resultados de cada
    # chamada seriam somados, duplicando/inflando os dados dela.
    itens_por_caminho: Dict[str, Dict[str, Any]] = {}
    for item in com_imagem:
        itens_por_caminho.setdefault(item["caminho_imagem"], item)
    itens_unicos = list(itens_por_caminho.values())

    # Preservados: tudo da execução que NÃO foi selecionado (mais os
    # selecionados sem imagem) — copiados intactos para a nova versão.
    preservados = [item for item in itens if item.get("caminho_imagem") not in caminhos_alvo]
    preservados += sem_imagem

    novo_run_id = db.iniciar_reanalise_de_execucao(raiz_execucao_id, imagens_total=len(itens_unicos))

    try:
        if not itens_unicos:
            for categoria in CATEGORIAS_REANALISE:
                db.registrar_itens(novo_run_id, categoria, [
                    _item_db_para_linha(categoria, item)
                    for item in preservados
                    if item.get("categoria") == categoria
                ])
            db.finalizar_execucao(novo_run_id, "concluido", mensagem="Nenhuma imagem com caminho registrado para reanálise; itens preservados")
            return {"sucesso": True, "run_id": novo_run_id, "total_arquivos": 0, "avarias": 0, "uso_interno": 0, "erros": 0,
                    "selecionados": len(itens_alvo), "preservados": len(preservados), "sem_imagem": len(sem_imagem),
                    "categorias": categorias_filtro}

        provider = construir_provedor_de_config(config)
        print(f"✅ {provider.nome_provedor} configurado para a reanálise")

        # Reaproveita a correlação de mensagem já gravada na execução original
        # em vez de tentar reler um conversa.txt que pode nem existir mais
        # perto de imagens já arquivadas há muito tempo. Uma linha
        # representante por imagem única basta - todas as linhas da mesma
        # imagem descrevem a mesma foto/mensagem.
        mensagens_por_imagem = {
            os.path.basename(item["caminho_imagem"]): item["observacao_mensagem"]
            for item in itens_unicos
            if item.get("observacao_mensagem") and item["observacao_mensagem"] not in ("Nenhuma", "N/A")
        }

        caminhos_originais = set(itens_por_caminho.keys())
        novas_avarias, novos_usos_internos, novos_erros = [], [], []
        tokens_totais = 0

        for idx, item in enumerate(itens_unicos, 1):
            caminho_registrado = item["caminho_imagem"]
            nome_arquivo = os.path.basename(caminho_registrado)
            caminho_imagem = _resolver_caminho_imagem(caminho_registrado)

            if callback_progresso:
                callback_progresso({"atual": idx, "total": len(itens_unicos), "arquivo": nome_arquivo})

            if not caminho_imagem:
                novos_erros.append({
                    "Arquivo": nome_arquivo,
                    "Detalhes do Erro": "Arquivo de imagem não encontrado para reanálise",
                    "Observação da Mensagem": mensagens_por_imagem.get(nome_arquivo, "Nenhuma"),
                    "Caminho da Imagem": caminho_registrado,
                    "Ver Imagem": caminho_registrado,
                })
            else:
                try:
                    resultado, tokens = ai_extraction.extrair_dados_de_lote([caminho_imagem], provider, mensagens_por_imagem)
                    tokens_totais += tokens
                    ai_extraction.processar_resultado_arquivo(
                        nome_arquivo, resultado, mensagens_por_imagem, os.path.dirname(caminho_imagem),
                        novas_avarias, novos_usos_internos, novos_erros,
                    )
                except Exception as e:
                    novos_erros.append({
                        "Arquivo": nome_arquivo,
                        "Detalhes do Erro": f"Erro na reanálise: {e}",
                        "Observação da Mensagem": mensagens_por_imagem.get(nome_arquivo, "Nenhuma"),
                        "Caminho da Imagem": caminho_imagem,
                        "Ver Imagem": caminho_imagem,
                    })

            if idx < len(itens_unicos):
                time.sleep(request_delay)

        # Só remove as linhas antigas do Excel DEPOIS de ter os novos
        # resultados prontos (nem que seja tudo erro) - uma queda no meio do
        # processo nunca deixa o relatório sem as linhas de uma versão válida.
        fazer_backup(arquivo_excel)
        sheets_atuais = carregar_todas_sheets(arquivo_excel) if os.path.exists(arquivo_excel) else {}
        sheets_sem_antigas = remover_linhas_por_caminho_imagem(sheets_atuais, caminhos_originais)
        if sheets_sem_antigas:
            salvar_todas_sheets(arquivo_excel, sheets_sem_antigas)

        salvar_relatorio_excel(arquivo_excel, novas_avarias, novos_usos_internos, novos_erros)
        db.registrar_itens(novo_run_id, "Avarias", novas_avarias)
        db.registrar_itens(novo_run_id, "Uso Interno", novos_usos_internos)
        db.registrar_itens(novo_run_id, "Erros de Análise", novos_erros)
        # A nova versão representa a execução inteira: copia os itens que
        # ficaram fora da seleção sem passar pela IA.
        for categoria in CATEGORIAS_REANALISE:
            linhas_preservadas = [
                _item_db_para_linha(categoria, item)
                for item in preservados
                if item.get("categoria") == categoria
            ]
            db.registrar_itens(novo_run_id, categoria, linhas_preservadas)
        db.registrar_consumo_tokens(novo_run_id, tokens_totais, f"Reanálise de {len(itens_unicos)} imagens")
        db.finalizar_execucao(
            novo_run_id, "concluido", len(novas_avarias), len(novos_usos_internos),
            len(novos_erros), tokens_totais,
        )

        print(f"✅ REANÁLISE DA EXECUÇÃO #{run_id} CONCLUÍDA -> nova versão #{novo_run_id}")
        return {
            "sucesso": True, "run_id": novo_run_id, "total_arquivos": len(itens_unicos),
            "avarias": len(novas_avarias), "uso_interno": len(novos_usos_internos), "erros": len(novos_erros),
            "selecionados": len(itens_alvo), "preservados": len(preservados),
            "sem_imagem": len(sem_imagem),
            "categorias": categorias_filtro,
        }

    except Exception as e:
        print(f"\n❌ Erro crítico na reanálise da execução #{run_id}: {e}")
        import traceback

        traceback.print_exc()
        db.finalizar_execucao(novo_run_id, "erro", mensagem=str(e))
        return {"sucesso": False, "erro": str(e), "run_id": novo_run_id}


def reanalisar_selecao_mestre(
    imagens=None,
    categorias=None,
    diretorio_imagens: Optional[str] = None,
    arquivo_excel: Optional[str] = None,
    callback_progresso: Optional[callable] = None,
) -> Dict[str, Any]:
    """Reanalisa imagens do relatório mestre (Excel), por seleção.

    Usado pelas telas de exibição (Relatório) e edição geral (Editar Dados),
    que mostram o Excel acumulado sem vínculo com uma execução: `imagens`
    (nomes de arquivo) tem precedência; sem elas, `categorias` (ex.:
    ["Avarias"]) deriva as imagens das respectivas abas do Excel. Sem nenhum
    dos dois, levanta ValueError — reanalisar "tudo do mestre" sem seleção
    seria caro e quase nunca intencional (para isso, use a reanálise por
    execução no Histórico).

    Cada imagem é reprocessada 1x pela IA e suas linhas antigas (todas as
    abas) são substituídas pelas novas; sucesso arquiva a imagem.
    """
    print("\n🔄 INICIANDO REANÁLISE SELECIONADA DO MESTRE")
    print("=" * 60)

    diretorio_imagens = diretorio_imagens or str(UPLOAD_FOLDER)
    arquivo_excel = arquivo_excel or str(ARQUIVO_SAIDA_EXCEL)
    categorias_filtro = _validar_categorias(categorias)

    alvos: List[str] = []
    if imagens:
        for entrada in imagens:
            nome = os.path.basename(str(entrada or "").strip())
            if nome and nome not in alvos:
                alvos.append(nome)
    elif categorias_filtro is not None:
        sheets = carregar_todas_sheets(arquivo_excel) if os.path.exists(arquivo_excel) else {}
        for sheet in categorias_filtro:
            df = sheets.get(sheet)
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                caminho = row.get("Caminho da Imagem")
                nome = os.path.basename(str(caminho).strip()) if isinstance(caminho, str) and caminho.strip() not in ("", "N/A", "-", "nan") else ""
                if not nome:
                    arquivo = row.get("Arquivo")
                    nome = os.path.basename(str(arquivo).strip()) if isinstance(arquivo, str) and arquivo.strip() else ""
                if nome and nome not in alvos:
                    alvos.append(nome)

    if not alvos:
        raise ValueError("Nenhuma imagem selecionada para reanálise")

    config = carregar_configuracao()
    request_delay = config.get("processamento", {}).get("request_delay", 2.0)
    run_id = db.iniciar_execucao("reanalise", imagens_total=len(alvos))
    gerenciador = criar_gerenciador(arquivo_excel)

    try:
        provider = construir_provedor_de_config(config)
        mensagens_por_imagem = conversa.mapear_mensagens_para_imagens(diretorio_imagens)

        corrigidos = ainda_com_erro = tokens_totais = 0
        avarias_total = usos_total = 0
        detalhes, erros_exec = [], []
        fazer_backup(arquivo_excel)

        for idx, nome_arquivo in enumerate(alvos, 1):
            if callback_progresso:
                callback_progresso({"atual": idx, "total": len(alvos), "arquivo": nome_arquivo})
            caminho_imagem = _resolver_caminho_imagem(os.path.join(diretorio_imagens, nome_arquivo))

            if not caminho_imagem:
                ainda_com_erro += 1
                detalhes.append({"arquivo": nome_arquivo, "status": "falha", "motivo": "Arquivo não encontrado"})
                erros_exec.append(_linha_de_erro(nome_arquivo, "Arquivo não encontrado", mensagens_por_imagem, diretorio_imagens))
                gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", "Arquivo não encontrado")
                continue

            try:
                resultado, tokens = ai_extraction.extrair_dados_de_lote([caminho_imagem], provider, mensagens_por_imagem)
                tokens_totais += tokens
                novas_avarias, novos_usos, novos_erros = [], [], []
                ai_extraction.processar_resultado_arquivo(
                    nome_arquivo, resultado, mensagens_por_imagem, os.path.dirname(caminho_imagem),
                    novas_avarias, novos_usos, novos_erros,
                )
                sheets_atuais = carregar_todas_sheets(arquivo_excel) if os.path.exists(arquivo_excel) else {}
                sheets_limpas = remover_linhas_por_caminho_imagem(sheets_atuais, {caminho_imagem, os.path.join(diretorio_imagens, nome_arquivo)})
                if sheets_limpas:
                    salvar_todas_sheets(arquivo_excel, sheets_limpas)
                salvar_relatorio_excel(arquivo_excel, novas_avarias, novos_usos, novos_erros)

                if novos_erros and not (novas_avarias or novos_usos):
                    ainda_com_erro += 1
                    motivo = novos_erros[0].get("Detalhes do Erro", "Resultado inválido")
                    detalhes.append({"arquivo": nome_arquivo, "status": "falha", "motivo": motivo})
                    erros_exec.extend(novos_erros)
                    gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", motivo)
                else:
                    db.registrar_itens(run_id, "Avarias", novas_avarias)
                    db.registrar_itens(run_id, "Uso Interno", novos_usos)
                    avarias_total += len(novas_avarias)
                    usos_total += len(novos_usos)
                    image_archive.arquivar_imagem(nome_arquivo, diretorio_imagens, ARCHIVE_FOLDER)
                    corrigidos += 1
                    detalhes.append({"arquivo": nome_arquivo, "status": "sucesso"})
                    gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "sucesso", "Reanálise seletiva do mestre")
            except Exception as e:
                ainda_com_erro += 1
                detalhes.append({"arquivo": nome_arquivo, "status": "falha", "motivo": str(e)})
                erros_exec.append(_linha_de_erro(nome_arquivo, str(e), mensagens_por_imagem, diretorio_imagens))
                gerenciador.adicionar_ao_log_reanalise(nome_arquivo, "falha", str(e))

            if idx < len(alvos):
                time.sleep(request_delay)

        db.registrar_consumo_tokens(run_id, tokens_totais, f"Reanálise seletiva do mestre ({len(alvos)} imagens)")
        db.registrar_itens(run_id, "Erros de Análise", erros_exec)
        db.finalizar_execucao(run_id, "concluido", avarias_total, usos_total, ainda_com_erro, tokens_totais)
        print(f"✅ REANÁLISE SELETIVA CONCLUÍDA: {corrigidos} corrigidos, {ainda_com_erro} com erro")
        return {"sucesso": True, "total_arquivos": len(alvos), "processados": len(alvos),
                "corrigidos": corrigidos, "ainda_com_erro": ainda_com_erro, "detalhes": detalhes,
                "categorias": categorias_filtro}
    except Exception as e:
        import traceback

        traceback.print_exc()
        db.finalizar_execucao(run_id, "erro", mensagem=str(e))
        return {"sucesso": False, "erro": str(e), "total_arquivos": len(alvos),
                "processados": 0, "corrigidos": 0, "ainda_com_erro": 0, "detalhes": []}
