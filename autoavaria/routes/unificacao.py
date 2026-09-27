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
from ..services import invertexto
from ..services.export_service import (
    escrever_txt_compacto,
    escrever_xlsx,
    filtrar_colunas,
    renderizar_txt_compacto,
)
from ..services.relatorio_view import _construir_dados_relatorio
from ..services.unification import (
    renderizar_secciones_como_texto,
    unificar_itens_avarias,
    unificar_itens_uso_interno,
)


def _sem_colunas_internas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove colunas que existem só para a interface antes de unificar.

    `id_linha` (ver services/relatorio_view.py) não é dado do produto: além de
    não pertencer ao relatório de auditoria, ao consolidar um grupo ela fixava
    o id de um item qualquer do grupo como se fosse o do produto unificado.
    """
    internas = [c for c in ("id_linha",) if c in df.columns]
    return df.drop(columns=internas) if internas else df


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


def processar_unificacao_completa(secoes_filtro=None, colunas_filtro=None, return_contenido=False):
    """Processa todo el relatório aplicando unificação e generando planilha de auditoria.

    Args:
        secsões_filtro: Lista de seções para processar (None = todas)
        colunas_filtro: Dicionário {secao: [colunas]} para filtrar colunas (None = todas)
        return_contenido: se True, no retorno incluye un 4º elemento com el
            contenido textual de lo que se generó (para mostrar/copiar en pantalla).

    Returns:
        tuple: (sucesso, mensaje, camino_archivo_gerado) o
               (sucesso, mensaje, camino_archivo_gerado, contenido_texto)
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
                df_final, _ = unificar_itens_avarias(_sem_colunas_internas(df))
            elif coluna_produto and "uso interno" in sheet_lower:
                df_final, _ = unificar_itens_uso_interno(_sem_colunas_internas(df))
            else:
                df_final = df

            colunas_secao = (colunas_filtro or {}).get(sheet_name)
            secoes_para_escrever[sheet_name] = filtrar_colunas(df_final, colunas_secao)

        if not secoes_para_escrever or all(df.empty for df in secoes_para_escrever.values()):
            return False, "Nada para unificar: as seções selecionadas estão vazias.", None

        escrever_xlsx(arquivo_unificado, secoes_para_escrever)

        if return_contenido:
            return True, f"Relatório unificado gerado com sucesso", arquivo_unificado, renderizar_secciones_como_texto(secoes_para_escrever)
        return True, f"Relatório unificado gerado com sucesso", arquivo_unificado

    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro ao processar unificação: {erro_completo}")
        return False, f"Erro ao processar unificação: {str(e)}", None


def processar_unificacao_txt(secoes_filtro=None, colunas_filtro=None, return_contenido=False):
    """Processa todo o relatório aplicando unificação e gera arquivo TXT.

    Args:
        secosões_filtro: Lista de seções para processar (None = todas)
        colunas_filtro: Dicionário {secao: [colunas]} para filtrar colunas (None = todas)
        return_contenido: se True, devuelve un 4º elemento com el contenido
            textual de lo que se generó (para mostrar/copiar en pantalla).

    Returns:
        tuple: (sucesso, mensagem, camino_archivo_gerado) o
               (sucesso, mensagem, camino_archivo_gerado, contenido_texto)
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

        if not secoes_para_escrever:
            return False, (
                "Nada para unificar em TXT: selecione Avarias e/ou Uso Interno "
                "com coluna de produto. A seção de erros não entra no formato compacto."
            ), None

        titulo = "RELATÓRIO UNIFICADO DE AVARIAS E USO INTERNO"
        escrever_txt_compacto(arquivo_unificado, titulo, secoes_para_escrever)

        if return_contenido:
            return True, "Relatório unificado TXT gerado com sucesso", arquivo_unificado, renderizar_txt_compacto(titulo, secoes_para_escrever)
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
            resultado = processar_unificacao_txt(secoes_filtro, colunas_filtro, return_contenido=True)
        else:
            resultado = processar_unificacao_completa(secoes_filtro, colunas_filtro, return_contenido=True)

        # En caso de erro, estas funciones devuelven 3 elementos (sin contenido).
        if len(resultado) == 4:
            sucesso, mensagem, arquivo_gerado, contenido = resultado
        else:
            sucesso, mensagem, arquivo_gerado = resultado
            contenido = ""

        if sucesso:
            # Retornar link para download
            filename = os.path.basename(arquivo_gerado)

            db_service.registrar_unificado_gerado(
                nome_arquivo=filename,
                formato=formato,
                secoes=secoes_filtro,
            )

            return jsonify({
                "success": True,
                "message": mensagem,
                "download_url": url_for("download_relatorio_unificado", filename=filename),
                "filename": filename,
                "formato": formato,
                "contenido": contenido or "",
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


@app.route("/api/enviar_invertexto", methods=["POST"])
def api_enviar_invertexto():
    """Envia a unificação do relatório mestre para o notepad do invertexto.

    Espelha a rota do Histórico: o conteúdo é REGERADO no servidor (não vem do
    cliente) e sanitizado antes de sair — a coluna "Caminho da Imagem" carrega
    o caminho do disco de quem processou e não faz sentido compartilhar.

    Corpo opcional: {"secoes": [...], "colunas": {...}} (os mesmos filtros da
    unificação da tela).
    """
    if not invertexto.configurado():
        return jsonify({
            "success": False,
            "message": "Integração com o invertexto não configurada.",
        }), 400

    data = request.get_json(silent=True) or {}
    secoes_filtro = data.get("secoes")
    colunas_filtro = data.get("colunas")

    resultado = processar_unificacao_txt(secoes_filtro, colunas_filtro, return_contenido=True)
    if len(resultado) == 4:
        sucesso, mensagem, _arquivo, contenido = resultado
    else:
        sucesso, mensagem, _arquivo = resultado
        contenido = ""

    if not sucesso:
        return jsonify({"success": False, "message": mensagem}), 400

    texto = invertexto.sanitizar(contenido or "")
    enviado, mensagem_envio = invertexto.enviar(texto)

    return jsonify({
        "success": enviado,
        "message": mensagem_envio,
        "url": invertexto.obter_config_publica()["url"],
        "caracteres": len(texto),
    }), (200 if enviado else 400)


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
