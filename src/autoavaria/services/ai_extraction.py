"""
EXTRAÇÃO DE DADOS COM IA

Responsável por: mapear o contexto de texto (conversa do WhatsApp) para cada
imagem, montar o prompt e enviar lotes de imagens+texto para o provedor de
IA configurado (Gemini/OpenAI/Claude/OpenRouter, via services/ai.py), e
transformar a resposta em linhas do relatório (Avaria / Uso Interno / Erro).
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Tuple

from PIL import Image

from .ai import AIProvider

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
DEBUG_MODE = False

PROMPT_INSTRUCAO = """
Sua tarefa é analisar os itens a seguir e catalogar produtos como "Avaria" ou "Uso Interno".
Cada item tem uma imagem e, opcionalmente, um texto de contexto de uma conversa.

[REGRA DE OURO]: O "Contexto da Mensagem" é a fonte de informação MAIS IMPORTANTE. A imagem serve apenas como apoio visual. Trate o texto como a fonte da verdade.

[COMO ANALISAR]:
1.  **Cenário 1 (Texto é o principal):** Se o "Contexto da Mensagem" descreve produtos (ex: "2 alface", "coentro", "saco de lixo"), EXTRAIA OS ITENS DIRETAMENTE DO TEXTO.
    - Se o texto menciona perdas, quebras, ou produtos estragados, classifique o `tipo` como "Avaria".
    - Se o texto menciona consumo da equipe ou da loja, classifique como "Uso Interno".
    - Se a imagem não mostra uma etiqueta clara para estes itens, os campos `peso`, `marca` e `codigo_barras` devem ser "N/A".
    - Se o texto contiver múltiplos itens (ex: "4 COENTRO\\n2 ALFACE"), crie um item para cada um na lista de `itens`.

2.  **Cenário 2 (Imagem é o principal):** Se o texto estiver vazio ou não descritivo, e a imagem mostrar uma etiqueta de produto legível, extraia as informações da etiqueta na imagem.
    - `tipo` "Avaria": Extraia NOME e PESO.
    - `tipo` "Uso Interno": Extraia NOME, MARCA e CÓDIGO DE BARRAS. Priorize a extração do CÓDIGO DE BARRAS.

3.  **Cenário 3 (Erro):** Se for impossível determinar o produto ou a categoria, use o `tipo` "Erro".

[FORMATO DA RESPOSTA]: A resposta DEVE ser um único objeto JSON.

[EXEMPLO PRÁTICO]:
Se a entrada for:
* Arquivo: "IMG-1234.jpg"
* Contexto da Mensagem: "perda de hoje:\\n4 coentro\\n2 alface"
* Imagem: (Uma foto genérica de caixas de hortaliças)

A sua saída JSON DEVE ser:
{
  "IMG-1234.jpg": {
    "tipo": "Avaria",
    "itens": [
      {"produto": "COENTRO", "peso": "N/A", "marca": "N/A", "codigo_barras": "N/A"},
      {"produto": "ALFACE", "peso": "N/A", "marca": "N/A", "codigo_barras": "N/A"}
    ]
  }
}

Agora, analise os seguintes arquivos:
"""


# ================================
# PROCESSAMENTO DE IMAGENS E TEXTO (IA)
# ================================


def _extrair_json_da_resposta(resposta_texto: str) -> Dict[str, Any]:
    """Extrai o objeto JSON da resposta do modelo, tolerando cercas ```json fantasma.

    Mesmo pedindo modo JSON nativo (Gemini/OpenAI), mantemos esse fallback:
    nem todo provedor/modelo respeita o modo JSON à risca, e alguns ainda
    envolvem a resposta em ```json ... ``` por hábito de prompt.
    """
    texto = resposta_texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"```\s*$", "", texto)
        texto = texto.strip()
    return json.loads(texto)


def extrair_dados_de_lote(
    lote_de_caminhos: List[str], provider: AIProvider, mensagens_por_imagem: Dict[str, str]
) -> Tuple[Dict[str, Any], int]:
    """Envia um lote de imagens e seu contexto de texto para o provedor de IA configurado."""
    if not lote_de_caminhos:
        return {}, 0

    partes = [{"tipo": "texto", "texto": PROMPT_INSTRUCAO}]
    nomes_validos = []
    resultados: Dict[str, Any] = {}

    for caminho in lote_de_caminhos:
        nome_arquivo = os.path.basename(caminho)
        try:
            # Só valida que o arquivo abre como imagem — a codificação real
            # (PIL/base64/etc.) é feita dentro de cada provedor.
            with Image.open(caminho) as img:
                img.verify()
        except Exception as e:
            # Uma imagem corrompida não pode derrubar o lote inteiro: só ELA
            # vira erro, as outras imagens do lote continuam sendo analisadas.
            print(f"⚠️ Não foi possível abrir {nome_arquivo}: {e}")
            resultados[nome_arquivo] = {"tipo": "Erro", "detalhes": f"Falha ao abrir arquivo: {e}"}
            continue

        contexto_mensagem = mensagens_por_imagem.get(nome_arquivo, "")
        prompt_arquivo = f"Arquivo: {nome_arquivo}"
        if contexto_mensagem:
            prompt_arquivo += f"\n[Contexto da Mensagem]:\n{contexto_mensagem}"
        partes.append({"tipo": "texto", "texto": prompt_arquivo})
        partes.append({"tipo": "imagem", "caminho": caminho})
        nomes_validos.append(nome_arquivo)

    if not nomes_validos:
        # Todas as imagens do lote falharam ao abrir — nada pra mandar pra IA.
        return resultados, 0

    resposta_texto = ""
    for tentativa in range(MAX_RETRIES):
        try:
            resposta_texto, tokens_consumidos = provider.gerar_conteudo(partes)
            dados = _extrair_json_da_resposta(resposta_texto)

            print(f"🪙 Tokens consumidos nesta requisição: {tokens_consumidos}")
            resultados.update(dados)
            return resultados, tokens_consumidos

        except json.JSONDecodeError as e:
            print(f"❌ Erro de JSON na tentativa {tentativa + 1}: {e}")
            if DEBUG_MODE:
                print(f"[DEBUG] Resposta problemática: {resposta_texto[:200]}...")

        except Exception as e:
            print(f"❌ Erro na API na tentativa {tentativa + 1}: {e}")

        if tentativa < MAX_RETRIES - 1:
            print(f"⏳ Aguardando {RETRY_DELAY_SECONDS}s...")
            time.sleep(RETRY_DELAY_SECONDS)

    print(f"❌ Falha em todas as {MAX_RETRIES} tentativas para o lote.")
    resultados.update({nome: {"tipo": "Erro", "detalhes": "Falha na API"} for nome in nomes_validos})
    return resultados, 0


# ================================
# CLASSIFICAÇÃO DO RESULTADO DA IA EM LINHAS DE RELATÓRIO
# ================================


def processar_resultado_arquivo(
    nome_arquivo: str,
    resultados_lote: Dict[str, Any],
    mensagens_por_imagem: Dict[str, str],
    diretorio_imagens: str,
    novas_avarias: List[Dict],
    novos_usos_internos: List[Dict],
    novos_erros: List[Dict],
) -> None:
    """Processa o resultado de análise de um arquivo específico."""
    try:
        dados = resultados_lote.get(nome_arquivo)
        if not dados:
            dados = {"tipo": "Erro", "detalhes": "Arquivo não retornado na resposta do lote."}

        caminho_absoluto = os.path.abspath(os.path.join(diretorio_imagens, nome_arquivo))
        msg_associada = mensagens_por_imagem.get(nome_arquivo, "")
        tipo = dados.get("tipo")
        itens = dados.get("itens", [])

        if not isinstance(itens, list):
            itens = [dados] if dados else []

        if tipo == "Avaria":
            _processar_avaria(itens, msg_associada, caminho_absoluto, novas_avarias)
        elif tipo == "Uso Interno":
            _processar_uso_interno(itens, msg_associada, caminho_absoluto, novos_usos_internos)
        else:
            _processar_erro(dados, nome_arquivo, msg_associada, caminho_absoluto, novos_erros)
    except Exception as e:
        caminho_absoluto = os.path.abspath(os.path.join(diretorio_imagens, nome_arquivo))
        novos_erros.append(
            {
                "Arquivo": nome_arquivo,
                "Detalhes do Erro": f"Erro de processamento interno: {e}",
                "Observação da Mensagem": mensagens_por_imagem.get(nome_arquivo, "Nenhuma"),
                "Caminho da Imagem": caminho_absoluto,
                "Ver Imagem": caminho_absoluto,
            }
        )


def _quantidade_do_item(item: Dict[str, Any]) -> int:
    """Quantidade de unidades do item, com 1 como padrão.

    Vem do texto da conversa (ex.: legenda "7" numa foto de linguiça), que é
    a única fonte dessa informação — a imagem não a contém. Ver
    services/conversa.py.
    """
    try:
        quantidade = int(item.get("quantidade") or 1)
    except (TypeError, ValueError):
        return 1
    return quantidade if quantidade > 0 else 1


def _processar_avaria(itens, msg_associada, caminho_absoluto, novas_avarias):
    """Processa e formata itens de avaria para o relatório."""
    for item in itens:
        novas_avarias.append(
            {
                "Produto": item.get("produto", "N/A"),
                "Quantidade": _quantidade_do_item(item),
                "Peso": item.get("peso") or "N/A",
                "Observação da Mensagem": msg_associada.replace("\n", " | ") if msg_associada else "Nenhuma",
                "Caminho da Imagem": caminho_absoluto,
                "Ver Imagem": caminho_absoluto,
            }
        )


def _processar_uso_interno(itens, msg_associada, caminho_absoluto, novos_usos_internos):
    """Processa e formata itens de uso interno para o relatório."""
    for item in itens:
        novos_usos_internos.append(
            {
                "Produto": item.get("produto", "N/A"),
                "Quantidade": _quantidade_do_item(item),
                "Marca": item.get("marca") or "N/A",
                "Código de Barras": item.get("codigo_barras") or "N/A",
                "Observação da Mensagem": msg_associada.replace("\n", " | ") if msg_associada else "Nenhuma",
                "Caminho da Imagem": caminho_absoluto,
                "Ver Imagem": caminho_absoluto,
            }
        )


def _processar_erro(dados, nome_arquivo, msg_associada, caminho_absoluto, novos_erros):
    """Processa e formata erros de análise para o relatório."""
    novos_erros.append(
        {
            "Arquivo": nome_arquivo,
            "Detalhes do Erro": dados.get("detalhes", "Erro não especificado."),
            "Observação da Mensagem": msg_associada.replace("\n", " | ") if msg_associada else "Nenhuma",
            "Caminho da Imagem": caminho_absoluto,
            "Ver Imagem": caminho_absoluto,
        }
    )
