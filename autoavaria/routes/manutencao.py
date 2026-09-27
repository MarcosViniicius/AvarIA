"""
Rotas de manutenção: `/limpar_dados`.

Existiam aqui também `/backup_relatorio` e `/download_backup/<filename>`,
mas nenhum botão da interface as chamava - o botão "Criar Backup" em
Configurações já usa `/download_relatorio` (routes/relatorio.py), que faz o
mesmo download direto do relatório atual. Removidas por serem código morto.
"""

import os
import shutil

from flask import jsonify, request

from .blueprint import web_bp as app
from .context import ARCHIVE_FOLDER, ARQUIVO_SAIDA_EXCEL, DIRETORIO_IMAGENS, LOG_CONSUMO_FILE, LOG_PROCESSADOS_FILE
from ..core.paths import RESULTADOS_DIR
from ..services import db as db_service
from ..services import maintenance


def _limpar_logs_no_banco():
    """Limpa os logs no SQLite (fonte primária desde a migração).

    Não basta remover os .txt: a leitura consulta o banco primeiro, então sem
    isto "Limpar Logs" não teria efeito visível.
    """
    try:
        db_service.limpar_arquivos_processados()
        db_service.limpar_consumo_log()
    except Exception as e:
        print(f"⚠️ Falha ao limpar os logs no banco: {e}")


@app.route("/limpar_dados", methods=["POST"])
def limpar_dados():
    """Limpa dados processados."""
    try:
        tipo = request.json.get("tipo", "")

        if tipo == "logs":
            if os.path.exists(LOG_PROCESSADOS_FILE):
                os.remove(LOG_PROCESSADOS_FILE)
            if os.path.exists(LOG_CONSUMO_FILE):
                os.remove(LOG_CONSUMO_FILE)
            _limpar_logs_no_banco()
            message = "Logs limpos com sucesso!"

        elif tipo == "relatorio":
            if os.path.exists(ARQUIVO_SAIDA_EXCEL):
                os.remove(ARQUIVO_SAIDA_EXCEL)
            message = "Relatório removido com sucesso!"

        elif tipo == "imagens":
            # Itens do Histórico guardam o caminho da imagem indefinidamente
            # (para o botão "Ver Imagem" continuar funcionando anos depois).
            # Apagar as imagens agora quebra esses links pra sempre — avisamos
            # quantos itens serão afetados na própria mensagem de resposta.
            # A maioria das imagens já processadas mora em ARCHIVE_FOLDER (ver
            # services/image_archive.py), não mais em DIRETORIO_IMAGENS — as
            # duas pastas precisam ser limpas para o aviso continuar verdadeiro.
            itens_afetados = db_service.contar_itens_com_imagem()

            for pasta in (DIRETORIO_IMAGENS, ARCHIVE_FOLDER):
                if os.path.exists(pasta):
                    for arquivo in os.listdir(pasta):
                        arquivo_path = os.path.join(pasta, arquivo)
                        if os.path.isfile(arquivo_path):
                            os.remove(arquivo_path)

            if itens_afetados:
                message = (
                    f"Imagens removidas. Atenção: {itens_afetados} itens no Histórico "
                    "referenciam essas imagens e o botão \"Ver Imagem\" deles vai parar de funcionar."
                )
            else:
                message = "Imagens removidas com sucesso!"

        elif tipo == "reprocessar_tudo":
            # Ação única e atômica para "resetar e processar tudo de novo":
            # limpa as imagens E o histórico de processamento juntos. Antes
            # disso, essas duas limpezas eram feitas separadamente ("logs" e
            # "imagens") e o usuário tinha que descobrir na tentativa e erro
            # que precisava das duas para conseguir reprocessar um lote.
            # Não mexe no relatório Excel nem no Histórico (aba Histórico) -
            # só reseta o que decide o que é "novo" para o pipeline.
            itens_afetados = db_service.contar_itens_com_imagem()

            if os.path.exists(DIRETORIO_IMAGENS):
                for arquivo in os.listdir(DIRETORIO_IMAGENS):
                    arquivo_path = os.path.join(DIRETORIO_IMAGENS, arquivo)
                    if os.path.isfile(arquivo_path):
                        os.remove(arquivo_path)

            if os.path.exists(LOG_PROCESSADOS_FILE):
                os.remove(LOG_PROCESSADOS_FILE)
            if os.path.exists(LOG_CONSUMO_FILE):
                os.remove(LOG_CONSUMO_FILE)
            _limpar_logs_no_banco()

            message = "Imagens e histórico de processamento removidos - pronto para enviar e processar do zero."
            if itens_afetados:
                message += (
                    f" Atenção: {itens_afetados} itens no Histórico referenciam essas imagens "
                    "e o botão \"Ver Imagem\" deles vai parar de funcionar."
                )

        elif tipo == "exportacoes":
            removidos = maintenance.limpar_exportacoes_antigas(RESULTADOS_DIR, manter=30)
            total = removidos["unificados"] + removidos["execucoes"]
            if total:
                message = (
                    f"{total} exportações antigas removidas "
                    f"({removidos['unificados']} unificados, {removidos['execucoes']} de execuções). "
                    "Foram mantidas as 30 mais recentes de cada tipo."
                )
            else:
                message = "Nenhuma exportação antiga para remover — você já está dentro do limite."

        else:
            return jsonify({"success": False, "message": "Tipo de limpeza inválido"})

        return jsonify({"success": True, "message": message})

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro: {str(e)}"})
