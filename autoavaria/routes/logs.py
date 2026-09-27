"""Rotas de logs (`/logs`, `/visualizar_logs`, `/api/logs`)."""

import os
from datetime import datetime

from flask import jsonify, render_template

from .blueprint import web_bp as app
from .context import LOG_CONSUMO_FILE, LOG_PROCESSADOS_FILE
from ..services import app_state
from ..services import db as db_service
from ..services.config_service import carregar_configuracao


def _processados_do_banco(limite: int = 20):
    """Últimos processados do SQLite, no formato que a tela consome."""
    try:
        with db_service.get_connection() as conn:
            rows = conn.execute(
                """SELECT nome, processado_em FROM arquivos_processados
                   ORDER BY processado_em DESC, rowid DESC LIMIT ?""",
                (limite,),
            ).fetchall()
        return [
            {
                "tipo": "processado",
                "timestamp": row["processado_em"],
                "mensagem": f"{row['processado_em']} - Processado: {row['nome']}",
            }
            for row in rows
        ]
    except Exception as e:
        print(f"⚠️ Banco indisponível para os logs de processados: {e}")
        return []


def _processados_do_arquivo(limite: int = 20):
    """Fallback legado: lê o log_mestre.txt.

    Usa o timestamp REAL da linha (não a hora atual): com o polling de 2s, um
    horário inventado faria a mesma linha parecer um evento novo a cada ciclo.
    """
    if not os.path.exists(LOG_PROCESSADOS_FILE):
        return []
    logs = []
    try:
        with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
            for linha in f.readlines()[-limite:]:
                linha = linha.strip()
                if not linha:
                    continue
                if " - Processado: " in linha:
                    timestamp = linha.split(" - Processado: ")[0]
                else:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logs.append({"tipo": "processado", "timestamp": timestamp, "mensagem": linha})
    except IOError:
        return []
    return logs


def _consumo_do_banco(limite: int = 10):
    try:
        with db_service.get_connection() as conn:
            rows = conn.execute(
                """SELECT registrado_em, tokens, detalhes FROM consumo_tokens_log
                   ORDER BY registrado_em DESC, id DESC LIMIT ?""",
                (limite,),
            ).fetchall()
        logs = []
        for row in rows:
            mensagem = f"{row['registrado_em']} - Tokens consumidos: {row['tokens']:,}"
            if row["detalhes"]:
                mensagem += f" - {row['detalhes']}"
            logs.append(
                {"tipo": "consumo", "timestamp": row["registrado_em"], "mensagem": mensagem}
            )
        return logs
    except Exception as e:
        print(f"⚠️ Banco indisponível para os logs de consumo: {e}")
        return []


def _consumo_do_arquivo(limite: int = 10):
    if not os.path.exists(LOG_CONSUMO_FILE):
        return []
    logs = []
    try:
        with open(LOG_CONSUMO_FILE, "r", encoding="utf-8") as f:
            for linha in f.readlines()[-limite:]:
                if not linha.strip():
                    continue
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
    except IOError:
        return []
    return logs


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
            # Modo padrão - logs simplificados.
            # Fonte primária: o SQLite (tabelas arquivos_processados e
            # consumo_tokens_log). O arquivo é o fallback para instalações que
            # ainda não importaram o histórico (ver db.importar_logs_dos_arquivos).
            logs.extend(_processados_do_banco() or _processados_do_arquivo())
            logs.extend(_consumo_do_banco() or _consumo_do_arquivo())

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
