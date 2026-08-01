"""
Funcionalidade de unificação de relatórios: `/api/unificar_relatorio`,
`/download_relatorio_unificado/<filename>`, `/api/opcoes_unificacao`.
"""

import os
from datetime import datetime

import pandas as pd
from flask import jsonify, request, send_file, url_for

from .blueprint import web_bp as app
from .context import BASE_PATH
from ..services import db as db_service
from ..services.export_service import escrever_txt_compacto, escrever_xlsx, filtrar_colunas
from ..services.relatorio_view import _construir_dados_relatorio
from ..services.unification import unificar_itens_avarias, unificar_itens_uso_interno


def _sheets_da_ultima_execucao():
    """Monta um dict {sheet_name: DataFrame} a partir da ÚLTIMA execução
    registrada no banco - a mesma fonte que a aba Relatório mostra na tela
    (ver routes/relatorio.py). "Unificar Relatório" existe para dar uma
    visão consolidada do que acabou de ser analisado, não do histórico
    inteiro acumulado no Excel mestre - por isso não lê ARQUIVO_SAIDA_EXCEL.

    Retorna None se ainda não houver nenhuma execução no banco (banco
    recém-criado, por exemplo) - quem chama decide como sinalizar isso.
    """
    execucoes = db_service.listar_execucoes(limite=1)
    if not execucoes:
        return None

    execucao = db_service.obter_execucao(execucoes[0]["id"])
    dados = _construir_dados_relatorio(execucao["itens"]) if execucao else {}

    return {
        categoria: pd.DataFrame(info["dados"], columns=info["colunas"])
        for categoria, info in dados.items()
    }


def processar_unificacao_completa(secoes_filtro=None, colunas_filtro=None):
    """Processa todo o relatório aplicando unificação e gerando planilha de auditoria.

    Args:
        secoes_filtro: Lista de seções para processar (None = todas)
        colunas_filtro: Dicionário {secao: [colunas]} para filtrar colunas (None = todas)

    Returns:
        tuple: (sucesso, mensagem, caminho_arquivo_gerado)
    """
    try:
        sheets = _sheets_da_ultima_execucao()
        if sheets is None:
            return False, "Nenhuma execução encontrada. Processe alguma análise primeiro.", None

        # Preparar arquivo de saída
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_unificado = os.path.join(
            BASE_PATH,
            "resultados",
            f"Relatorio_Unificado_{timestamp}.xlsx"
        )

        # Monta cada seção (unificando Avarias/Uso Interno quando aplicável)
        # e delega a escrita real ao exportador único.
        secoes_para_escrever = {}
        for sheet_name, df in sheets.items():
            if secoes_filtro and sheet_name not in secoes_filtro:
                continue

            if df.empty:
                secoes_para_escrever[sheet_name] = df
                continue

            # Só unifica se a sheet for Avarias/Uso Interno E tiver uma coluna
            # reconhecível de produto - senão mantém os dados como estão.
            sheet_lower = sheet_name.lower()
            coluna_produto = None
            if "avaria" in sheet_lower or "uso interno" in sheet_lower:
                for col in df.columns:
                    col_lower = col.lower()
                    if "produto" in col_lower or "item" in col_lower or "descrição" in col_lower or "descricao" in col_lower:
                        coluna_produto = col

            if coluna_produto and "avaria" in sheet_lower:
                df_final, _ = unificar_itens_avarias(df)
            elif coluna_produto and "uso interno" in sheet_lower:
                df_final, _ = unificar_itens_uso_interno(df)
            else:
                df_final = df

            colunas_secao = (colunas_filtro or {}).get(sheet_name)
            secoes_para_escrever[sheet_name] = filtrar_colunas(df_final, colunas_secao)

        escrever_xlsx(arquivo_unificado, secoes_para_escrever)

        return True, f"Relatório unificado gerado com sucesso", arquivo_unificado

    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro ao processar unificação: {erro_completo}")
        return False, f"Erro ao processar unificação: {str(e)}", None


def processar_unificacao_txt(secoes_filtro=None, colunas_filtro=None):
    """Processa todo o relatório aplicando unificação e gerando arquivo TXT.

    Args:
        secoes_filtro: Lista de seções para processar (None = todas)
        colunas_filtro: Dicionário {secao: [colunas]} para filtrar colunas (None = todas)

    Returns:
        tuple: (sucesso, mensagem, caminho_arquivo_gerado)
    """
    try:
        sheets = _sheets_da_ultima_execucao()
        if sheets is None:
            return False, "Nenhuma execução encontrada. Processe alguma análise primeiro.", None

        # Preparar arquivo de saída
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_unificado = os.path.join(
            BASE_PATH,
            "resultados",
            f"Relatorio_Unificado_{timestamp}.txt"
        )

        # Só seções unificáveis (Avarias/Uso Interno com coluna "Produto")
        # aparecem no TXT compacto - as demais (ex.: Erros de Análise) não
        # fazem sentido nesse formato de uma linha por item.
        secoes_para_escrever = {}
        for sheet_name, df in sheets.items():
            if secoes_filtro and sheet_name not in secoes_filtro:
                continue
            if df.empty:
                continue

            sheet_lower = sheet_name.lower()
            if "avaria" not in sheet_lower and "uso interno" not in sheet_lower:
                continue
            if "Produto" not in df.columns:
                continue

            if "avaria" in sheet_lower:
                df_unificado, _ = unificar_itens_avarias(df)
            else:
                df_unificado, _ = unificar_itens_uso_interno(df)

            colunas_secao = (colunas_filtro or {}).get(sheet_name)
            secoes_para_escrever[sheet_name] = filtrar_colunas(df_unificado, colunas_secao)

        escrever_txt_compacto(arquivo_unificado, "RELATÓRIO UNIFICADO DE AVARIAS E USO INTERNO", secoes_para_escrever)

        return True, f"Relatório unificado TXT gerado com sucesso", arquivo_unificado

    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro ao processar unificação TXT: {erro_completo}")
        return False, f"Erro ao processar unificação TXT: {str(e)}", None


@app.route("/api/unificar_relatorio", methods=["POST"])
def api_unificar_relatorio():
    """API para processar unificação do relatório."""
    try:
        # Obter formato do request (padrão: xlsx)
        data = request.get_json() or {}
        formato = data.get("formato", "xlsx").lower()
        secoes_json = data.get("secoes")
        colunas_json = data.get("colunas")

        # Validar formato
        if formato not in ["xlsx", "txt"]:
            return jsonify({
                "success": False,
                "message": "Formato inválido. Use 'xlsx' ou 'txt'."
            }), 400

        # Processar filtros se fornecidos
        secoes_filtro = None
        colunas_filtro = None

        if secoes_json:
            secoes_filtro = secoes_json
        if colunas_json:
            colunas_filtro = colunas_json

        # Processar conforme o formato
        if formato == "txt":
            sucesso, mensagem, arquivo_gerado = processar_unificacao_txt(secoes_filtro, colunas_filtro)
        else:
            sucesso, mensagem, arquivo_gerado = processar_unificacao_completa(secoes_filtro, colunas_filtro)

        if sucesso:
            # Retornar link para download
            filename = os.path.basename(arquivo_gerado)

            db_service.registrar_relatorio_unificado(
                arquivo_xlsx=filename if formato == "xlsx" else None,
                arquivo_txt=filename if formato == "txt" else None,
                secoes=secoes_filtro,
            )

            return jsonify({
                "success": True,
                "message": mensagem,
                "download_url": url_for("download_relatorio_unificado", filename=filename),
                "filename": filename,
                "formato": formato
            })
        else:
            return jsonify({
                "success": False,
                "message": mensagem
            }), 400

    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro na API de unificação: {erro_completo}")
        return jsonify({
            "success": False,
            "message": f"Erro interno: {str(e)}"
        }), 500


@app.route("/download_relatorio_unificado/<filename>")
def download_relatorio_unificado(filename):
    """Download do relatório unificado."""
    try:
        # Validar nome do arquivo (segurança)
        if not filename.startswith("Relatorio_Unificado_"):
            return jsonify({"error": "Arquivo inválido"}), 400

        caminho = os.path.join(BASE_PATH, "resultados", filename)

        if not os.path.exists(caminho):
            return jsonify({"error": "Arquivo não encontrado"}), 404

        return send_file(
            caminho,
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"❌ Erro no download do relatório unificado: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/opcoes_unificacao")
def api_opcoes_unificacao():
    """API para obter seções e colunas disponíveis para unificação."""
    try:
        sheets = _sheets_da_ultima_execucao()
        if sheets is None:
            return jsonify({"error": "Nenhuma execução encontrada"}), 404

        # Processar cada sheet para obter colunas após unificação
        secoes = []
        colunas_por_secao = {}

        for sheet_name, df in sheets.items():
            if df.empty:
                continue

            sheet_lower = sheet_name.lower()

            # Verificar se é uma seção unificável
            if "avaria" in sheet_lower or "uso interno" in sheet_lower:
                secoes.append(sheet_name)

                # Obter colunas após unificação
                if "Produto" in df.columns:
                    if "avaria" in sheet_lower:
                        df_unificado, _ = unificar_itens_avarias(df)
                    elif "uso interno" in sheet_lower:
                        df_unificado, _ = unificar_itens_uso_interno(df)
                    else:
                        df_unificado = df

                    colunas_por_secao[sheet_name] = df_unificado.columns.tolist()
                else:
                    colunas_por_secao[sheet_name] = df.columns.tolist()
            else:
                # Incluir outras seções também
                secoes.append(sheet_name)
                colunas_por_secao[sheet_name] = df.columns.tolist()

        return jsonify({
            "secoes": secoes,
            "colunas_por_secao": colunas_por_secao
        })
    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro ao obter opções de unificação: {erro_completo}")
        return jsonify({"error": str(e)}), 500
