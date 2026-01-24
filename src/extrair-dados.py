"""
ANALISADOR MESTRE DE IMAGENS E MENSAGENS
Versão Corrigida com Foco em Texto: 16/07/2025
VERSÃO MELHORADA - Código refatorado para priorizar a análise de texto sobre a imagem.

Este sistema analisa imagens de etiquetas de produtos e mensagens de texto correspondentes
usando Google Gemini AI, extraindo dados de avarias e uso interno, e gerando
relatórios completos em Excel.
"""

import os
import sys
import json
import time
import re
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, Any

# Imports de terceiros
from PIL import Image
import google.generativeai as genai
import pandas as pd
from openpyxl.styles import Font
from tqdm import tqdm

# ================================
# CONFIGURAÇÕES DO SISTEMA
# ================================

# Configurações da API - carregadas do config.json
CONFIG_FILE = os.path.join("config", "config.json")


def carregar_configuracao():
    """Carrega configurações do arquivo JSON."""
    config_padrao = {
        "api": {
            "provider": "gemini",
            "gemini_api_key": "",
            "openai_api_key": "",
            "anthropic_api_key": "",
        },
        "processamento": {
            "modelo_gemini": "gemini-1.5-flash",
            "temperatura": 0.1,
            "max_tokens": 1000,
            "timeout": 30,
        },
    }

    try:
        # Usar sempre o caminho absoluto para config/config.json
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.json")
        
        if os.path.exists(config_path):
            print(f"📄 Arquivo de configuração encontrado: {config_path}")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                
                # Verificar se a API key foi definida
                api_key = config.get("api", {}).get("gemini_api_key", "")
                if api_key and api_key.strip() and api_key != "SUA_CHAVE_AI_AQUI":
                    print("✅ API Key do Gemini encontrada na configuração")
                else:
                    print("⚠️ API Key do Gemini não encontrada ou inválida")
                
                return config
        else:
            print("⚠️ Nenhum arquivo de configuração encontrado, usando configuração padrão")
            return config_padrao
    except Exception as e:
        print(f"⚠️ Erro ao carregar configuração: {e}")
        return config_padrao


# Carregar configurações
CONFIG = carregar_configuracao()
GEMINI_API_KEY = CONFIG.get("api", {}).get("gemini_api_key", "")
GEMINI_MODEL = CONFIG.get("processamento", {}).get("modelo_gemini", "gemini-2.0-flash")

# Configurações de arquivos e diretórios
DIRETORIO_IMAGENS = "imagens_para_analisar"
ARQUIVO_SAIDA_EXCEL = "resultados/Relatorio_Mestre_Produtos.xlsx"
LOG_PROCESSADOS_FILE = "logs/log_mestre.txt"
LOG_CONSUMO_FILE = "logs/log_consumo_tokens.txt"

# Configurações de processamento otimizadas para reduzir RPM/RPD (carregadas do config.json)
TAMANHO_LOTE = CONFIG.get("processamento", {}).get("tamanho_lote", 5)
MAX_WORKERS = CONFIG.get("processamento", {}).get("max_workers", 2)
REQUEST_DELAY = CONFIG.get("processamento", {}).get("request_delay", 1.5)
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
DEBUG_MODE = False

# Extensões de imagem suportadas
EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")

# Verifica se existem as pastas necessárias, se não tiver, cria.
for pasta in ["resultados", "logs"]:
    if not os.path.exists(pasta):
        os.makedirs(pasta)
        print(f"Pasta '{pasta}' criada com sucesso.")
    else:
        print(f"Pasta '{pasta}' já existe.")


# ================================
# CLASSES DE CONFIGURAÇÃO
# ================================


class ProcessingConfig:
    """Configurações centralizadas do processamento."""

    def __init__(self):
        self.validate_settings()

    def validate_settings(self) -> None:
        """Valida as configurações do sistema."""
        if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == "" or "SUA_CHAVE_AI_AQUI" in GEMINI_API_KEY:
            print("❌ Problemas encontrados na configuração da API:")
            print(f"   - API Key: {'Vazia' if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == '' else 'Inválida'}")
            print(f"   - Arquivo de config usado: {CONFIG_FILE}")
            print("💡 Soluções:")
            print("   1. Verifique se o arquivo config/config.json existe")
            print("   2. Configure sua API Key do Gemini na interface web (aba Configurações)")
            print("   3. Certifique-se de que a chave não está vazia")
            raise ValueError(
                "Chave da API Gemini não configurada. Configure na interface web."
            )

        if TAMANHO_LOTE <= 0:
            raise ValueError("Tamanho do lote deve ser maior que zero.")

        if MAX_WORKERS <= 0:
            raise ValueError("Número de workers deve ser maior que zero.")


# ================================
# UTILITÁRIOS E LOGS
# ================================


def verificar_cancelamento() -> bool:
    """Verifica se o processamento foi cancelado."""
    cancel_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cancel_processing")
    if os.path.exists(cancel_file):
        try:
            os.remove(cancel_file)
        except:
            pass
        return True
    return False


def carregar_logs() -> Set[str]:
    """Carrega os logs de arquivos já processados."""
    if not os.path.exists(LOG_PROCESSADOS_FILE):
        return set()
    try:
        with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except IOError as e:
        print(f"⚠️ Erro ao ler log de arquivos processados: {e}")
        return set()


def registrar_log(nome_arquivo: str) -> None:
    """Registra um arquivo como processado no log."""
    try:
        # Garantir que o diretório existe
        os.makedirs(os.path.dirname(LOG_PROCESSADOS_FILE), exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - Processado: {nome_arquivo}\n"
        
        with open(LOG_PROCESSADOS_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except IOError as e:
        print(f"⚠️ Erro ao salvar log de arquivos: {e}")
    except Exception as e:
        print(f"❌ Erro inesperado ao salvar log de arquivos: {e}")


def registrar_consumo_log(total_tokens: int, detalhes_extras: str = "") -> None:
    """Salva o consumo total de tokens com data e hora em um arquivo de log."""
    try:
        # Garantir que o diretório existe
        os.makedirs(os.path.dirname(LOG_CONSUMO_FILE), exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - Tokens consumidos: {total_tokens:,}"
        
        if detalhes_extras:
            log_entry += f" - {detalhes_extras}"
        
        log_entry += "\n"
        
        with open(LOG_CONSUMO_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
            
        print(f"📝 Log de consumo salvo: {total_tokens:,} tokens")
    except IOError as e:
        print(f"⚠️ Erro ao salvar log de consumo: {e}")
    except Exception as e:
        print(f"❌ Erro inesperado ao salvar log: {e}")


def verificar_dependencias() -> None:
    """Verifica e instala dependências necessárias."""
    try:
        import tqdm
    except ImportError:
        print("📦 Instalando biblioteca 'tqdm' para barra de progresso...")
        try:
            import subprocess

            subprocess.check_call([sys.executable, "-m", "pip", "install", "tqdm"])
            print("✅ Biblioteca 'tqdm' instalada com sucesso.")
        except Exception as e:
            print(f"❌ Erro ao instalar 'tqdm': {e}")
            sys.exit(1)


# ================================
# PROCESSAMENTO DE MENSAGENS (Contexto de Texto)
# ================================


def mapear_mensagens_para_imagens() -> Dict[str, str]:
    """Mapeia mensagens de texto de um arquivo .txt para os nomes de arquivos de imagem."""
    try:
        caminho_txt = next(
            (
                os.path.join(DIRETORIO_IMAGENS, f)
                for f in os.listdir(DIRETORIO_IMAGENS)
                if f.lower().endswith(".txt")
            ),
            None,
        )
        if not caminho_txt:
            print(
                "ℹ️ Nenhum arquivo .txt de mensagens encontrado para análise de contexto."
            )
            return {}

        print(f"📄 Arquivo de mensagens encontrado: {os.path.basename(caminho_txt)}")
        with open(caminho_txt, "r", encoding="utf-8") as f:
            linhas = f.readlines()

        mapeamento = {}
        i = 0
        while i < len(linhas):
            linha_atual = linhas[i].strip()
            match_img = re.search(
                r"(IMG-\d{8}-WA\d{4}\.jpg)", linha_atual, re.IGNORECASE
            )
            if match_img:
                nome_img = match_img.group(1)
                informacoes_produto = _extrair_informacoes_produto(linhas, i + 1)
                if informacoes_produto:
                    mapeamento[nome_img] = informacoes_produto
            i += 1
        print(
            f"✅ Mapeamento concluído: {len(mapeamento)} imagens associadas a mensagens de texto."
        )
        return mapeamento
    except Exception as e:
        print(f"⚠️ Erro inesperado no mapeamento de mensagens: {e}")
        return {}


def _extrair_informacoes_produto(linhas: List[str], inicio_busca: int) -> str:
    """Extrai informações de produto das linhas seguintes a uma imagem."""
    if inicio_busca >= len(linhas):
        return ""
    informacoes_coletadas = []
    max_linhas_busca = 7
    for i in range(inicio_busca, min(inicio_busca + max_linhas_busca, len(linhas))):
        linha = linhas[i].strip()
        if not linha:
            continue
        if re.match(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", linha) or re.search(
            r"IMG-\d{8}-WA\d{4}\.jpg", linha, re.IGNORECASE
        ):
            break
        if any(
            palavra in linha.lower()
            for palavra in ["arquivo anexado", "mensagem apagada", "<anexado:"]
        ):
            continue
        informacoes_coletadas.append(linha)
    return "\n".join(informacoes_coletadas) if informacoes_coletadas else ""


# ================================
# PROCESSAMENTO DE IMAGENS E TEXTO (IA) - PROMPT CORRIGIDO
# ================================
def extrair_dados_de_lote(
    lote_de_caminhos: List[str], model, mensagens_por_imagem: Dict[str, str]
) -> Tuple[Dict[str, Any], int]:
    """
    Envia um lote de imagens E SEU CONTEXTO DE TEXTO para o Gemini e retorna os dados.
    Esta versão contém um prompt aprimorado para priorizar o texto.
    """
    if not lote_de_caminhos:
        return {}, 0

    prompt_e_imagens = []
    nomes_arquivos_lote = [os.path.basename(p) for p in lote_de_caminhos]

    # --- PROMPT REFORMULADO PARA CORRIGIR A LÓGICA DA IA ---
    prompt_instrucao = """
Sua tarefa é analisar os itens a seguir e catalogar produtos como "Avaria" ou "Uso Interno".
Cada item tem uma imagem e, opcionalmente, um texto de contexto de uma conversa.

[REGRA DE OURO]: O "Contexto da Mensagem" é a fonte de informação MAIS IMPORTANTE. A imagem serve apenas como apoio visual. Trate o texto como a fonte da verdade.

[COMO ANALISAR]:
1.  **Cenário 1 (Texto é o principal):** Se o "Contexto da Mensagem" descreve produtos (ex: "2 alface", "coentro", "saco de lixo"), EXTRAIA OS ITENS DIRETAMENTE DO TEXTO.
    - Se o texto menciona perdas, quebras, ou produtos estragados, classifique o `tipo` como "Avaria".
    - Se o texto menciona consumo da equipe ou da loja, classifique como "Uso Interno".
    - Se a imagem não mostra uma etiqueta clara para estes itens, os campos `peso`, `marca` e `codigo_barras` devem ser "N/A".
    - Se o texto contiver múltiplos itens (ex: "4 COENTRO\n2 ALFACE"), crie um item para cada um na lista de `itens`.

2.  **Cenário 2 (Imagem é o principal):** Se o texto estiver vazio ou não descritivo, e a imagem mostrar uma etiqueta de produto legível, extraia as informações da etiqueta na imagem.
    - `tipo` "Avaria": Extraia NOME e PESO.
    - `tipo` "Uso Interno": Extraia NOME, MARCA e CÓDIGO DE BARRAS. Priorize a extração do CÓDIGO DE BARRAS.

3.  **Cenário 3 (Erro):** Se for impossível determinar o produto ou a categoria, use o `tipo` "Erro".

[FORMATO DA RESPOSTA]: A resposta DEVE ser um único objeto JSON.

[EXEMPLO PRÁTICO]:
Se a entrada for:
* Arquivo: "IMG-1234.jpg"
* Contexto da Mensagem: "perda de hoje:\n4 coentro\n2 alface"
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

    prompt_e_imagens.append(prompt_instrucao)

    for caminho in lote_de_caminhos:
        try:
            img = Image.open(caminho)
            nome_arquivo = os.path.basename(caminho)
            contexto_mensagem = mensagens_por_imagem.get(nome_arquivo, "")
            prompt_arquivo = f"Arquivo: {nome_arquivo}"
            if contexto_mensagem:
                prompt_arquivo += f"\n[Contexto da Mensagem]:\n{contexto_mensagem}"
            prompt_e_imagens.append(prompt_arquivo)
            prompt_e_imagens.append(img)
        except Exception as e:
            nome_arquivo = os.path.basename(caminho)
            print(f"⚠️ Não foi possível abrir {nome_arquivo}: {e}")
            return {
                nome_arquivo: {
                    "tipo": "Erro",
                    "detalhes": f"Falha ao abrir arquivo: {e}",
                }
            }, 0

    for tentativa in range(MAX_RETRIES):
        try:
            response = model.generate_content(prompt_e_imagens)
            resposta_texto = response.text.strip()

            if resposta_texto.startswith("```json"):
                resposta_texto = resposta_texto[7:-3].strip()
            elif resposta_texto.startswith("```"):
                resposta_texto = resposta_texto[3:-3].strip()

            dados = json.loads(resposta_texto)
            
            # Extrair tokens consumidos da resposta
            tokens_consumidos = 0
            if hasattr(response, 'usage_metadata'):
                tokens_consumidos = getattr(response.usage_metadata, 'total_token_count', 0)
            elif hasattr(response, '_result') and hasattr(response._result, 'usage_metadata'):
                usage = response._result.usage_metadata
                tokens_consumidos = getattr(usage, 'total_token_count', 0)
            
            print(f"🪙 Tokens consumidos nesta requisição: {tokens_consumidos}")
            return dados, tokens_consumidos

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
    return {
        nome: {"tipo": "Erro", "detalhes": "Falha na API"}
        for nome in nomes_arquivos_lote
    }, 0


# ================================
# GERAÇÃO DE RELATÓRIOS E FUNÇÕES AUXILIARES
# (O restante do código permanece o mesmo)
# ================================
def salvar_relatorio_excel(
    novas_avarias: List[Dict], novos_usos_internos: List[Dict], novos_erros: List[Dict]
) -> None:
    """Salva os dados extraídos em um arquivo Excel com múltiplas abas."""
    try:
        print("📊 Gerando relatório Excel...")
        sheets = {}
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            try:
                sheets = pd.read_excel(
                    ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl"
                )
                print("✅ Arquivo Excel existente carregado para atualização.")
            except Exception as e:
                print(
                    f"⚠️ Erro ao ler Excel existente: {e}. Um novo arquivo será criado."
                )

        # Define a ordem das colunas para consistência
        colunas_avarias = [
            "Produto",
            "Detalhes",
            "Observação da Mensagem",
            "Caminho da Imagem",
            "Ver Imagem",
        ]
        colunas_uso_interno = [
            "Produto",
            "Detalhes",
            "Observação da Mensagem",
            "Caminho da Imagem",
            "Ver Imagem",
        ]
        colunas_erros = [
            "Arquivo",
            "Detalhes do Erro",
            "Observação da Mensagem",
            "Caminho da Imagem",
            "Ver Imagem",
        ]

        df_novas_avarias = pd.DataFrame(novas_avarias, columns=colunas_avarias)
        df_novos_usos_internos = pd.DataFrame(
            novos_usos_internos, columns=colunas_uso_interno
        )
        df_novos_erros = pd.DataFrame(novos_erros, columns=colunas_erros)

        df_avarias_final = pd.concat(
            [
                sheets.get("Avarias", pd.DataFrame(columns=colunas_avarias)),
                df_novas_avarias,
            ],
            ignore_index=True,
        )

        df_uso_interno_final = pd.concat(
            [
                sheets.get("Uso Interno", pd.DataFrame(columns=colunas_uso_interno)),
                df_novos_usos_internos,
            ],
            ignore_index=True,
        )

        df_erros_final = pd.concat(
            [
                sheets.get("Erros de Análise", pd.DataFrame(columns=colunas_erros)),
                df_novos_erros,
            ],
            ignore_index=True,
        )

        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
            if not df_avarias_final.empty:
                df_avarias_final.to_excel(writer, sheet_name="Avarias", index=False)
            if not df_uso_interno_final.empty:
                df_uso_interno_final.to_excel(
                    writer, sheet_name="Uso Interno", index=False
                )
            if not df_erros_final.empty:
                df_erros_final.to_excel(
                    writer, sheet_name="Erros de Análise", index=False
                )

            _aplicar_formatacao_excel(
                writer, df_avarias_final, df_uso_interno_final, df_erros_final
            )

        print(f"\n📋 RELATÓRIO SALVO: {ARQUIVO_SAIDA_EXCEL}")
        print(f"  ├─ Novas Avarias: {len(novas_avarias)}")
        print(f"  ├─ Novos Usos Internos: {len(novos_usos_internos)}")
        print(f"  └─ Novos Erros: {len(novos_erros)}")

    except Exception as e:
        print(f"❌ Erro crítico ao salvar o arquivo Excel: {e}")


def _aplicar_formatacao_excel(
    writer,
    df_avarias: pd.DataFrame,
    df_uso_interno: pd.DataFrame,
    df_erros: pd.DataFrame,
) -> None:
    """Aplica formatação e hyperlinks ao arquivo Excel."""
    try:
        workbook = writer.book
        link_font = Font(color="0563C1", underline="single")

        for sheet_name, df in [
            ("Avarias", df_avarias),
            ("Uso Interno", df_uso_interno),
            ("Erros de Análise", df_erros),
        ]:
            if sheet_name not in workbook.sheetnames or df.empty:
                continue
            sheet = workbook[sheet_name]
            try:
                headers = [cell.value for cell in sheet[1]]
                link_col_idx = headers.index("Ver Imagem") + 1
                for index, registro in df.iterrows():
                    if "Ver Imagem" in registro and pd.notna(registro["Ver Imagem"]):
                        link_cell = sheet.cell(row=index + 2, column=link_col_idx)
                        # Usar caminho local para abrir no Windows
                        caminho_imagem = registro["Ver Imagem"]
                        if caminho_imagem.startswith("http"):
                            # Se for URL web, usar diretamente
                            link_cell.hyperlink = caminho_imagem
                            link_cell.value = "Abrir Imagem"
                        else:
                            # É um caminho local, usar como hyperlink para abrir no Windows
                            link_cell.hyperlink = (
                                f"file:///{caminho_imagem.replace(os.sep, '/')}"
                            )
                            link_cell.value = (
                                caminho_imagem  # Mostrar o caminho completo
                            )
                        link_cell.font = link_font
            except (ValueError, IndexError):
                pass
            for column in sheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        cell_length = len(str(cell.value))
                        if cell_length > max_length:
                            max_length = cell_length
                    except:
                        pass
                adjusted_width = min(max_length + 2, 60)
                sheet.column_dimensions[column_letter].width = adjusted_width
    except Exception as e:
        print(f"⚠️ Erro na formatação do Excel: {e}")


def main() -> None:
    """Função principal do analisador de imagens."""
    print("🚀 ANALISADOR MESTRE DE IMAGENS E MENSAGENS - INICIANDO")
    print("=" * 60)
    try:
        verificar_dependencias()
        config = ProcessingConfig()
        
        # Mostrar configurações de otimização
        print(f"⚙️ Configurações de processamento:")
        print(f"   • Tamanho do lote: {TAMANHO_LOTE} imagens/requisição")
        print(f"   • Workers paralelos: {MAX_WORKERS}")
        print(f"   • Delay entre requisições: {REQUEST_DELAY}s")
        print(f"   • Modelo: {GEMINI_MODEL}")
        print()
        
        if not os.path.exists(DIRETORIO_IMAGENS):
            os.makedirs(DIRETORIO_IMAGENS)
            print(f"📁 Pasta '{DIRETORIO_IMAGENS}' criada.")
            print(
                "📋 Adicione suas imagens e o arquivo .txt de mensagens, depois execute novamente."
            )
            return

        imagens_processadas = carregar_logs()
        print(f"📝 Arquivos já processados anteriormente: {len(imagens_processadas)}")

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        print(f"🤖 Modelo {GEMINI_MODEL} configurado.")

        imagens_para_processar = [
            os.path.join(DIRETORIO_IMAGENS, f)
            for f in sorted(os.listdir(DIRETORIO_IMAGENS))
            if f.lower().endswith(EXTENSOES_IMAGEM) and f not in imagens_processadas
        ]

        if not imagens_para_processar:
            print("✅ Nenhuma imagem nova para analisar.")
            return

        lotes_de_imagens = [
            imagens_para_processar[i : i + TAMANHO_LOTE]
            for i in range(0, len(imagens_para_processar), TAMANHO_LOTE)
        ]

        print(f"🖼️ Novas imagens a processar: {len(imagens_para_processar)}")
        print(
            f"📦 Lotes criados: {len(lotes_de_imagens)} (até {TAMANHO_LOTE} imagens por lote)"
        )

        mensagens_por_imagem = mapear_mensagens_para_imagens()
        novas_avarias, novos_usos_internos, novos_erros = [], [], []
        total_tokens_consumidos = 0

        print("\n🔄 Iniciando processamento com lógica de texto aprimorada...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_lote = {}
            for idx, lote in enumerate(lotes_de_imagens):
                # Adicionar delay entre submissões para respeitar limites de RPM
                if idx > 0:
                    time.sleep(REQUEST_DELAY)
                future_to_lote[executor.submit(
                    extrair_dados_de_lote, lote, model, mensagens_por_imagem
                )] = lote
            with tqdm(
                total=len(imagens_para_processar), desc="Analisando", unit="img"
            ) as pbar:
                for future in concurrent.futures.as_completed(future_to_lote):
                    # Verificar se foi cancelado
                    if verificar_cancelamento():
                        print("\n⚠️ Processamento cancelado pelo usuário")
                        executor.shutdown(wait=False, cancel_futures=True)
                        return
                    
                    lote_processado_caminhos = future_to_lote[future]
                    lote_processado_nomes = [
                        os.path.basename(p) for p in lote_processado_caminhos
                    ]
                    try:
                        resultados_lote, tokens_do_lote = future.result()
                        total_tokens_consumidos += tokens_do_lote
                        for nome_arquivo in lote_processado_nomes:
                            _processar_resultado_arquivo(
                                nome_arquivo,
                                resultados_lote,
                                mensagens_por_imagem,
                                novas_avarias,
                                novos_usos_internos,
                                novos_erros,
                            )
                            registrar_log(nome_arquivo)
                            pbar.update(1)
                    except Exception as e:
                        print(f"❌ Erro crítico no processamento do lote: {e}")
                        for nome in lote_processado_nomes:
                            registrar_log(nome)
                        pbar.update(len(lote_processado_nomes))

        salvar_relatorio_excel(novas_avarias, novos_usos_internos, novos_erros)
        
        # Registrar consumo com detalhes da sessão
        total_imagens = len(imagens_para_processar)
        detalhes = f"Processamento de {total_imagens} imagens, {len(novas_avarias)} avarias, {len(novos_usos_internos)} uso interno, {len(novos_erros)} erros"
        registrar_consumo_log(total_tokens_consumidos, detalhes)

        print("\n" + "=" * 60)
        print("✅ ANÁLISE CONCLUÍDA COM SUCESSO!")
        print(
            f"🪙  Total de tokens consumidos nesta execução: {total_tokens_consumidos:,}"
        )
        print(f"📊 Log de consumo salvo em: {LOG_CONSUMO_FILE}")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ Erro crítico na execução principal: {e}")


def _processar_resultado_arquivo(
    nome_arquivo: str,
    resultados_lote: Dict[str, Any],
    mensagens_por_imagem: Dict[str, str],
    novas_avarias: List[Dict],
    novos_usos_internos: List[Dict],
    novos_erros: List[Dict],
) -> None:
    """Processa o resultado de análise de um arquivo específico."""
    try:
        dados = resultados_lote.get(nome_arquivo)
        if not dados:
            dados = {
                "tipo": "Erro",
                "detalhes": "Arquivo não retornado na resposta do lote.",
            }

        caminho_absoluto = os.path.abspath(
            os.path.join(DIRETORIO_IMAGENS, nome_arquivo)
        )
        msg_associada = mensagens_por_imagem.get(nome_arquivo, "")
        tipo = dados.get("tipo")
        itens = dados.get("itens", [])

        if not isinstance(itens, list):
            itens = [dados] if dados else []

        if tipo == "Avaria":
            _processar_avaria(itens, msg_associada, caminho_absoluto, novas_avarias)
        elif tipo == "Uso Interno":
            _processar_uso_interno(
                itens, msg_associada, caminho_absoluto, novos_usos_internos
            )
        else:  # Erro
            _processar_erro(
                dados, nome_arquivo, msg_associada, caminho_absoluto, novos_erros
            )
    except Exception as e:
        caminho_absoluto = os.path.abspath(
            os.path.join(DIRETORIO_IMAGENS, nome_arquivo)
        )
        novos_erros.append(
            {
                "Arquivo": nome_arquivo,
                "Detalhes do Erro": f"Erro de processamento interno: {e}",
                "Observação da Mensagem": mensagens_por_imagem.get(
                    nome_arquivo, "Nenhuma"
                ),
                "Caminho da Imagem": caminho_absoluto,
                "Ver Imagem": caminho_absoluto,  # Caminho local para abrir no Windows
            }
        )


def _processar_avaria(
    itens: List[Dict],
    msg_associada: str,
    caminho_absoluto: str,
    novas_avarias: List[Dict],
) -> None:
    """Processa e formata itens de avaria para o relatório."""
    for item in itens:
        detalhes = f'Peso: {item.get("peso", "N/A")}'
        novas_avarias.append(
            {
                "Produto": item.get("produto", "N/A"),
                "Detalhes": detalhes,
                "Observação da Mensagem": (
                    msg_associada.replace("\n", " | ") if msg_associada else "Nenhuma"
                ),
                "Caminho da Imagem": caminho_absoluto,
                "Ver Imagem": caminho_absoluto,  # Caminho local para abrir no Windows
            }
        )


def _processar_uso_interno(
    itens: List[Dict],
    msg_associada: str,
    caminho_absoluto: str,
    novos_usos_internos: List[Dict],
) -> None:
    """Processa e formata itens de uso interno para o relatório."""
    for item in itens:
        detalhes_list = []
        if item.get("marca"):
            detalhes_list.append(f'Marca: {item.get("marca")}')
        if item.get("codigo_barras"):
            detalhes_list.append(f'Cód. Barras: {item.get("codigo_barras")}')
        novos_usos_internos.append(
            {
                "Produto": item.get("produto", "N/A"),
                "Detalhes": " | ".join(detalhes_list) if detalhes_list else "N/A",
                "Observação da Mensagem": (
                    msg_associada.replace("\n", " | ") if msg_associada else "Nenhuma"
                ),
                "Caminho da Imagem": caminho_absoluto,
                "Ver Imagem": caminho_absoluto,  # Caminho local para abrir no Windows
            }
        )


def _processar_erro(
    dados: Dict[str, Any],
    nome_arquivo: str,
    msg_associada: str,
    caminho_absoluto: str,
    novos_erros: List[Dict],
) -> None:
    """Processa e formata erros de análise para o relatório."""
    novos_erros.append(
        {
            "Arquivo": nome_arquivo,
            "Detalhes do Erro": dados.get("detalhes", "Erro não especificado."),
            "Observação da Mensagem": (
                msg_associada.replace("\n", " | ") if msg_associada else "Nenhuma"
            ),
            "Caminho da Imagem": caminho_absoluto,
            "Ver Imagem": caminho_absoluto,  # Caminho local para abrir no Windows
        }
    )


if __name__ == "__main__":
    main()
