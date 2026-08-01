"""
Rotas de gerenciamento de erros de análise: `/api/obter_erros_pendentes`,
`/api/reanalisar_erros`, `/api/progresso_reanalise`.
"""

import threading

from flask import jsonify

from .blueprint import web_bp as app
from .context import ARQUIVO_SAIDA_EXCEL, DIRETORIO_IMAGENS
from ..services import app_state


@app.route("/api/obter_erros_pendentes")
def obter_erros_pendentes():
    """API para obter quantidade de erros pendentes."""
    try:
        from autoavaria.services.reports import criar_gerenciador

        gerenciador = criar_gerenciador(ARQUIVO_SAIDA_EXCEL)
        resumo = gerenciador.gerar_resumo_erros()

        return jsonify({
            "success": True,
            "total": resumo["total"],
            "tipos": resumo["tipos"],
            "arquivos": resumo["arquivos"]
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/reanalisar_erros", methods=["POST"])
def reanalisar_erros_api():
    """API para iniciar reanálise de erros."""
    try:
        # Verificar se já há processamento ativo
        if app_state.processamento_ativo:
            return jsonify({
                "success": False,
                "message": "Já existe um processamento em andamento"
            }), 400

        from autoavaria.services.reports import criar_gerenciador

        # Verificar se há erros para reanalisar
        gerenciador = criar_gerenciador(ARQUIVO_SAIDA_EXCEL)
        total_erros = gerenciador.contar_erros_pendentes()

        if total_erros == 0:
            return jsonify({
                "success": True,
                "message": "Nenhum erro pendente para reanalisar",
                "resultado": {
                    "total_arquivos": 0,
                    "corrigidos": 0,
                    "ainda_com_erro": 0
                }
            })

        # Marcar processamento como ativo
        app_state.processamento_ativo = True
        app_state.progresso_atual = {
            "progresso": 0,
            "status": "Iniciando reanálise de erros",
            "logs": [f"🔄 Iniciando reanálise de {total_erros} itens com erro"]
        }

        # Função de callback para atualizar progresso
        def callback_progresso(info):
            progresso = int((info["atual"] / info["total"]) * 100)
            app_state.progresso_atual["progresso"] = progresso
            app_state.progresso_atual["status"] = f"Reanalisando: {info['arquivo']}"
            app_state.progresso_atual["logs"].append(
                f"[{info['atual']}/{info['total']}] {info['arquivo']}"
            )

        # Executar reanálise em thread separada
        def executar_reanalise():
            try:
                from autoavaria.services.extraction_pipeline import reanalisar_erros

                resultado = reanalisar_erros(
                    diretorio_imagens=DIRETORIO_IMAGENS,
                    arquivo_excel=ARQUIVO_SAIDA_EXCEL,
                    callback_progresso=callback_progresso
                )

                app_state.progresso_atual["progresso"] = 100
                app_state.progresso_atual["status"] = "Reanálise concluída"
                app_state.progresso_atual["resultado"] = resultado
                app_state.progresso_atual["logs"].append(
                    f"✅ Reanálise concluída: {resultado.get('corrigidos', 0)} corrigidos, "
                    f"{resultado.get('ainda_com_erro', 0)} ainda com erro"
                )

            except Exception as e:
                app_state.progresso_atual["status"] = f"Erro na reanálise: {str(e)}"
                app_state.progresso_atual["logs"].append(f"❌ Erro: {str(e)}")
                app_state.progresso_atual["erro"] = str(e)
            finally:
                app_state.processamento_ativo = False

        # Iniciar thread
        thread = threading.Thread(target=executar_reanalise, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "message": f"Reanálise iniciada para {total_erros} itens",
            "total_erros": total_erros
        })

    except Exception as e:
        app_state.processamento_ativo = False
        return jsonify({
            "success": False,
            "message": f"Erro ao iniciar reanálise: {str(e)}"
        }), 500


@app.route("/api/progresso_reanalise")
def progresso_reanalise():
    """API para obter progresso da reanálise."""
    return jsonify({
        "ativo": app_state.processamento_ativo,
        "progresso": app_state.progresso_atual.get("progresso", 0),
        "status": app_state.progresso_atual.get("status", "Aguardando"),
        "logs": app_state.progresso_atual.get("logs", []),
        "resultado": app_state.progresso_atual.get("resultado"),
        "erro": app_state.progresso_atual.get("erro")
    })
