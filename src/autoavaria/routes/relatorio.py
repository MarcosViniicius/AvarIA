"""
Rotas de visualização e download do relatório: `/relatorio`,
`/visualizar_relatorio`, `/download_relatorio`, `/download_relatorio_txt`,
`/api/opcoes_exportacao`, `/imagem/<path:filename>`.
"""

import os
from datetime import datetime

import pandas as pd
from flask import (
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .blueprint import web_bp as app
from .context import ARCHIVE_FOLDER, ARQUIVO_SAIDA_EXCEL, BASE_PATH, DIRETORIO_IMAGENS, EXTENSOES_IMAGEM
from ..services import db as db_service
from ..services import invertexto
from ..services.export_service import escrever_txt_detalhado, escrever_xlsx
from ..services.relatorio_view import _construir_dados_relatorio
from ..services.report_editing import carregar_todas_sheets


def _resolver_imagem(nome_original: str):
    """Caminho físico de uma imagem a partir do nome original (ou None).

    O acervo (services/arquivos.py) é a fonte primária: o nome físico pode ser
    opaco, e há fallback para o nome-base (referências antigas a `IMG-x_2.jpg`,
    cujo conteúdo idêntico foi consolidado em `IMG-x.jpg`). Sem registro, cai
    para as pastas oficiais — mantém funcionando acervo ainda não migrado.
    """
    try:
        from ..services import arquivos as acervo

        for registro in acervo.buscar_por_nome_com_fallback(nome_original):
            caminho = acervo.caminho_de(registro)
            if os.path.isfile(caminho):
                return caminho
    except Exception as e:
        print(f"⚠️ Acervo indisponível para '{nome_original}': {e}")

    for pasta in (DIRETORIO_IMAGENS, ARCHIVE_FOLDER):
        candidato = os.path.join(str(pasta), nome_original)
        if os.path.exists(candidato):
            return candidato
    return None


@app.route("/relatorio")
@app.route("/visualizar_relatorio")
def visualizar_relatorio():
    """Página de visualização do relatório - mostra só a última execução
    registrada no banco (services/db.py), não o histórico acumulado inteiro.

    Os botões de exportação (Excel/TXT/Unificar) continuam operando sobre o
    Excel mestre completo - ver templates/relatorio.html - de propósito,
    para quem quiser baixar o histórico todo continuar podendo.
    """
    execucoes = db_service.listar_execucoes(limite=1)
    if not execucoes:
        # Nenhuma execução registrada no banco ainda (banco novo, ou um Excel
        # de antes do banco existir) - cai para a visão antiga (Excel completo).
        return _visualizar_relatorio_excel_completo()

    execucao = db_service.obter_execucao(execucoes[0]["id"])
    dados = _construir_dados_relatorio(execucao["itens"]) if execucao else {}

    return render_template(
        "relatorio.html",
        dados=dados,
        execucao=execucao,
        dados_invertexto=invertexto.obter_config_publica(),
    )


def _visualizar_relatorio_excel_completo():
    """Fallback: mostra o Excel mestre completo. Usado só quando ainda não
    existe nenhuma execução registrada no banco (ver visualizar_relatorio)."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            flash(
                "Nenhum relatório encontrado. Execute o processamento primeiro.",
                "warning",
            )
            return redirect(url_for("index"))

        # Verificar se o arquivo não está vazio
        if os.path.getsize(ARQUIVO_SAIDA_EXCEL) == 0:
            flash(
                "Arquivo de relatório está vazio. Execute o processamento novamente.",
                "warning",
            )
            return redirect(url_for("index"))

        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)
        dados = {}

        if not sheets:
            flash("Relatório não contém dados válidos.", "warning")
            return redirect(url_for("index"))

        for sheet_name, df in sheets.items():
            if df is not None and not df.empty:
                # Tratar valores NaN
                df = df.fillna("-")
                dados[sheet_name] = {
                    "colunas": df.columns.tolist(),
                    "dados": df.to_dict("records"),
                    "total": len(df),
                }

        if not dados:
            flash("Nenhum dado válido encontrado no relatório.", "warning")
            return redirect(url_for("index"))

        return render_template(
            "relatorio.html",
            dados=dados,
            execucao=None,
            dados_invertexto=invertexto.obter_config_publica(),
        )

    except FileNotFoundError:
        flash("Arquivo de relatório não encontrado.", "danger")
        return redirect(url_for("index"))
    except PermissionError:
        flash("Sem permissão para acessar o arquivo de relatório.", "danger")
        return redirect(url_for("index"))
    except pd.errors.EmptyDataError:
        flash("Arquivo de relatório está vazio ou corrompido.", "danger")
        return redirect(url_for("index"))
    except Exception as e:
        print(f"Erro detalhado ao carregar relatório: {e}")
        flash(f"Erro ao carregar relatório: {str(e)}", "danger")
        return redirect(url_for("index"))


@app.route("/download_relatorio")
def download_relatorio():
    """Download do relatório em Excel."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            flash("Relatório não encontrado", "warning")
            return redirect(url_for("index"))

        # Obter filtros de seções e colunas
        secoes_json = request.args.get('secoes')
        colunas_json = request.args.get('colunas')

        if secoes_json and colunas_json:
            # Aplicar filtros
            import json as json_lib
            secoes_selecionadas = json_lib.loads(secoes_json)
            colunas_por_secao = json_lib.loads(colunas_json)

            # Ler Excel original
            sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

            # Criar arquivo filtrado
            xlsx_filename = f'Relatorio_Avarias_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
            xlsx_path = os.path.join(BASE_PATH, "resultados", f"temp_{xlsx_filename}")

            secoes_para_escrever = {}
            for secao in secoes_selecionadas:
                if secao not in sheets:
                    continue
                colunas = colunas_por_secao.get(secao, [])
                if not colunas:
                    continue  # sem filtro de coluna definido, a seção não entra (comportamento original)
                colunas_existentes = [col for col in colunas if col in sheets[secao].columns]
                if colunas_existentes:
                    secoes_para_escrever[secao] = sheets[secao][colunas_existentes]

            escrever_xlsx(xlsx_path, secoes_para_escrever)

            # Enviar arquivo filtrado
            response = send_file(
                xlsx_path,
                as_attachment=True,
                download_name=xlsx_filename,
            )

            # Remover arquivo temporário
            @response.call_on_close
            def remove_file():
                try:
                    if os.path.exists(xlsx_path):
                        os.remove(xlsx_path)
                except:
                    pass

            return response
        else:
            # Download completo (comportamento original)
            return send_file(
                ARQUIVO_SAIDA_EXCEL,
                as_attachment=True,
                download_name=f'Relatorio_Avarias_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx',
            )
    except Exception as e:
        flash(f"Erro no download: {str(e)}", "danger")
        return redirect(url_for("index"))


@app.route("/api/opcoes_exportacao")
def api_opcoes_exportacao():
    """API para obter seções e colunas disponíveis para exportação."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({"error": "Relatório não encontrado"}), 404

        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        secoes = list(sheets.keys())
        colunas_por_secao = {}

        for sheet_name, df in sheets.items():
            if df is not None and not df.empty:
                colunas_por_secao[sheet_name] = df.columns.tolist()

        return jsonify({
            "secoes": secoes,
            "colunas_por_secao": colunas_por_secao
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download_relatorio_txt")
def download_relatorio_txt():
    """Download do relatório em formato TXT."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            flash("Relatório não encontrado", "warning")
            return redirect(url_for("index"))

        # Obter filtros de seções e colunas
        secoes_json = request.args.get('secoes')
        colunas_json = request.args.get('colunas')

        # Ler todas as sheets do Excel
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

        # Aplicar filtros se fornecidos
        secoes_para_exportar = sheets.keys()
        colunas_por_secao_filtradas = {}

        if secoes_json and colunas_json:
            import json as json_lib
            secoes_selecionadas = json_lib.loads(secoes_json)
            colunas_por_secao = json_lib.loads(colunas_json)
            secoes_para_exportar = secoes_selecionadas
            colunas_por_secao_filtradas = colunas_por_secao

        # Criar arquivo temporário para o TXT
        txt_filename = f'Relatorio_Avarias_{datetime.now().strftime("%Y%m%d_%H%M")}.txt'
        txt_path = os.path.join(BASE_PATH, "resultados", txt_filename)

        # Ordem de exibição: Avarias, depois Uso Interno, depois o resto.
        sheet_order = []
        for sheet_name in secoes_para_exportar:
            if sheet_name not in sheets:
                continue
            if "Avarias" in sheet_name:
                sheet_order.insert(0, sheet_name)
            elif "Uso Interno" in sheet_name:
                if sheet_order and "Avarias" in sheet_order[0]:
                    sheet_order.insert(1, sheet_name)
                else:
                    sheet_order.insert(0, sheet_name)
            else:
                sheet_order.append(sheet_name)

        secoes_para_escrever = {}
        for sheet_name in sheet_order:
            df = sheets[sheet_name]
            if df is None or df.empty:
                continue

            if colunas_por_secao_filtradas and sheet_name in colunas_por_secao_filtradas:
                colunas = colunas_por_secao_filtradas[sheet_name]
                colunas_existentes = [col for col in colunas if col in df.columns]
                if colunas_existentes:
                    df = df[colunas_existentes]
                else:
                    continue  # Pular se nenhuma coluna válida

            secoes_para_escrever[sheet_name] = df

        escrever_txt_detalhado(txt_path, "RELATÓRIO COMPLETO DE ANÁLISE DE PRODUTOS", secoes_para_escrever)

        # Enviar arquivo
        response = send_file(
            txt_path,
            as_attachment=True,
            download_name=txt_filename,
            mimetype="text/plain"
        )

        # Agendar remoção do arquivo temporário após envio
        @response.call_on_close
        def remove_file():
            try:
                if os.path.exists(txt_path):
                    os.remove(txt_path)
            except:
                pass

        return response

    except Exception as e:
        flash(f"Erro ao gerar arquivo TXT: {str(e)}", "danger")
        return redirect(url_for("visualizar_relatorio"))


@app.route("/imagem/<path:filename>")
def servir_imagem(filename):
    """Serve imagens do diretório de imagens com cache otimizado.

    `filename` é o NOME ORIGINAL (identidade de negócio). O arquivo físico pode
    ser opaco quando veio do acervo (services/arquivos.py), então a resolução
    passa pelo acervo primeiro e cai para o disco (legado) depois.
    """
    try:
        # Resolução única: acervo por nome original (com fallback para o
        # nome-base, cobrindo referências antigas a `IMG-x_2.jpg`), e depois
        # as pastas oficiais — pode estar em pendentes (com erro/nova) ou em
        # arquivadas (processada com sucesso).
        caminho_completo = _resolver_imagem(filename)

        if not caminho_completo:
            return jsonify({"error": "Imagem não encontrada"}), 404

        # Verificar se é realmente uma imagem
        _, ext = os.path.splitext(filename.lower())
        if ext not in EXTENSOES_IMAGEM:
            return jsonify({"error": "Arquivo não é uma imagem válida"}), 400

        # Configurar headers de cache para imagens
        def add_cache_headers(response):
            # Cache por 1 hora para imagens estáticas
            response.headers["Cache-Control"] = "public, max-age=3600"
            response.headers["ETag"] = (
                f'"{hash(filename + str(os.path.getmtime(caminho_completo)))}"'
            )
            return response

        # Verificar ETag para cache condicional
        if_none_match = request.headers.get("If-None-Match")
        current_etag = f'"{hash(filename + str(os.path.getmtime(caminho_completo)))}"'

        if if_none_match == current_etag:
            response = make_response("", 304)  # Not Modified
            response.headers["ETag"] = current_etag
            return response

        response = make_response(send_file(caminho_completo))
        return add_cache_headers(response)

    except Exception as e:
        print(f"❌ Erro ao servir imagem {filename}: {e}")
        return jsonify({"error": "Erro interno do servidor"}), 500
