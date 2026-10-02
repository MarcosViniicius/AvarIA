"""Rotas de upload de arquivos (`/upload`, `/upload_files`)."""

import os

from flask import jsonify, render_template, request
from werkzeug.utils import secure_filename

from .blueprint import web_bp as app
from .context import ARCHIVE_FOLDER, UPLOAD_FOLDER
from .processing import allowed_file
from ..services import arquivos
from ..services.config_service import verificar_e_corrigir_configuracao

MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024


def _nome_original_seguro(nome: str) -> str:
    """Sanitiza o nome do arquivo PRESERVANDO a extensão.

    `secure_filename("测试.zip")` devolve "zip": o não-ASCII é removido e o
    ponto vira separador de sufixo, então o arquivo perderia a extensão e nunca
    seria reconhecido como ZIP/imagem. Aqui o radical é sanitizado e a extensão
    original é reanexada.
    """
    base, extensao = os.path.splitext(str(nome or ""))
    radicao = secure_filename(base) or "arquivo"
    return f"{radicao}{extensao.lower()}"


@app.route("/upload")
def upload_page():
    """Página de upload."""
    config_ok, config_msg = verificar_e_corrigir_configuracao()
    return render_template("upload.html", chave_api_ausente=not config_ok, mensagem_config=config_msg)


@app.route("/upload_files", methods=["POST"])
def upload_files():
    """Endpoint para upload de arquivos."""
    try:
        if "files" not in request.files:
            return jsonify({"success": False, "message": "Nenhum arquivo selecionado"})

        files = request.files.getlist("files")
        if not files or files[0].filename == "":
            return jsonify({"success": False, "message": "Nenhum arquivo selecionado"})

        # No ambiente Vercel, uploads vão para /tmp
        upload_dir = UPLOAD_FOLDER
        os.makedirs(upload_dir, exist_ok=True)

        forcar = request.form.get("forcar_reprocessamento") == "true"

        uploaded_files = []
        registrados = []
        ignorados_duplicados = []
        for file in files:
            if file and allowed_file(file.filename):
                filename_original = _nome_original_seguro(file.filename)
                dados = file.read()

                # Acervo: nome físico aleatório (nunca colide) + metadados no
                # banco. O hash do CONTEÚDO ORIGINAL é a chave de dedup -
                # reenviar o mesmo lote não duplica nem reprocessa, mesmo que a
                # cópia em disco tenha sido recomprimida ao ser arquivada.
                # `forcar` registra mesmo o conteúdo idêntico (o usuário pediu),
                # criando um físico novo para não confundir a fila.
                registro = arquivos.registrar(
                    filename_original, dados=dados, forcar=forcar,
                )

                if registro is None:
                    ignorados_duplicados.append(filename_original)
                    continue

                uploaded_files.append(filename_original)
                registrados.append({
                    "nome_original": filename_original,
                    "nome_fisico": registro["nome_fisico"],
                })

        mensagem = f"{len(uploaded_files)} arquivo(s) enviado(s) com sucesso!"
        if ignorados_duplicados:
            mensagem += f" {len(ignorados_duplicados)} já haviam sido enviados (conteúdo idêntico) e não foram duplicados."

        return jsonify(
            {
                "success": True,
                "message": mensagem,
                "files": uploaded_files,
                "registrados": registrados,
                "ignorados_duplicados": ignorados_duplicados,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro no upload: {str(e)}"})
