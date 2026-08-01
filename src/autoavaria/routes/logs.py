"""Rotas de logs (`/logs`, `/visualizar_logs`, `/api/logs`)."""

import os
from datetime import datetime

from flask import jsonify, render_template

from .blueprint import web_bp as app
from .context import LOG_CONSUMO_FILE, LOG_PROCESSADOS_FILE
from ..services import app_state
from ..services.config_service import carregar_configuracao


@app.route("/logs")
@app.route("/visualizar_logs")
def visualizar_logs():
    """Página de visualização de logs em tempo real."""
    return render_template("logs.html")


@app.route("/api/logs")
def api_logs():
    """API para obter logs em tempo real."""
    try:
        config = carregar_configuracao()
        logs_detalhados = config.get("interface", {}).get("logs_detalhados_aplicacao", False)
        logs = []

        # Se logs detalhados estiver ativo, retornar logs da aplicação
        if logs_detalhados and app_state.logs_aplicacao_buffer:
            logs.extend(app_state.logs_aplicacao_buffer[-100:])
        else:
            # Modo padrão - logs simplificados
            # Ler log de processamento
            if os.path.exists(LOG_PROCESSADOS_FILE):
                with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
                    linhas = f.readlines()
                    for linha in linhas[-20:]:  # Últimas 20 linhas
                        linha = linha.strip()
                        if not linha:
                            continue
                        # Linha tem o formato "TIMESTAMP - Processado: arquivo" -
                        # usar o timestamp real do evento em vez da hora atual,
                        # senão a mesma linha reaparece com um horário diferente
                        # a cada polling (a cada 2s) e parece um evento novo.
                        if " - Processado: " in linha:
                            timestamp = linha.split(" - Processado: ")[0]
                        else:
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        logs.append(
                            {
                                "tipo": "processado",
                                "timestamp": timestamp,
                                "mensagem": linha,
                            }
                        )

            # Ler log de consumo
            if os.path.exists(LOG_CONSUMO_FILE):
                with open(LOG_CONSUMO_FILE, "r", encoding="utf-8") as f:
                    linhas = f.readlines()
                    for linha in linhas[-10:]:  # Últimas 10 linhas
                        if linha.strip():
                            logs.append(
                                {
                                    "tipo": "consumo",
                                    "timestamp": (
                                        linha[:19]
                                        if len(linha) > 19
                                        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    ),
                                    "mensagem": linha.strip(),
                                }
                            )

            # Adicionar logs do progresso atual
            for log_msg in app_state.progresso_atual.get("logs", []):
                logs.append(
                    {
                        "tipo": "progresso",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "mensagem": log_msg,
                    }
                )

        return jsonify(
            {
                "logs": logs[-100:],  # Últimos 100 logs
                "processamento_ativo": app_state.processamento_ativo,
                "progresso": app_state.progresso_atual,
                "logs_detalhados": logs_detalhados,
            }
        )

    except Exception as e:
        return jsonify(
            {
                "logs": [
                    {
                        "tipo": "erro",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "mensagem": f"Erro ao ler logs: {str(e)}",
                    }
                ],
                "processamento_ativo": app_state.processamento_ativo,
                "progresso": app_state.progresso_atual,
            }
        )
