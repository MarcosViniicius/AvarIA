"""
Rotas de processamento (`/processar`, `/cancelar`, `/status`) e as funções
auxiliares de orquestração usadas apenas por este grupo de rotas
(``executar_processamento_principal``, ``processar_em_background``,
``allowed_file``, ``extrair_arquivos_comprimidos``).
"""

import os
import threading
from datetime import datetime

import pandas as pd
from flask import jsonify, request

from .blueprint import web_bp as app
from .context import (
    ALLOWED_EXTENSIONS,
    ARCHIVE_FOLDER,
    ARQUIVO_SAIDA_EXCEL,
    BASE_PATH,
    DIRETORIO_IMAGENS,
    EXTENSOES_IMAGEM,
)
from ..services import app_state
from ..services.app_state import log_aplicacao
from ..services.config_service import (
    carregar_configuracao,
    verificar_e_corrigir_configuracao,
)
from ..services.extraction import ExtratorArquivos
from ..services.extraction_pipeline import listar_imagens_pendentes
from ..services.report_editing import carregar_todas_sheets


def allowed_file(filename):
    """Verifica se o arquivo tem extensão permitida, incluindo extensões compostas."""
    if not filename or "." not in filename:
        return False

    filename_lower = filename.lower()

    # Verificar extensões compostas primeiro
    extensoes_compostas = [".tar.gz", ".tar.bz2", ".tgz"]
    for ext_composta in extensoes_compostas:
        if filename_lower.endswith(ext_composta):
            return True

    # Verificar extensão simples
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS


def extrair_arquivos_comprimidos(pasta_imagens, logs_callback=None, forcar=False):
    """
    Extrai arquivos comprimidos da pasta de imagens.

    Args:
        pasta_imagens (str): Caminho para a pasta de imagens
        logs_callback (function): Função callback para adicionar logs
        forcar (bool): Se True, ignora o dedup por conteúdo - toda imagem
            colidindo com uma já existente (mesmo idêntica) ganha um nome
            novo em vez de ser descartada. Usado pelo "Forçar reprocessamento"
            da tela de Upload.

    Returns:
        dict: Resultados da extração
    """
    try:
        extrator = ExtratorArquivos(pasta_origem=pasta_imagens, pasta_arquivo=ARCHIVE_FOLDER, forcar=forcar)
        arquivos_comprimidos = extrator.listar_arquivos_comprimidos()

        if not arquivos_comprimidos:
            if logs_callback:
                logs_callback("📦 Nenhum arquivo comprimido encontrado")
            return {"arquivos_encontrados": 0, "arquivos_extraidos": 0}

        if logs_callback:
            logs_callback(f"📦 Encontrados {len(arquivos_comprimidos)} arquivos comprimidos")
            logs_callback("📦 Iniciando extração...")

        # Extrair todos os arquivos
        resultados = extrator.extrair_todos(
            criar_subpastas=False,  # Não criar subpastas para manter na pasta principal
            remover_originais=False  # Manter originais por segurança
        )

        sucessos = sum(1 for sucesso in resultados.values() if sucesso)

        if logs_callback:
            if sucessos > 0:
                logs_callback(f"✅ {sucessos}/{len(arquivos_comprimidos)} arquivos extraídos com sucesso")
                for arquivo, sucesso in resultados.items():
                    status = "✅" if sucesso else "❌"
                    logs_callback(f"  {status} {arquivo}")
            else:
                logs_callback("⚠️ Nenhum arquivo foi extraído com sucesso")

        return {
            "arquivos_encontrados": len(arquivos_comprimidos),
            "arquivos_extraidos": sucessos,
            "detalhes": resultados
        }

    except Exception as e:
        if logs_callback:
            logs_callback(f"⚠️ Erro durante extração: {str(e)}")
        return {
            "arquivos_encontrados": 0,
            "arquivos_extraidos": 0,
            "erro": str(e)
        }


def executar_processamento_principal(modo_extracao=None):
    """Executa o processamento principal importando e rodando o script original."""
    try:
        # Verificar e sincronizar configurações
        config_ok, config_msg = verificar_e_corrigir_configuracao(modo_extracao)
        log_aplicacao(f"🔧 {config_msg}")
        app_state.progresso_atual["logs"].append(f"🔧 {config_msg}")

        if not config_ok:
            app_state.progresso_atual["status"] = "Erro: API Key não configurada"
            return False

        log_aplicacao("🔑 Configuração validada, continuando...")
        app_state.progresso_atual["logs"].append("🔑 Configuração validada, continuando...")

        # Verificar se há imagens para processar
        if not os.path.exists(DIRETORIO_IMAGENS):
            log_aplicacao("❌ Diretório de imagens não encontrado!")
            app_state.progresso_atual["logs"].append("❌ Diretório de imagens não encontrado!")
            return False

        imagens = [
            f
            for f in os.listdir(DIRETORIO_IMAGENS)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]

        if not imagens:
            log_aplicacao("❌ Nenhuma imagem encontrada para processar!")
            app_state.progresso_atual["logs"].append(
                "❌ Nenhuma imagem encontrada para processar!"
            )
            return False

        log_aplicacao(f"📸 Encontradas {len(imagens)} imagens para processar")
        app_state.progresso_atual["logs"].append(
            f"📸 Encontradas {len(imagens)} imagens para processar"
        )

        # No ambiente Vercel, o processamento completo pode ser limitado
        if "VERCEL" in os.environ:
            log_aplicacao("⚠️ Ambiente Vercel: processamento completo pode ser limitado")
            app_state.progresso_atual["logs"].append(
                "⚠️ Ambiente Vercel: processamento completo pode ser limitado"
            )
            return False

        log_aplicacao("🚀 Iniciando análise com IA...")
        app_state.progresso_atual["logs"].append("🚀 Iniciando análise com IA...")

        # Executar a função principal do pipeline de extração
        from autoavaria.services.extraction_pipeline import main as executar_pipeline_extracao

        executar_pipeline_extracao(modo_extracao)

        # Verificar se o relatório foi gerado
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            log_aplicacao("✅ Relatório Excel gerado com sucesso!")
            app_state.progresso_atual["logs"].append("✅ Relatório Excel gerado com sucesso!")
            return True
        else:
            log_aplicacao("⚠️ Processamento concluído, mas relatório não foi encontrado")
            app_state.progresso_atual["logs"].append(
                "⚠️ Processamento concluído, mas relatório não foi encontrado"
            )
            return False

    except Exception as e:
        erro_msg = f"Erro ao executar processamento: {str(e)}"
        log_aplicacao(f"❌ {erro_msg}", "erro")
        app_state.progresso_atual["logs"].append(f"❌ {erro_msg}")
        return False


def processar_em_background(modo_extracao=None, resultado_extracao_previo=None):
    """Executa o processamento em background.

    `resultado_extracao_previo`: resultado já calculado por
    `iniciar_processamento()`, que precisa extrair os comprimidos de forma
    síncrona ANTES de decidir se vale a pena disparar esta thread (checar se
    sobrou alguma imagem pra processar). Passar esse resultado pronto evita
    extrair os mesmos arquivos comprimidos duas vezes toda vez que alguém
    clica em "Processar" - sem isso, cada zip era lido e (re)extraído duas
    vezes seguidas (a segunda não duplicava imagem por causa da checagem de
    conteúdo em `nome_para_gravar`, mas desperdiçava tempo e poluía o log).
    """
    try:
        app_state.processamento_ativo = True
        app_state.processamento_cancelado = False
        app_state.progresso_atual = {
            "progresso": 0,
            "status": "Iniciando processamento...",
            "logs": [],
        }

        # Limpar arquivo de cancelamento se existir
        cancel_file = os.path.join(BASE_PATH, ".cancel_processing")
        if os.path.exists(cancel_file):
            try:
                os.remove(cancel_file)
            except:
                pass

        # Log inicial
        timestamp = datetime.now().strftime("%H:%M:%S")
        app_state.progresso_atual["logs"].append(f"🚀 Iniciando processamento às {timestamp}")

        # Verificar se estamos na Vercel
        if "VERCEL" in os.environ:
            app_state.progresso_atual["status"] = (
                "❌ Erro: Processamento não disponível na Vercel"
            )
            app_state.progresso_atual["logs"].append(
                "❌ O processamento completo não está disponível no ambiente Vercel"
            )
            app_state.progresso_atual["logs"].append(
                "💡 Use o ambiente local para processamento de imagens"
            )
            return

        # Verificar configurações
        app_state.progresso_atual["progresso"] = 5
        app_state.progresso_atual["status"] = "🔍 Verificando configurações..."
        config = carregar_configuracao()
        modo_extracao = (
            modo_extracao or config.get("processamento", {}).get("modo_extracao") or "ia"
        ).lower()

        config_ok, config_msg = verificar_e_corrigir_configuracao(modo_extracao)
        if not config_ok:
            app_state.progresso_atual["status"] = "❌ Erro: API Key não configurada"
            app_state.progresso_atual["logs"].append(f"❌ {config_msg}")
            app_state.progresso_atual["logs"].append(
                "⚙️ Configure a API Key na página de Configurações"
            )
            return
        app_state.progresso_atual["logs"].append(f"🔧 {config_msg}")

        # Verificar se foi cancelado
        if app_state.processamento_cancelado:
            app_state.progresso_atual["status"] = "❌ Processamento cancelado pelo usuário"
            app_state.progresso_atual["logs"].append("⚠️ Processamento cancelado")
            return

        # Extrair arquivos comprimidos se existirem
        app_state.progresso_atual["progresso"] = 8
        app_state.progresso_atual["status"] = "📦 Verificando arquivos comprimidos..."

        def adicionar_log(mensagem):
            app_state.progresso_atual["logs"].append(mensagem)

        if resultado_extracao_previo is not None:
            # Já foi extraído por iniciar_processamento() antes de disparar
            # esta thread - reaproveita o resultado em vez de repetir a
            # extração (ver docstring desta função).
            resultado_extracao = resultado_extracao_previo
            if resultado_extracao["arquivos_encontrados"] > 0:
                adicionar_log(
                    f"📦 {resultado_extracao['arquivos_extraidos']}/{resultado_extracao['arquivos_encontrados']} "
                    "arquivos comprimidos extraídos com sucesso"
                )
            else:
                adicionar_log("📦 Nenhum arquivo comprimido encontrado")
        else:
            resultado_extracao = extrair_arquivos_comprimidos(DIRETORIO_IMAGENS, adicionar_log)

        if resultado_extracao["arquivos_encontrados"] > 0:
            app_state.progresso_atual["status"] = "📦 Extração de arquivos concluída"
        else:
            app_state.progresso_atual["status"] = "📦 Nenhum arquivo comprimido encontrado"

        # Verificar imagens disponíveis
        app_state.progresso_atual["progresso"] = 10
        app_state.progresso_atual["status"] = "📸 Verificando imagens disponíveis..."

        if not os.path.exists(DIRETORIO_IMAGENS):
            app_state.progresso_atual["logs"].append("❌ Diretório de imagens não encontrado")
            app_state.progresso_atual["status"] = "❌ Erro: Diretório não encontrado"
            return

        imagens = [
            f
            for f in os.listdir(DIRETORIO_IMAGENS)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]

        if not imagens:
            app_state.progresso_atual["logs"].append(
                "❌ Nenhuma imagem encontrada para processar"
            )
            app_state.progresso_atual["status"] = "❌ Erro: Nenhuma imagem encontrada"
            return

        app_state.progresso_atual["logs"].append(
            f"📸 Encontradas {len(imagens)} imagens para processar"
        )

        # Verificar imagens já processadas
        app_state.progresso_atual["progresso"] = 20
        app_state.progresso_atual["status"] = "📋 Verificando arquivos já processados..."

        # Mesma função usada pelo pipeline (extraction_pipeline.py) - fonte
        # única desta verificação, para as duas nunca divergirem sobre o que
        # conta como "novo" (antes essa checagem era refeita aqui comparando
        # nome de arquivo contra a linha inteira do log, o que nunca dava
        # match e fazia essa mensagem de progresso mentir).
        novas_imagens = listar_imagens_pendentes(DIRETORIO_IMAGENS)
        app_state.progresso_atual["logs"].append(
            f"📝 {len(imagens) - len(novas_imagens)} imagens já foram processadas anteriormente"
        )
        app_state.progresso_atual["logs"].append(
            f"🆕 {len(novas_imagens)} novas imagens para processar"
        )

        if not novas_imagens:
            app_state.progresso_atual["progresso"] = 100
            app_state.progresso_atual["status"] = "✅ Todas as imagens já foram processadas!"
            app_state.progresso_atual["logs"].append("✅ Todas as imagens já foram processadas!")
            return

        # Verificar se foi cancelado antes de iniciar processamento
        if app_state.processamento_cancelado:
            app_state.progresso_atual["status"] = "❌ Processamento cancelado pelo usuário"
            app_state.progresso_atual["logs"].append("⚠️ Processamento cancelado antes de iniciar análise")
            return

        # Executar processamento principal
        app_state.progresso_atual["progresso"] = 30
        app_state.progresso_atual["status"] = "🤖 Iniciando análise com IA Gemini..."
        app_state.progresso_atual["logs"].append("⚙️ Carregando script de processamento...")

        sucesso = executar_processamento_principal(modo_extracao)

        if sucesso:
            app_state.progresso_atual["progresso"] = 100
            app_state.progresso_atual["status"] = "✅ Processamento concluído com sucesso!"
            app_state.progresso_atual["logs"].append("✅ Análise concluída com sucesso!")

            # Verificar resultados
            if os.path.exists(ARQUIVO_SAIDA_EXCEL):
                app_state.progresso_atual["logs"].append(
                    f"📄 Relatório Excel gerado: {ARQUIVO_SAIDA_EXCEL}"
                )

                # Contar resultados
                try:
                    sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)
                    for sheet_name, df in sheets.items():
                        if not df.empty:
                            app_state.progresso_atual["logs"].append(
                                f"📊 {sheet_name}: {len(df)} registros"
                            )
                except Exception as e:
                    app_state.progresso_atual["logs"].append(
                        f"⚠️ Erro ao ler estatísticas do relatório: {e}"
                    )
            else:
                app_state.progresso_atual["logs"].append("⚠️ Relatório não foi gerado")
        else:
            app_state.progresso_atual["status"] = "❌ Erro durante processamento"
            app_state.progresso_atual["logs"].append("❌ Erro durante o processamento principal")

    except Exception as e:
        erro_msg = f"Erro durante processamento: {str(e)}"
        app_state.progresso_atual["status"] = f"❌ Erro: {str(e)}"
        app_state.progresso_atual["logs"].append(f"❌ {erro_msg}")
        print(f"Erro em processar_em_background: {e}")

    finally:
        app_state.processamento_ativo = False
        app_state.processamento_cancelado = False
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Adicionar mensagem de finalização apenas se não foi adicionada antes
        if app_state.progresso_atual["logs"] and not app_state.progresso_atual["logs"][-1].startswith("🏁"):
            app_state.progresso_atual["logs"].append(f"🏁 Processamento finalizado às {timestamp}")


@app.route("/processar", methods=["POST"])
def iniciar_processamento():
    """Inicia o processamento das imagens."""
    # Verificar se estamos na Vercel
    if "VERCEL" in os.environ:
        return jsonify(
            {
                "success": False,
                "message": "Processamento não disponível no ambiente Vercel. Use o ambiente local.",
            }
        )

    if app_state.processamento_ativo:
        return jsonify({"success": False, "message": "Processamento já em andamento"})

    # Verificar se há imagens para processar
    if not os.path.exists(DIRETORIO_IMAGENS):
        return jsonify({"success": False, "message": "Pasta de imagens não encontrada"})

    # Modo de extração escolhido pelo usuário na tela de processamento (IA,
    # sem IA ou híbrido). Se omitido, processar_em_background usa o padrão
    # salvo em config/config.json. Lido uma única vez aqui e reaproveitado
    # abaixo para não chamar request.get_json() duas vezes.
    dados_requisicao = request.get_json(silent=True) or {}
    modo_extracao = dados_requisicao.get("modo_extracao")
    forcar_reprocessamento = bool(dados_requisicao.get("forcar_reprocessamento", False))

    # Tentar extrair arquivos comprimidos antes de verificar imagens - precisa
    # ser síncrono aqui para a checagem de "há imagens" logo abaixo enxergar
    # o conteúdo já extraído. O resultado é repassado para a thread de
    # processamento (processar_em_background) para ela não extrair tudo de
    # novo - ver docstring de processar_em_background.
    resultado_extracao = None
    try:
        resultado_extracao = extrair_arquivos_comprimidos(DIRETORIO_IMAGENS, forcar=forcar_reprocessamento)
        if resultado_extracao["arquivos_extraidos"] > 0:
            print(f"✅ Extraídos {resultado_extracao['arquivos_extraidos']} arquivos comprimidos")
    except Exception as e:
        # Se houver erro na extração, continuar com o processamento normal
        print(f"Aviso: Erro na extração de arquivos: {e}")

    imagens = [
        f for f in os.listdir(DIRETORIO_IMAGENS) if f.lower().endswith(EXTENSOES_IMAGEM)
    ]
    if not imagens:
        return jsonify(
            {"success": False, "message": "Nenhuma imagem encontrada para processar"}
        )

    # Iniciar processamento em background
    thread = threading.Thread(
        target=processar_em_background, args=(modo_extracao, resultado_extracao)
    )
    thread.start()

    return jsonify({"success": True, "message": "Processamento iniciado!"})


@app.route("/cancelar", methods=["POST"])
def cancelar_processamento():
    """Cancela o processamento em andamento."""
    if not app_state.processamento_ativo:
        return jsonify({"success": False, "message": "Nenhum processamento em andamento"})

    app_state.processamento_cancelado = True
    app_state.progresso_atual["logs"].append("⚠️ Solicitação de cancelamento recebida...")
    app_state.progresso_atual["status"] = "⚠️ Cancelando processamento..."

    # Criar arquivo de sinalização lido pelo pipeline de extração (services/extraction_pipeline.py)
    try:
        cancel_file = os.path.join(BASE_PATH, ".cancel_processing")
        with open(cancel_file, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        print(f"Erro ao criar arquivo de cancelamento: {e}")

    return jsonify({"success": True, "message": "Processamento cancelado!"})


@app.route("/status")
def obter_status():
    """Obtém o status atual do processamento."""
    # Adicionar informações extras ao progresso
    status_completo = app_state.progresso_atual.copy()

    # Adicionar contagem de imagens
    if os.path.exists(DIRETORIO_IMAGENS):
        imagens = [
            f
            for f in os.listdir(DIRETORIO_IMAGENS)
            if f.lower().endswith(EXTENSOES_IMAGEM)
        ]
        status_completo["total_imagens"] = len(imagens)
    else:
        status_completo["total_imagens"] = 0

    return jsonify(status_completo)
