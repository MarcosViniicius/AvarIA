"""Rotas de configurações: `/configuracoes`, `/salvar_configuracao`, `/download_config`."""

import copy
import json
import os

from flask import flash, jsonify, make_response, redirect, render_template, request, url_for

from .blueprint import web_bp as app
from .context import CONFIG_FILE
from ..services.config_service import carregar_configuracao, salvar_configuracao
from ..services.stats import obter_estatisticas


@app.route("/configuracoes")
def configuracoes():
    """Página de configurações."""
    config = carregar_configuracao()
    stats = obter_estatisticas()

    # Avisar sobre limitações na Vercel
    if "VERCEL" in os.environ:
        config["_vercel_env"] = True

    return render_template("configuracoes.html", config=config, stats=stats)


def _config_sem_chaves(config: dict) -> dict:
    """Copia a config substituindo as chaves de API por um marcador.

    As chamadas que consomem este endpoint (ver rotas abaixo) só precisam de
    preferências como `processamento.modo_extracao` ou
    `interface.logs_detalhados_aplicacao` — nunca da chave em si. Mandar a
    chave real pela rede sem necessidade é exposição desnecessária.
    """
    config_seguro = copy.deepcopy(config)
    for campo, valor in config_seguro.get("api", {}).items():
        if campo.endswith("_api_key") and valor:
            config_seguro["api"][campo] = "***"
    return config_seguro


@app.route("/api/configuracoes", methods=["GET"])
def api_configuracoes_get():
    """Devolve a configuração atual como JSON, com as chaves de API mascaradas.

    Usado por telas que precisam ler uma preferência pontual (ex.: o modo de
    extração no Dashboard) sem carregar a página de Configurações inteira.
    A tela de Configurações em si lê a chave real via `config` renderizado
    pelo servidor (Jinja), não por este endpoint.
    """
    return jsonify(_config_sem_chaves(carregar_configuracao()))


@app.route("/api/configuracoes", methods=["POST"])
def api_configuracoes_post():
    """Atualiza a configuração (mesma lógica de /salvar_configuracao, como JSON puro)."""
    return salvar_configuracao_route()


@app.route("/salvar_configuracao", methods=["POST"])
def salvar_configuracao_route():
    """Salva as configurações do usuário."""
    try:
        data = request.json
        config = carregar_configuracao()

        # Atualizar configurações da API
        if "api" in data:
            for key, value in data["api"].items():
                config["api"][key] = value

            # Se um modelo específico foi selecionado, salvar nas configurações de processamento
            if "modelo_selecionado" in data["api"]:
                provider = data["api"].get("provider", "gemini")
                modelo_key = f"modelo_{provider}"
                if "processamento" not in config:
                    config["processamento"] = {}
                config["processamento"][modelo_key] = data["api"]["modelo_selecionado"]

        # Atualizar configurações de processamento
        if "processamento" in data:
            if "processamento" not in config:
                config["processamento"] = {}
            for key, value in data["processamento"].items():
                config["processamento"][key] = value

        # Atualizar configurações de interface
        if "interface" in data:
            if "interface" not in config:
                config["interface"] = {}
            config["interface"].update(data["interface"])

        # No ambiente Vercel, apenas simular salvamento
        if "VERCEL" in os.environ:
            return jsonify(
                {
                    "success": True,
                    "message": "No ambiente Vercel, use variáveis de ambiente para configurações",
                }
            )

        if salvar_configuracao(config):
            return jsonify(
                {"success": True, "message": "Configurações salvas com sucesso!"}
            )
        else:
            return jsonify(
                {"success": False, "message": "Erro ao salvar configurações"}
            )

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro: {str(e)}"})


@app.route("/api/configuracoes/logs_detalhados", methods=["GET", "POST"])
def api_logs_detalhados():
    """Lê/grava só `interface.logs_detalhados_aplicacao` (o toggle da tela de Logs).

    Rota própria para não precisar ir e voltar com a configuração inteira
    (chaves de API incluídas) só para ligar/desligar um booleano.
    """
    if request.method == "GET":
        config = carregar_configuracao()
        return jsonify({"ativo": bool(config.get("interface", {}).get("logs_detalhados_aplicacao", False))})

    data = request.get_json(silent=True) or {}
    config = carregar_configuracao()
    config.setdefault("interface", {})["logs_detalhados_aplicacao"] = bool(data.get("ativo"))

    if "VERCEL" in os.environ:
        return jsonify({"success": True, "message": "No ambiente Vercel, use variáveis de ambiente para configurações"})

    if salvar_configuracao(config):
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Erro ao salvar configuração"}), 500


@app.route("/download_config")
def download_config():
    """Download das configurações como backup (chaves de API removidas por segurança)."""
    try:
        if not os.path.exists(CONFIG_FILE):
            flash("Arquivo de configuração não encontrado.", "warning")
            return redirect(url_for("configuracoes"))

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Nunca exportar as chaves de API em texto puro — esse backup é só das
        # preferências de processamento/interface. Quem precisar restaurar a
        # chave configura de novo pela tela de Configurações.
        config_seguro = copy.deepcopy(config)
        for campo, valor in config_seguro.get("api", {}).items():
            if campo.endswith("_api_key") and valor:
                config_seguro["api"][campo] = "***REMOVIDA_POR_SEGURANCA***"

        response = make_response(json.dumps(config_seguro, indent=2, ensure_ascii=False))
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=config_backup.json"
        return response
    except Exception as e:
        flash(f"Erro ao fazer download: {str(e)}", "error")
        return redirect(url_for("configuracoes"))
