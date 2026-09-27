"""
Rotas de edição de dados do relatório: `/editar_dados`, `/salvar_edicao`,
`/salvar_edicao_completa`, `/excluir_linha`, `/mover_item`,
`/adicionar_linha`.

A leitura/backup/gravação do Excel (comuns às 5 rotas de mutação) foi
extraída para ``autoavaria.services.report_editing``; a lógica específica de
cada rota permanece aqui.
"""

import os
from datetime import datetime

import pandas as pd
from flask import flash, jsonify, make_response, redirect, render_template, request, url_for

from .blueprint import web_bp as app
from .context import ARQUIVO_SAIDA_EXCEL
from ..services import db
from ..services.report_editing import (
    carregar_todas_sheets,
    fazer_backup,
    salvar_todas_sheets,
)


def _sincronizar_edicao_no_banco(sheet_name: str, valores_originais: dict, campo: str, novo_valor) -> int:
    """Propaga uma edição de campo do Excel para o(s) item(ns) no banco.

    Devolve quantos itens foram atualizados. Atualiza TODAS as correspondências
    exatas: a mesma imagem processada em várias execuções gera linhas
    equivalentes (uma por execução), e editar uma linha do Excel deve refletir
    em todas elas — antes o código exigia uma única linha e desistia em 22% dos
    casos, deixando o Histórico desatualizado em silêncio.

    Sem isso, editar um item aqui corrigia só o Excel; o Histórico e as
    exportações por execução continuavam mostrando o valor antigo.
    """
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_name, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        return db.atualizar_itens_campo(ids, campo, novo_valor)
    except Exception as e:
        print(f"⚠️ Não foi possível sincronizar a edição com o banco: {e}")
        return 0


def _sincronizar_edicao_completa_no_banco(sheet_name: str, valores_originais: dict, dados_linha: dict) -> int:
    """Mesma ideia de `_sincronizar_edicao_no_banco`, mas para a linha inteira."""
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_name, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        return db.atualizar_itens_completo(ids, dados_linha)
    except Exception as e:
        print(f"⚠️ Não foi possível sincronizar a edição com o banco: {e}")
        return 0


def _sincronizar_exclusao_no_banco(sheet_name: str, valores_originais: dict) -> int:
    try:
        ids = db.buscar_itens_por_caminho(
            sheet_name, valores_originais.get("Caminho da Imagem", ""), valores_originais
        )
        runs = db.excluir_itens(ids)
        for run_id in runs:
            db.recalcular_contagens(run_id)
        return len(ids)
    except Exception as e:
        print(f"⚠️ Não foi possível sincronizar a exclusão com o banco: {e}")
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
        print(f"⚠️ Não foi possível sincronizar a movimentação com o banco: {e}")
        return 0


def _aviso_sincronizacao(afetados: int) -> str:
    """Mensagem sobre o efeito no banco, para não haver alteração silenciosa.

    Quando nada sincroniza, o usuário precisa saber: a edição valeu no Excel
    (que é o que as telas de edição mostram), mas o Histórico continuará com o
    valor antigo. Silêncio aqui já causou divergência percebida como bug.
    """
    if afetados > 0:
        return ""
    return (
        " Atenção: não foi possível identificar esta linha no Histórico "
        "(há itens diferentes associados à mesma imagem), então o Histórico "
        "continua com o valor anterior — a alteração vale para o relatório."
    )


@app.route("/editar_dados")
def editar_dados():
    """Página de edição de dados do relatório."""
    try:
        # Tentar encontrar o arquivo em diferentes caminhos possíveis
        caminhos_possiveis = [
            ARQUIVO_SAIDA_EXCEL,
            os.path.join(os.getcwd(), "resultados", "Relatorio_Mestre_Produtos.xlsx"),
            "./resultados/Relatorio_Mestre_Produtos.xlsx"
        ]

        arquivo_encontrado = None
        for caminho in caminhos_possiveis:
            if os.path.exists(caminho):
                arquivo_encontrado = caminho
                break

        if not arquivo_encontrado:
            flash("Nenhum relatório encontrado para editar. Execute o processamento primeiro.", "warning")
            return redirect(url_for("configuracoes"))

        # Verificar se o arquivo não está vazio
        if os.path.getsize(arquivo_encontrado) == 0:
            flash("O arquivo de relatório está vazio. Execute o processamento novamente.", "warning")
            return redirect(url_for("configuracoes"))

        # Ler o arquivo Excel
        sheets = carregar_todas_sheets(arquivo_encontrado)

        if not sheets:
            flash("O relatório não contém planilhas válidas.", "warning")
            return redirect(url_for("configuracoes"))

        dados = {}

        for sheet_name, df in sheets.items():
            if df is not None and not df.empty:
                # Adicionar índice para edição
                df = df.reset_index()
                df["id_linha"] = df.index

                # Tratar valores NaN para evitar erros no template
                df = df.fillna("")  # Substitui NaN por string vazia

                dados[sheet_name] = {
                    "colunas": df.columns.tolist(),
                    "dados": df.to_dict("records"),
                    "total": len(df),
                }

        if not dados:
            flash("O relatório não contém dados para editar. Todas as planilhas estão vazias.", "warning")
            return redirect(url_for("configuracoes"))

        response = make_response(render_template("editar_dados.html", dados=dados))
        # Evitar cache para garantir dados atualizados
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    except FileNotFoundError:
        flash("Arquivo de relatório não encontrado.", "danger")
        return redirect(url_for("configuracoes"))
    except PermissionError:
        flash("Sem permissão para acessar o arquivo de relatório.", "danger")
        return redirect(url_for("configuracoes"))
    except pd.errors.EmptyDataError:
        flash("Arquivo de relatório está vazio ou corrompido.", "danger")
        return redirect(url_for("configuracoes"))
    except Exception as e:
        print(f"Erro ao carregar dados para edição: {e}")
        flash(f"Erro ao carregar dados para edição: {str(e)}", "danger")
        return redirect(url_for("configuracoes"))


@app.route("/salvar_edicao", methods=["POST"])
def salvar_edicao():
    """Salva as edições feitas nos dados."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        linha_id = data.get("linha_id")
        campo = data.get("campo")
        novo_valor = data.get("novo_valor")

        print(
            f"📝 Salvando edição: Sheet={sheet_name}, Linha={linha_id}, Campo={campo}, Valor={novo_valor}"
        )

        # Validação mais detalhada
        if not sheet_name:
            return jsonify(
                {"success": False, "message": "Nome da planilha é obrigatório"}
            )
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})
        if not campo:
            return jsonify({"success": False, "message": "Nome do campo é obrigatório"})
        if novo_valor is None:
            novo_valor = ""  # Permitir valores vazios

        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify(
                {"success": False, "message": "Arquivo de relatório não encontrado"}
            )

        # Ler arquivo Excel
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        if sheet_name not in sheets:
            return jsonify(
                {"success": False, "message": f'Planilha "{sheet_name}" não encontrada'}
            )

        df = sheets[sheet_name]

        # Verificar se a linha existe
        if linha_id >= len(df) or linha_id < 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Linha {linha_id} não encontrada (total: {len(df)} linhas)",
                }
            )

        # Verificar se a coluna existe
        if campo not in df.columns:
            return jsonify(
                {
                    "success": False,
                    "message": f'Campo "{campo}" não encontrado. Campos disponíveis: {list(df.columns)}',
                }
            )

        # Validar tipos de dados se necessário
        original_value = df.at[linha_id, campo]
        valores_originais = df.iloc[linha_id].to_dict()
        print(f"📊 Valor original: {original_value} -> Novo valor: {novo_valor}")

        # Atualizar valor
        df.at[linha_id, campo] = novo_valor
        sheets[sheet_name] = df

        # Criar backup antes de salvar
        fazer_backup(ARQUIVO_SAIDA_EXCEL)

        # Salvar arquivo Excel
        salvar_todas_sheets(ARQUIVO_SAIDA_EXCEL, sheets)
        afetados = _sincronizar_edicao_no_banco(sheet_name, valores_originais, campo, novo_valor)

        print(f"✅ Edição salva com sucesso!")
        return jsonify(
            {
                "success": True,
                "message": f'Campo "{campo}" atualizado com sucesso!'
                + _aviso_sincronizacao(afetados),
            }
        )

    except FileNotFoundError:
        return jsonify(
            {"success": False, "message": "Arquivo de relatório não encontrado"}
        )
    except PermissionError:
        return jsonify(
            {
                "success": False,
                "message": "Sem permissão para editar o arquivo. Verifique se está aberto em outro programa",
            }
        )
    except pd.errors.EmptyDataError:
        return jsonify(
            {
                "success": False,
                "message": "Arquivo de relatório está vazio ou corrompido",
            }
        )
    except Exception as e:
        print(f"❌ Erro ao salvar edição: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


@app.route("/salvar_edicao_completa", methods=["POST"])
def salvar_edicao_completa():
    """Salva as edições completas feitas em uma linha."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        linha_id = data.get("linha_id")
        dados_linha = data.get("dados_linha")

        print(
            f"📝 Salvando edição completa: Sheet={sheet_name}, Linha={linha_id}, Dados={dados_linha}"
        )

        # Validação
        if not sheet_name:
            return jsonify(
                {"success": False, "message": "Nome da planilha é obrigatório"}
            )
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})
        if not dados_linha or not isinstance(dados_linha, dict):
            return jsonify(
                {"success": False, "message": "Dados da linha são obrigatórios"}
            )

        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify(
                {"success": False, "message": "Arquivo de relatório não encontrado"}
            )

        # Ler arquivo Excel
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        if sheet_name not in sheets:
            return jsonify(
                {"success": False, "message": f'Planilha "{sheet_name}" não encontrada'}
            )

        df = sheets[sheet_name]

        # Verificar se a linha existe
        if linha_id >= len(df) or linha_id < 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Linha {linha_id} não encontrada (total: {len(df)} linhas)",
                }
            )

        # Criar backup antes de salvar
        fazer_backup(ARQUIVO_SAIDA_EXCEL)
        valores_originais = df.iloc[linha_id].to_dict()

        # Atualizar todos os campos fornecidos
        campos_atualizados = []
        for campo, novo_valor in dados_linha.items():
            if campo in df.columns:
                valor_original = df.at[linha_id, campo]
                df.at[linha_id, campo] = novo_valor
                campos_atualizados.append(campo)
                print(f"📊 {campo}: {valor_original} -> {novo_valor}")
            else:
                print(f"⚠️ Campo '{campo}' não encontrado na planilha")

        if not campos_atualizados:
            return jsonify(
                {
                    "success": False,
                    "message": "Nenhum campo válido foi encontrado para atualizar",
                }
            )

        sheets[sheet_name] = df

        # Salvar arquivo Excel
        salvar_todas_sheets(ARQUIVO_SAIDA_EXCEL, sheets)
        afetados = _sincronizar_edicao_completa_no_banco(sheet_name, valores_originais, dados_linha)

        print(
            f"✅ Edição completa salva com sucesso! Campos atualizados: {', '.join(campos_atualizados)}"
        )
        return jsonify(
            {
                "success": True,
                "message": f"Linha atualizada com sucesso! ({len(campos_atualizados)} campos alterados)"
                + _aviso_sincronizacao(afetados),
            }
        )

    except FileNotFoundError:
        return jsonify(
            {"success": False, "message": "Arquivo de relatório não encontrado"}
        )
    except PermissionError:
        return jsonify(
            {
                "success": False,
                "message": "Sem permissão para editar o arquivo. Verifique se está aberto em outro programa",
            }
        )
    except pd.errors.EmptyDataError:
        return jsonify(
            {
                "success": False,
                "message": "Arquivo de relatório está vazio ou corrompido",
            }
        )
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
            return jsonify(
                {"success": False, "message": "Nome da planilha é obrigatório"}
            )
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})

        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify(
                {"success": False, "message": "Arquivo de relatório não encontrado"}
            )

        # Ler arquivo Excel
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        if sheet_name not in sheets:
            return jsonify(
                {"success": False, "message": f'Planilha "{sheet_name}" não encontrada'}
            )

        df = sheets[sheet_name]

        # Verificar se a linha existe
        if linha_id >= len(df) or linha_id < 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Linha {linha_id} não encontrada (total: {len(df)} linhas)",
                }
            )

        # Criar backup antes de excluir
        fazer_backup(ARQUIVO_SAIDA_EXCEL)
        valores_originais = df.iloc[linha_id].to_dict()

        # Remover linha
        df = df.drop(df.index[linha_id]).reset_index(drop=True)
        sheets[sheet_name] = df

        # Salvar arquivo Excel
        salvar_todas_sheets(ARQUIVO_SAIDA_EXCEL, sheets)
        afetados = _sincronizar_exclusao_no_banco(sheet_name, valores_originais)

        print(f"✅ Linha excluída com sucesso!")
        return jsonify(
            {
                "success": True,
                "message": "Linha excluída com sucesso!" + _aviso_sincronizacao(afetados),
            }
        )

    except FileNotFoundError:
        return jsonify(
            {"success": False, "message": "Arquivo de relatório não encontrado"}
        )
    except PermissionError:
        return jsonify(
            {
                "success": False,
                "message": "Sem permissão para editar o arquivo. Verifique se está aberto em outro programa",
            }
        )
    except Exception as e:
        print(f"❌ Erro ao excluir linha: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


@app.route("/mover_item", methods=["POST"])
def mover_item():
    """Move um item de uma tabela para outra."""
    try:
        data = request.json
        sheet_origem = data.get("sheet_origem")
        sheet_destino = data.get("sheet_destino")
        linha_id = data.get("linha_id")

        print(f"🔄 Movendo item: {sheet_origem} -> {sheet_destino}, Linha={linha_id}")

        # Validação
        if not sheet_origem or not sheet_destino:
            return jsonify(
                {
                    "success": False,
                    "message": "Planilhas de origem e destino são obrigatórias",
                }
            )
        if linha_id is None:
            return jsonify({"success": False, "message": "ID da linha é obrigatório"})
        if sheet_origem == sheet_destino:
            return jsonify(
                {
                    "success": False,
                    "message": "Planilha de origem e destino não podem ser iguais",
                }
            )

        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify(
                {"success": False, "message": "Arquivo de relatório não encontrado"}
            )

        # Ler arquivo Excel
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        if sheet_origem not in sheets:
            return jsonify(
                {
                    "success": False,
                    "message": f'Planilha de origem "{sheet_origem}" não encontrada',
                }
            )
        if sheet_destino not in sheets:
            # Se a planilha de destino não existir, criar uma vazia
            # Definir colunas baseadas no tipo de planilha
            if sheet_destino == "Avarias":
                colunas_destino = [
                    "Produto",
                    "Peso",
                    "Observação da Mensagem",
                    "Caminho da Imagem",
                    "Ver Imagem",
                ]
            elif sheet_destino == "Uso Interno":
                colunas_destino = [
                    "Produto",
                    "Marca",
                    "Código de Barras",
                    "Observação da Mensagem",
                    "Caminho da Imagem",
                    "Ver Imagem",
                ]
            elif sheet_destino == "Erros de Análise":
                colunas_destino = [
                    "Arquivo",
                    "Detalhes do Erro",
                    "Observação da Mensagem",
                    "Caminho da Imagem",
                    "Ver Imagem",
                ]
            else:
                return jsonify(
                    {
                        "success": False,
                        "message": f'Tipo de planilha destino "{sheet_destino}" não reconhecido',
                    }
                )

            sheets[sheet_destino] = pd.DataFrame(columns=colunas_destino)

        df_origem = sheets[sheet_origem]
        df_destino = sheets[sheet_destino]

        # Verificar se a linha existe na origem
        if linha_id >= len(df_origem) or linha_id < 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Linha {linha_id} não encontrada na planilha origem (total: {len(df_origem)} linhas)",
                }
            )

        # Obter dados da linha
        linha_dados = df_origem.iloc[linha_id].copy()

        # Criar backup antes de mover
        fazer_backup(ARQUIVO_SAIDA_EXCEL)

        # Adaptar dados para a planilha de destino
        nova_linha = {}

        if sheet_destino == "Avarias":
            nova_linha = {
                "Produto": linha_dados.get(
                    "Produto", linha_dados.get("Arquivo", "N/A")
                ),
                "Peso": linha_dados.get("Peso", "N/A"),
                "Observação da Mensagem": linha_dados.get(
                    "Observação da Mensagem", "N/A"
                ),
                "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
                "Ver Imagem": linha_dados.get(
                    "Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A")
                ),
            }
        elif sheet_destino == "Uso Interno":
            nova_linha = {
                "Produto": linha_dados.get(
                    "Produto", linha_dados.get("Arquivo", "N/A")
                ),
                "Marca": linha_dados.get("Marca", "N/A"),
                "Código de Barras": linha_dados.get("Código de Barras", "N/A"),
                "Observação da Mensagem": linha_dados.get(
                    "Observação da Mensagem", "N/A"
                ),
                "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
                "Ver Imagem": linha_dados.get(
                    "Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A")
                ),
            }
        elif sheet_destino == "Erros de Análise":
            nova_linha = {
                "Arquivo": linha_dados.get(
                    "Arquivo", linha_dados.get("Produto", "N/A")
                ),
                "Detalhes do Erro": linha_dados.get(
                    "Detalhes do Erro", "Movido de outra planilha"
                ),
                "Observação da Mensagem": linha_dados.get(
                    "Observação da Mensagem", "N/A"
                ),
                "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
                "Ver Imagem": linha_dados.get(
                    "Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A")
                ),
            }

        # Adicionar nova linha à planilha de destino
        df_destino = pd.concat(
            [df_destino, pd.DataFrame([nova_linha])], ignore_index=True
        )

        # Remover linha da planilha de origem
        df_origem = df_origem.drop(df_origem.index[linha_id]).reset_index(drop=True)

        # Atualizar sheets
        sheets[sheet_origem] = df_origem
        sheets[sheet_destino] = df_destino

        # Salvar arquivo Excel (só grava planilhas não vazias)
        salvar_todas_sheets(ARQUIVO_SAIDA_EXCEL, sheets, apenas_nao_vazias=True)
        afetados = _sincronizar_movimentacao_no_banco(sheet_origem, sheet_destino, linha_dados.to_dict(), nova_linha)

        produto_nome = nova_linha.get("Produto", nova_linha.get("Arquivo", "Item"))
        print(
            f"✅ Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!"
        )

        return jsonify(
            {
                "success": True,
                "message": f"Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!"
                + _aviso_sincronizacao(afetados),
            }
        )

    except FileNotFoundError:
        return jsonify(
            {"success": False, "message": "Arquivo de relatório não encontrado"}
        )
    except PermissionError:
        return jsonify(
            {
                "success": False,
                "message": "Sem permissão para editar o arquivo. Verifique se está aberto em outro programa",
            }
        )
    except pd.errors.EmptyDataError:
        return jsonify(
            {
                "success": False,
                "message": "Arquivo de relatório está vazio ou corrompido",
            }
        )
    except Exception as e:
        print(f"❌ Erro ao mover item: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})


@app.route("/adicionar_linha", methods=["POST"])
def adicionar_linha():
    """Adiciona uma nova linha ao relatório."""
    try:
        data = request.json
        sheet_name = data.get("sheet_name")
        dados_linha = data.get("dados_linha")

        print(f"➕ Adicionando linha: Sheet={sheet_name}, Dados={dados_linha}")

        if not sheet_name:
            return jsonify(
                {"success": False, "message": "Nome da planilha é obrigatório"}
            )
        if not dados_linha or not isinstance(dados_linha, dict):
            return jsonify(
                {"success": False, "message": "Dados da linha são obrigatórios"}
            )

        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify(
                {"success": False, "message": "Arquivo de relatório não encontrado"}
            )

        # Ler arquivo Excel
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        if sheet_name not in sheets:
            return jsonify(
                {"success": False, "message": f'Planilha "{sheet_name}" não encontrada'}
            )

        df = sheets[sheet_name]

        # Validar campos obrigatórios (se aplicável)
        campos_obrigatorios = ["Produto", "Quantidade"]
        for campo in campos_obrigatorios:
            if campo in df.columns and not dados_linha.get(campo, "").strip():
                return jsonify(
                    {"success": False, "message": f'Campo "{campo}" é obrigatório'}
                )

        # Criar nova linha com as colunas existentes
        nova_linha = {}
        for coluna in df.columns:
            valor = dados_linha.get(coluna, "")
            # Adicionar timestamp para campos de data se estiverem vazios
            if "Data" in coluna and not valor:
                valor = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            nova_linha[coluna] = valor

        # Criar backup antes de adicionar
        fazer_backup(ARQUIVO_SAIDA_EXCEL)

        # Adicionar nova linha
        df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
        sheets[sheet_name] = df

        # Salvar arquivo Excel
        salvar_todas_sheets(ARQUIVO_SAIDA_EXCEL, sheets)
        try:
            # run_id=None: item digitado manualmente, sem execução automática
            # por trás. Não aparece em nenhum "Histórico > Execução", mas
            # fica registrado no banco para consistência.
            db.adicionar_item(None, sheet_name, nova_linha)
        except Exception as e:
            print(f"⚠️ Não foi possível sincronizar a nova linha com o banco: {e}")

        print(f"✅ Linha adicionada com sucesso! Total de linhas: {len(df)}")
        return jsonify(
            {
                "success": True,
                "message": f"Nova linha adicionada com sucesso! Total: {len(df)} registros",
            }
        )

    except FileNotFoundError:
        return jsonify(
            {"success": False, "message": "Arquivo de relatório não encontrado"}
        )
    except PermissionError:
        return jsonify(
            {
                "success": False,
                "message": "Sem permissão para editar o arquivo. Verifique se está aberto em outro programa",
            }
        )
    except Exception as e:
        print(f"❌ Erro ao adicionar linha: {e}")
        return jsonify({"success": False, "message": f"Erro inesperado: {str(e)}"})
