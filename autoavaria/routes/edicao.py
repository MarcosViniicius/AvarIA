"""
Rotas de edição de dados do relatório: `/editar_dados`, `/salvar_edicao`,
`/salvar_edicao_completa`, `/excluir_linha`, `/mover_item`,
`/adicionar_linha`.

O SQLite é a FONTE da verdade (ver services/mestre.py). A tela lê a visão
mestre do banco e cada edição grava direto nos itens (`report_items`). Não há
mais um Excel intermediário sendo lido/reescrito a cada clique: o `.xlsx` é só
export, gerado sob demanda.

A linha da tela carrega `id_linha` — o id do item no banco — então as rotas
sabem exatamente qual item editar. Uma mesma linha exibida pode corresponder a
vários itens (a mesma imagem processada em execuções diferentes); nesse caso a
edição é propagada para todos os equivalentes, via
`db.buscar_itens_por_caminho`.
"""

from flask import flash, jsonify, make_response, redirect, render_template, request, url_for

from .blueprint import web_bp as app
from ..services import db, mestre
from ..services.relatorio_view import _construir_registro


def _item_e_valores(linha_id, sheet_name):
    """(item bruto, linha no formato das colunas da tela) a partir do id.

    Devolve ``(None, None)`` se o id não existir mais (linha removida em outra
    aba, banco reiniciado, etc.).
    """
    item = db.obter_item(linha_id)
    if not item:
        return None, None
    return item, _construir_registro(sheet_name, item)


def _sincronizar_edicao_no_banco(sheet_name: str, valores_originais: dict, campo: str, novo_valor) -> int:
    """Propaga uma edição de campo para o(s) item(ns) correspondentes no banco.

    Devolve quantos itens foram atualizados. Atualiza TODAS as correspondências
    exatas: a mesma imagem processada em várias execuções gera linhas
    equivalentes (uma por execução), e editar uma delas deve refletir em todas.
    """
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_name, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        if not ids:
            return 0
        return db.atualizar_itens_campo(ids, campo, novo_valor)
    except Exception as e:
        print(f"⚠️ Não foi possível salvar a edição no banco: {e}")
        return 0


def _sincronizar_edicao_completa_no_banco(sheet_name: str, valores_originais: dict, dados_linha: dict) -> int:
    """Mesma ideia de `_sincronizar_edicao_no_banco`, mas para a linha inteira."""
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_name, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        if not ids:
            return 0
        return db.atualizar_itens_completo(ids, dados_linha)
    except Exception as e:
        print(f"⚠️ Não foi possível salvar a edição no banco: {e}")
        return 0


def _sincronizar_exclusao_no_banco(sheet_name: str, valores_originais: dict) -> int:
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_name, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        if not ids:
            return 0
        runs = db.excluir_itens(ids)
        for run_id in runs:
            db.recalcular_contagens(run_id)
        return len(ids)
    except Exception as e:
        print(f"⚠️ Não foi possível excluir no banco: {e}")
        return 0


def _sincronizar_movimentacao_no_banco(sheet_origem: str, sheet_destino: str, valores_originais: dict, nova_linha: dict) -> int:
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_origem, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        if not ids:
            return 0
        db.mover_itens_categoria(ids, sheet_destino)
        db.atualizar_itens_completo(ids, nova_linha)
        return len(ids)
    except Exception as e:
        print(f"⚠️ Não foi possível mover no banco: {e}")
        return 0


def _aviso_sincronizacao(afetados: int) -> str:
    """Mensagem quando a linha não pôde ser identificada de forma única.

    Sem isso a falha seria silenciosa: o usuário veria "salvo", mas a linha
    não teria mudado (ou teria mudado só parte das duplicatas).
    """
    if afetados > 0:
        return ""
    return (
        " Atenção: não foi possível identificar esta linha de forma única "
        "(há itens diferentes associados à mesma imagem), então nada foi "
        "alterado."
    )


def _colunas_da_categoria(sheet_name: str):
    """Colunas de dados editáveis de uma categoria (sem 'Caminho da Imagem')."""
    return mestre.COLUNAS_POR_CATEGORIA.get(sheet_name, [])


@app.route("/editar_dados")
def editar_dados():
    """Página de edição de dados do relatório (visão mestre do banco)."""
    try:
        secoes = mestre.obter_secoes_mestre()

        if not secoes:
            flash("Nenhum relatório encontrado para editar. Execute o processamento primeiro.", "warning")
            return redirect(url_for("configuracoes"))

        dados = {}
        for sheet_name, info in secoes.items():
            dados[sheet_name] = {
                # 'id_linha' entra na lista de colunas (mas é ocultado no
                # template: não é um campo de dado, é o identificador da linha).
                "colunas": info["colunas"] + ["id_linha"],
                "dados": info["dados"],
                "total": info["total"],
            }

        response = make_response(render_template("editar_dados.html", dados=dados))
        # Evitar cache para garantir dados atualizados
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    except Exception as e:
        print(f"Erro ao carregar dados para edição: {e}")
        flash(f"Erro ao carregar dados para edição: {str(e)}", "danger")
        return redirect(url_for("configuracoes"))


@app.route("/salvar_edicao", methods=["POST"])
def salvar_edicao():
    """Salva a edição de um único campo de uma linha."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        linha_id = data.get("linha_id")
        campo = data.get("campo")
        novo_valor = data.get("novo_valor")

        print(
            f"📝 Salvando edição: Sheet={sheet_name}, Linha={linha_id}, Campo={campo}, Valor={novo_valor}"
        )

        if not sheet_name:
            return jsonify({"success": False, "message": "Nome da planilha é obrigatório"})
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})
        if not campo:
            return jsonify({"success": False, "message": "Nome do campo é obrigatório"})
        if novo_valor is None:
            novo_valor = ""  # Permitir valores vazios

        _, valores_originais = _item_e_valores(linha_id, sheet_name)
        if valores_originais is None:
            return jsonify({"success": False, "message": "Linha não encontrada"})

        colunas_validas = _colunas_da_categoria(sheet_name)
        if colunas_validas and campo not in colunas_validas:
            return jsonify({
                "success": False,
                "message": f'Campo "{campo}" não encontrado. Campos disponíveis: {colunas_validas}',
            })

        afetados = _sincronizar_edicao_no_banco(sheet_name, valores_originais, campo, novo_valor)

        print("✅ Edição salva com sucesso!")
        return jsonify({
            "success": True,
            "message": f'Campo "{campo}" atualizado com sucesso!' + _aviso_sincronizacao(afetados),
        })

    except Exception as e:
        print(f"❌ Erro ao salvar edição: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


@app.route("/salvar_edicao_completa", methods=["POST"])
def salvar_edicao_completa():
    """Salva a edição de vários campos de uma linha de uma vez."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        linha_id = data.get("linha_id")
        dados_linha = data.get("dados_linha")

        print(
            f"📝 Salvando edição completa: Sheet={sheet_name}, Linha={linha_id}, Dados={dados_linha}"
        )

        if not sheet_name:
            return jsonify({"success": False, "message": "Nome da planilha é obrigatório"})
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})
        if not dados_linha or not isinstance(dados_linha, dict):
            return jsonify({"success": False, "message": "Dados da linha são obrigatórios"})

        _, valores_originais = _item_e_valores(linha_id, sheet_name)
        if valores_originais is None:
            return jsonify({"success": False, "message": "Linha não encontrada"})

        colunas_validas = _colunas_da_categoria(sheet_name)
        campos_atualizados = []
        for campo, novo_valor in dados_linha.items():
            if campo in colunas_validas:
                campos_atualizados.append(campo)
                print(f"📊 {campo}: {valores_originais.get(campo)} -> {novo_valor}")
            else:
                print(f"⚠️ Campo '{campo}' não encontrado na planilha")

        if not campos_atualizados:
            return jsonify({
                "success": False,
                "message": "Nenhum campo válido foi encontrado para atualizar",
            })

        afetados = _sincronizar_edicao_completa_no_banco(sheet_name, valores_originais, dados_linha)

        print(
            f"✅ Edição completa salva com sucesso! Campos atualizados: {', '.join(campos_atualizados)}"
        )
        return jsonify({
            "success": True,
            "message": f"Linha atualizada com sucesso! ({len(campos_atualizados)} campos alterados)"
            + _aviso_sincronizacao(afetados),
        })

    except Exception as e:
        print(f"❌ Erro ao salvar edição completa: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


@app.route("/excluir_linha", methods=["POST"])
def excluir_linha():
    """Exclui uma linha do relatório."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        linha_id = data.get("linha_id")

        print(f"🗑️ Excluindo linha: Sheet={sheet_name}, Linha={linha_id}")

        if not sheet_name:
            return jsonify({"success": False, "message": "Nome da planilha é obrigatório"})
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})

        _, valores_originais = _item_e_valores(linha_id, sheet_name)
        if valores_originais is None:
            return jsonify({"success": False, "message": "Linha não encontrada"})

        afetados = _sincronizar_exclusao_no_banco(sheet_name, valores_originais)

        print("✅ Linha excluída com sucesso!")
        return jsonify({
            "success": True,
            "message": "Linha excluída com sucesso!" + _aviso_sincronizacao(afetados),
        })

    except Exception as e:
        print(f"❌ Erro ao excluir linha: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


def _nova_linha_para_destino(sheet_destino: str, linha_dados: dict) -> dict:
    """Adapta uma linha de origem para as colunas da categoria de destino."""
    if sheet_destino == "Avarias":
        return {
            "Produto": linha_dados.get("Produto", linha_dados.get("Arquivo", "N/A")),
            "Quantidade": linha_dados.get("Quantidade", 1),
            "Peso": linha_dados.get("Peso", "N/A"),
            "Observação da Mensagem": linha_dados.get("Observação da Mensagem", "N/A"),
            "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
            "Ver Imagem": linha_dados.get("Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A")),
        }
    if sheet_destino == "Uso Interno":
        return {
            "Produto": linha_dados.get("Produto", linha_dados.get("Arquivo", "N/A")),
            "Quantidade": linha_dados.get("Quantidade", 1),
            "Marca": linha_dados.get("Marca", "N/A"),
            "Código de Barras": linha_dados.get("Código de Barras", "N/A"),
            "Observação da Mensagem": linha_dados.get("Observação da Mensagem", "N/A"),
            "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
            "Ver Imagem": linha_dados.get("Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A")),
        }
    # Erros de Análise
    return {
        "Arquivo": linha_dados.get("Arquivo", linha_dados.get("Produto", "N/A")),
        "Detalhes do Erro": linha_dados.get("Detalhes do Erro", "Movido de outra planilha"),
        "Observação da Mensagem": linha_dados.get("Observação da Mensagem", "N/A"),
        "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
        "Ver Imagem": linha_dados.get("Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A")),
    }


@app.route("/mover_item", methods=["POST"])
def mover_item():
    """Move um item de uma categoria para outra."""
    try:
        data = request.json
        sheet_origem = data.get("sheet_origem")
        sheet_destino = data.get("sheet_destino")
        linha_id = data.get("linha_id")

        print(f"🔄 Movendo item: {sheet_origem} -> {sheet_destino}, Linha={linha_id}")

        if not sheet_origem or not sheet_destino:
            return jsonify({
                "success": False,
                "message": "Planilhas de origem e destino são obrigatórias",
            })
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})
        if sheet_origem == sheet_destino:
            return jsonify({
                "success": False,
                "message": "Planilha de origem e destino não podem ser iguais",
            })
        if sheet_destino not in mestre.ORDEM_CATEGORIAS:
            return jsonify({
                "success": False,
                "message": f'Tipo de planilha destino "{sheet_destino}" não reconhecido',
            })

        _, valores_originais = _item_e_valores(linha_id, sheet_origem)
        if valores_originais is None:
            return jsonify({"success": False, "message": "Linha não encontrada"})

        nova_linha = _nova_linha_para_destino(sheet_destino, valores_originais)
        afetados = _sincronizar_movimentacao_no_banco(
            sheet_origem, sheet_destino, valores_originais, nova_linha
        )

        produto_nome = nova_linha.get("Produto", nova_linha.get("Arquivo", "Item"))
        print(
            f"✅ Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!"
        )
        return jsonify({
            "success": True,
            "message": f"Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!"
            + _aviso_sincronizacao(afetados),
        })

    except Exception as e:
        print(f"❌ Erro ao mover item: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


@app.route("/adicionar_linha", methods=["POST"])
def adicionar_linha():
    """Adiciona uma nova linha ao relatório (item manual, sem execução)."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        dados_linha = data.get("dados_linha")

        print(f"➕ Adicionando linha: Sheet={sheet_name}, Dados={dados_linha}")

        if not sheet_name:
            return jsonify({"success": False, "message": "Nome da planilha é obrigatório"})
        if sheet_name not in mestre.ORDEM_CATEGORIAS:
            return jsonify({
                "success": False,
                "message": f'Tipo de planilha "{sheet_name}" não reconhecido',
            })
        if not dados_linha or not isinstance(dados_linha, dict):
            return jsonify({"success": False, "message": "Dados da linha são obrigatórios"})

        # Campos obrigatórios conforme a categoria.
        if sheet_name == "Erros de Análise":
            obrigatorios = ["Arquivo"]
        else:
            obrigatorios = ["Produto", "Quantidade"]
        for campo in obrigatorios:
            if not str(dados_linha.get(campo, "")).strip():
                return jsonify({"success": False, "message": f'Campo "{campo}" é obrigatório'})

        # Mantém apenas as colunas conhecidas da categoria.
        colunas = _colunas_da_categoria(sheet_name)
        nova_linha = {col: dados_linha.get(col, "") for col in colunas if col != "Ver Imagem"}
        # 'Ver Imagem' deve acompanhar o caminho, quando houver.
        if "Caminho da Imagem" in nova_linha:
            nova_linha["Ver Imagem"] = dados_linha.get(
                "Ver Imagem", nova_linha["Caminho da Imagem"]
            )

        # run_id=None: item digitado manualmente, sem execução automática por
        # trás. Não aparece em "Histórico > Execução", mas fica no banco.
        db.adicionar_item(None, sheet_name, nova_linha)

        print(f"✅ Linha adicionada com sucesso! Sheet={sheet_name}")
        return jsonify({
            "success": True,
            "message": "Nova linha adicionada com sucesso!",
        })

    except Exception as e:
        print(f"❌ Erro ao adicionar linha: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})
