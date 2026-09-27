"""
Rotas de Histórico de Relatórios.

Mostra o histórico de execuções de processamento e de relatórios unificados
gerados, usando o índice guardado no banco SQLite (services/db.py). Os
arquivos em si continuam em resultados/ — esta tela só lista/organiza o que
já existe, sem duplicar dados.
"""

import threading

from flask import abort, jsonify, render_template, request, send_file, url_for

from ..core.paths import RESULTADOS_DIR
from ..services import app_state
from ..services import db as db_service
from ..services import execucao_export
from ..services import invertexto
from ..services.relatorio_view import (
    _COLUNAS_POR_CATEGORIA,
    _construir_dados_relatorio,
)
from .blueprint import web_bp as app


@app.route("/historico")
def historico():
    """Lista as execuções de processamento e os relatórios unificados já gerados."""
    execucoes = db_service.listar_execucoes(limite=50)
    relatorios_unificados = db_service.listar_relatorios_unificados(limite=100)
    resumo = db_service.resumo_geral()
    return render_template(
        "historico.html",
        execucoes=execucoes,
        relatorios_unificados=relatorios_unificados,
        resumo=resumo,
    )


@app.route("/historico/execucao/<int:run_id>")
def historico_execucao(run_id):
    """Mostra o detalhe (itens extraídos) de uma execução específica.

    Os itens são reorganizados no mesmo formato ``{categoria: {colunas, dados,
    total}}`` usado pela página de Relatório, para reaproveitar exatamente a
    mesma exibição (cards de resumo, abas, tabela pesquisável/ordenável e
    visualização de imagem).
    """
    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        abort(404)
    raiz_execucao_id = execucao["raiz_execucao_id"] or execucao["id"]
    versoes = db_service.listar_versoes(raiz_execucao_id)
    eh_versao_mais_recente = not versoes or execucao["versao"] == max(v["versao"] for v in versoes)
    dados = _construir_dados_relatorio(execucao["itens"])
    origem = request.args.get("origem", "historico")
    return render_template(
        "historico_execucao.html",
        execucao=execucao,
        dados=dados,
        versoes=versoes,
        eh_versao_mais_recente=eh_versao_mais_recente,
        origem=origem,
        dados_invertexto=invertexto.obter_config_publica(),
    )


# ---------------------------------------------------------------------------
# Edição dos itens de uma execução histórica (armazenados no banco).
# Não mexe no Excel mestre atual — cada execução tem seu próprio conjunto de
# itens no banco, independente do relatório "vivo" (ver página Editar Dados).
# ---------------------------------------------------------------------------

@app.route("/historico/execucao/<int:run_id>/item/editar", methods=["POST"])
def historico_editar_item(run_id):
    """Edita um único campo de um item histórico."""
    data = request.json or {}
    item_id = data.get("item_id")
    campo = data.get("campo")
    novo_valor = data.get("novo_valor", "")

    if item_id is None or not campo:
        return jsonify({"success": False, "message": "item_id e campo são obrigatórios"})

    item = db_service.obter_item(item_id)
    if not item or item["run_id"] != run_id:
        return jsonify({"success": False, "message": "Item não encontrado nesta execução"})

    if not db_service.atualizar_item_campo(item_id, campo, novo_valor):
        return jsonify({"success": False, "message": f'Campo "{campo}" inválido'})

    return jsonify({"success": True, "message": f'Campo "{campo}" atualizado com sucesso!'})


@app.route("/historico/execucao/<int:run_id>/item/editar_completo", methods=["POST"])
def historico_editar_item_completo(run_id):
    """Edita vários campos de um item histórico de uma vez."""
    data = request.json or {}
    item_id = data.get("item_id")
    dados_linha = data.get("dados_linha")

    if item_id is None or not isinstance(dados_linha, dict) or not dados_linha:
        return jsonify({"success": False, "message": "item_id e dados_linha são obrigatórios"})

    item = db_service.obter_item(item_id)
    if not item or item["run_id"] != run_id:
        return jsonify({"success": False, "message": "Item não encontrado nesta execução"})

    if not db_service.atualizar_item_completo(item_id, dados_linha):
        return jsonify({"success": False, "message": "Nenhum campo válido foi encontrado para atualizar"})

    return jsonify({"success": True, "message": "Item atualizado com sucesso!"})


@app.route("/historico/execucao/<int:run_id>/item/excluir", methods=["POST"])
def historico_excluir_item(run_id):
    """Exclui um item histórico."""
    data = request.json or {}
    item_id = data.get("item_id")
    if item_id is None:
        return jsonify({"success": False, "message": "item_id é obrigatório"})

    item = db_service.obter_item(item_id)
    if not item or item["run_id"] != run_id:
        return jsonify({"success": False, "message": "Item não encontrado nesta execução"})

    db_service.excluir_item(item_id)
    db_service.recalcular_contagens(run_id)
    return jsonify({"success": True, "message": "Item excluído com sucesso!"})


@app.route("/historico/execucao/<int:run_id>/item/mover", methods=["POST"])
def historico_mover_item(run_id):
    """Move um item histórico entre categorias (Avarias / Uso Interno / Erros de Análise)."""
    data = request.json or {}
    item_id = data.get("item_id")
    categoria_destino = data.get("categoria_destino")

    if item_id is None or not categoria_destino:
        return jsonify({"success": False, "message": "item_id e categoria_destino são obrigatórios"})
    if categoria_destino not in _COLUNAS_POR_CATEGORIA:
        return jsonify({"success": False, "message": f'Categoria "{categoria_destino}" inválida'})

    item = db_service.obter_item(item_id)
    if not item or item["run_id"] != run_id:
        return jsonify({"success": False, "message": "Item não encontrado nesta execução"})

    db_service.mover_item_categoria(item_id, categoria_destino)
    db_service.recalcular_contagens(run_id)
    return jsonify({"success": True, "message": f'Item movido para "{categoria_destino}" com sucesso!'})


@app.route("/historico/execucao/<int:run_id>/item/adicionar", methods=["POST"])
def historico_adicionar_item(run_id):
    """Adiciona um novo item a uma execução histórica."""
    execucao_existe = db_service.obter_execucao(run_id)
    if not execucao_existe:
        abort(404)

    data = request.json or {}
    categoria = data.get("categoria")
    dados_linha = data.get("dados_linha")

    if not categoria or categoria not in _COLUNAS_POR_CATEGORIA:
        return jsonify({"success": False, "message": "Categoria inválida"})
    if not isinstance(dados_linha, dict) or not dados_linha:
        return jsonify({"success": False, "message": "dados_linha é obrigatório"})

    db_service.adicionar_item(run_id, categoria, dados_linha)
    db_service.recalcular_contagens(run_id)
    return jsonify({"success": True, "message": "Item adicionado com sucesso!"})


# ---------------------------------------------------------------------------
# Exportação e unificação escopadas a uma execução (gera arquivo novo,
# independente do relatório mestre; não mescla nem sobrescreve nada).
# ---------------------------------------------------------------------------

@app.route("/historico/execucao/<int:run_id>/exportar/<formato>")
def historico_exportar(run_id, formato):
    """Baixa um Excel ou TXT novo contendo só os itens desta execução."""
    if formato not in ("xlsx", "txt"):
        return jsonify({"error": "Formato inválido"}), 400

    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        abort(404)

    dados = _construir_dados_relatorio(execucao["itens"])
    if formato == "xlsx":
        nome_arquivo = execucao_export.gerar_excel_execucao(run_id, dados)
    else:
        nome_arquivo = execucao_export.gerar_txt_execucao(run_id, dados)

    caminho = str(RESULTADOS_DIR / nome_arquivo)
    return send_file(caminho, as_attachment=True, download_name=nome_arquivo)


@app.route("/historico/execucao/<int:run_id>/unificar", methods=["POST"])
def historico_unificar(run_id):
    """Gera um relatório unificado (Avarias + Uso Interno) escopado a esta execução."""
    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        return jsonify({"success": False, "message": "Execução não encontrada"}), 404

    data = request.json or {}
    formato = data.get("formato", "xlsx").lower()
    if formato not in ("xlsx", "txt"):
        return jsonify({"success": False, "message": "Formato inválido. Use 'xlsx' ou 'txt'."}), 400

    dados = _construir_dados_relatorio(execucao["itens"])
    nome_arquivo, total_itens, contenido = execucao_export.gerar_unificado_execucao(
        run_id, dados, formato, return_contenido=True
    )

    db_service.registrar_unificado_gerado(
        nome_arquivo=nome_arquivo,
        formato=formato,
        total_itens=total_itens,
        execucao_id=run_id,
        contagem_por_secao={nome: len(sec.get("dados", [])) for nome, sec in dados.items()},
    )

    return jsonify({
        "success": True,
        "message": "Relatório unificado gerado com sucesso",
        "download_url": url_for("download_relatorio_unificado", filename=nome_arquivo),
        "filename": nome_arquivo,
        "formato": formato,
        "contenido": contenido or "",
        "invertexto": invertexto.obter_config_publica(),
    })


@app.route("/historico/execucao/<int:run_id>/enviar_invertexto", methods=["POST"])
def historico_enviar_invertexto(run_id):
    """Envia a unificação desta execução para o notepad do invertexto.

    O texto é REGERADO no servidor (em vez de aceitar o do cliente): assim o
    conteúdo enviado é exatamente o que o sistema produz para esta execução, e
    o `sanitizar` roda num lugar só — não dá para um cliente mandar texto
    arbitrário para o notepad por esta rota.

    Corpo opcional: {"secoes": [...]} para restringir as seções enviadas.
    """
    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        return jsonify({"success": False, "message": "Execução não encontrada"}), 404

    if not invertexto.configurado():
        return jsonify({
            "success": False,
            "message": "Integração com o invertexto não configurada.",
        }), 400

    dados = _construir_dados_relatorio(execucao["itens"])
    _, _, contenido = execucao_export.gerar_unificado_execucao(
        run_id, dados, "txt", return_contenido=True
    )

    texto = invertexto.sanitizar(contenido or "")
    sucesso, mensagem = invertexto.enviar(texto)

    return jsonify({
        "success": sucesso,
        "message": mensagem,
        "url": invertexto.obter_config_publica()["url"],
        "caracteres": len(texto),
    }), (200 if sucesso else 400)


# ---------------------------------------------------------------------------
# Reanálise versionada de uma execução (ver services/extraction_pipeline.py e
# o versionamento em services/db.py). Diferente de /api/reanalisar_erros
# (reprocessa só itens com erro, sem criar versão nova), esta rota reprocessa
# TODOS os itens da execução e cria uma nova versão na mesma linhagem.
# ---------------------------------------------------------------------------

@app.route("/historico/execucao/<int:run_id>/reanalisar", methods=["POST"])
def historico_reanalisar(run_id):
    """Reanalisa imagens desta execução, criando uma nova versão.

    Corpo JSON opcional para reanálise seletiva (um tipo, vários ou todos):
    {"categorias": ["Avarias", ...], "item_ids": [12, ...]}. Sem corpo (ou
    vazio), reanalisa tudo — comportamento original. `item_ids` (ids do
    banco) tem precedência sobre `categorias`.
    """
    execucao = db_service.obter_execucao(run_id)
    if not execucao:
        abort(404)

    raiz_execucao_id = execucao["raiz_execucao_id"] or execucao["id"]
    versoes = db_service.listar_versoes(raiz_execucao_id)
    versao_mais_recente = max(v["versao"] for v in versoes) if versoes else execucao["versao"]
    if execucao["versao"] != versao_mais_recente:
        return jsonify({
            "success": False,
            "message": "Só é possível reanalisar a versão mais recente desta análise",
        }), 400

    filtros = request.get_json(silent=True) or {}
    categorias = filtros.get("categorias")
    item_ids = filtros.get("item_ids")
    try:
        from ..services.extraction_pipeline import _validar_categorias
        _validar_categorias(categorias)
        if item_ids is not None and (not isinstance(item_ids, list) or not item_ids):
            raise ValueError("Nenhum item selecionado para reanálise")
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400

    with app_state.processamento_lock:
        if app_state.processamento_ativo:
            return jsonify({"success": False, "message": "Já existe um processamento em andamento"}), 400
        app_state.processamento_ativo = True
    if item_ids:
        escopo_txt = f"{len(item_ids)} item(ns) selecionado(s)"
    elif categorias:
        escopo_txt = f"categorias: {', '.join(categorias)}"
    else:
        escopo_txt = "todas as imagens"
    app_state.progresso_atual = {
        "progresso": 0,
        "status": f"Iniciando reanálise da execução #{run_id} ({escopo_txt})",
        "logs": [f"🔄 Iniciando reanálise da execução #{run_id} ({escopo_txt})"],
    }

    def callback_progresso(info):
        progresso = int((info["atual"] / info["total"]) * 100) if info["total"] else 100
        app_state.progresso_atual["progresso"] = progresso
        app_state.progresso_atual["status"] = f"Reanalisando: {info['arquivo']}"
        app_state.progresso_atual["logs"].append(f"[{info['atual']}/{info['total']}] {info['arquivo']}")

    def executar_reanalise():
        try:
            from ..services.extraction_pipeline import reanalisar_execucao

            resultado = reanalisar_execucao(
                run_id, callback_progresso=callback_progresso,
                categorias=categorias, item_ids=item_ids,
            )
            app_state.progresso_atual["resultado"] = resultado
            if resultado.get("sucesso"):
                app_state.progresso_atual["status"] = "Reanálise concluída"
                app_state.progresso_atual["logs"].append(
                    f"✅ Reanálise concluída: nova versão #{resultado.get('run_id')}"
                )
            else:
                app_state.progresso_atual["status"] = f"Erro na reanálise: {resultado.get('erro')}"
                app_state.progresso_atual["logs"].append(f"❌ Erro: {resultado.get('erro')}")
                app_state.progresso_atual["erro"] = resultado.get("erro")
            app_state.progresso_atual["progresso"] = 100
        except Exception as e:
            app_state.progresso_atual["status"] = f"Erro na reanálise: {e}"
            app_state.progresso_atual["logs"].append(f"❌ Erro: {e}")
            app_state.progresso_atual["erro"] = str(e)
        finally:
            app_state.processamento_ativo = False

    try:
        threading.Thread(target=executar_reanalise, daemon=True).start()
    except Exception:
        app_state.processamento_ativo = False
        raise
    return jsonify({"success": True, "message": "Reanálise iniciada!"})
