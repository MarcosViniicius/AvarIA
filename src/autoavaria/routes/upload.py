"""Rotas de upload de arquivos (`/upload`, `/upload_files`)."""

import os

from flask import jsonify, render_template, request
from werkzeug.utils import secure_filename

from .blueprint import web_bp as app
from .context import ARCHIVE_FOLDER, UPLOAD_FOLDER
from .processing import allowed_file
from ..services.config_service import verificar_e_corrigir_configuracao
from ..services.extraction import nome_para_gravar


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
        renomeados = []
        ignorados_duplicados = []
        for file in files:
            if file and allowed_file(file.filename):
                filename_original = secure_filename(file.filename)
                dados = file.read()
                filename = nome_para_gravar([upload_dir, ARCHIVE_FOLDER], filename_original, dados, forcar=forcar)

                if filename is None:
                    # Conteúdo idêntico a um arquivo já existente - reenviar o
                    # mesmo lote pra testar não deve duplicar a imagem nem a
                    # linha dela no relatório.
                    ignorados_duplicados.append(filename_original)
                    continue

                if filename != filename_original:
                    renomeados.append({"original": filename_original, "salvo_como": filename})

                filepath = os.path.join(upload_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(dados)
                uploaded_files.append(filename)

        mensagem = f"{len(uploaded_files)} arquivo(s) enviado(s) com sucesso!"
        if renomeados:
            mensagem += (
                f" {len(renomeados)} já existiam com esse nome (mas com conteúdo diferente) "
                "e foram salvos com um sufixo para não sobrescrever o arquivo anterior."
            )
        if ignorados_duplicados:
            mensagem += f" {len(ignorados_duplicados)} eram idênticos a arquivos já enviados e não foram duplicados."

        return jsonify(
            {
                "success": True,
                "message": mensagem,
                "files": uploaded_files,
                "renomeados": renomeados,
                "ignorados_duplicados": ignorados_duplicados,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro no upload: {str(e)}"})
