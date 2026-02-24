"""
INTERFACE WEB PARA ANALISADOR DE IMAGENS E MENSAGENS
Aplicação Flask - Compatível com desenvolvimento local e Vercel
"""

import os
import json
import shutil
import zipfile
import sys
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    flash,
    redirect,
    url_for,
    make_response,
)
import pandas as pd
import threading
import time
import traceback
from functools import lru_cache
import gzip
from werkzeug.middleware.proxy_fix import ProxyFix

from src.extrair_arquivos import ExtratorArquivos

# Detectar ambiente e ajustar caminhos
def get_base_path():
    """Obtém o caminho base da aplicação considerando ambiente Vercel."""
    if "VERCEL" in os.environ:
        # Em produção na Vercel
        return "/tmp"
    else:
        # Em desenvolvimento local
        return os.path.dirname(os.path.abspath(__file__))


BASE_PATH = get_base_path()

# Importar otimizações
try:
    from src.optimizations import init_optimizations
except ImportError:
    # Função vazia se não conseguir importar
    def init_optimizations(app):
        pass


app = Flask(
    __name__,
    template_folder=os.path.join(BASE_PATH, "templates"),
    static_folder=os.path.join(BASE_PATH, "static"),
)

app.secret_key = os.environ.get("SECRET_KEY", "sua_chave_secreta_aqui_mude_em_producao")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max por upload

# Otimizações de performance
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = timedelta(hours=1)  # Cache estático
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Aplicar otimizações
init_optimizations(app)

# Cache para configurações
_config_cache = None
_config_cache_time = None
CONFIG_CACHE_TTL = 300  # 5 minutos

# Configurações básicas adaptadas para ambiente
UPLOAD_FOLDER = os.path.join(BASE_PATH, "imagens_para_analisar")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "txt", "zip", "rar", "7z", "tar", "gz", "bz2", "tgz"}
EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")
DIRETORIO_IMAGENS = UPLOAD_FOLDER
ARQUIVO_SAIDA_EXCEL = os.path.join(
    BASE_PATH, "resultados", "Relatorio_Mestre_Produtos.xlsx"
)
LOG_CONSUMO_FILE = os.path.join(BASE_PATH, "logs", "log_consumo_tokens.txt")
LOG_PROCESSADOS_FILE = os.path.join(BASE_PATH, "logs", "log_mestre.txt")
CONFIG_FILE = os.path.join(BASE_PATH, "config", "config.json")

# Garantir que os diretórios existam
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, "resultados"), exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, "logs"), exist_ok=True)

# Variáveis globais para controle de processamento
processamento_ativo = False
processamento_cancelado = False
progresso_atual = {"progresso": 0, "status": "Aguardando", "logs": []}

# Buffer de logs em tempo real
logs_aplicacao_buffer = []

# Sistema de captura de prints
class LogCapture:
    """Captura prints e redireciona para o buffer de logs."""
    def __init__(self):
        self.terminal = sys.stdout
        self.log_buffer = logs_aplicacao_buffer
        self._in_write = False  # Prevenir recursão
        
    def write(self, mensagem):
        # Sempre escrever no terminal
        self.terminal.write(mensagem)
        self.terminal.flush()
        
        # Prevenir recursão infinita
        if self._in_write:
            return
            
        try:
            self._in_write = True
            # Se logs detalhados estiverem ativados, adicionar ao buffer
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if config.get("interface", {}).get("logs_detalhados_aplicacao", False):
                        mensagem = mensagem.strip()
                        if mensagem:  # Ignorar linhas vazias
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            self.log_buffer.append({
                                "timestamp": timestamp,
                                "tipo": "aplicacao",
                                "mensagem": mensagem
                            })
                            # Manter apenas os últimos 200 logs
                            if len(self.log_buffer) > 200:
                                self.log_buffer[:] = self.log_buffer[-200:]
        except:
            pass  # Ignorar erros na captura de logs
        finally:
            self._in_write = False
    
    def flush(self):
        self.terminal.flush()

# Redirecionar stdout para captura de logs
sys.stdout = LogCapture()


@lru_cache(maxsize=1)
def carregar_configuracao():
    """Carrega configurações do arquivo JSON com cache."""
    global _config_cache, _config_cache_time

    # Verificar cache
    current_time = time.time()
    if (
        _config_cache is not None
        and _config_cache_time is not None
        and current_time - _config_cache_time < CONFIG_CACHE_TTL
    ):
        return _config_cache

    config_padrao = {
        "api": {
            "provider": "gemini",
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
            "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "modelo_selecionado": "gemini-2.5-flash-lite",
        },
        "processamento": {
            "modelo_gemini": "gemini-2.5-flash-lite",
            "temperatura": 0.1,
            "max_tokens": 4000,
            "timeout": 60,
            "tamanho_lote": 12,
            "max_workers": 1,
            "request_delay": 13.0,
        },
        "interface": {
            "tema": "escuro",
            "auto_refresh": True,
            "logs_tempo_real": True,
            "logs_detalhados_aplicacao": False,
        },
    }

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Mesclar com configuração padrão para garantir todas as chaves
                for key in config_padrao:
                    if key not in config:
                        config[key] = config_padrao[key]
                    elif isinstance(config_padrao[key], dict):
                        for subkey in config_padrao[key]:
                            if subkey not in config[key]:
                                config[key][subkey] = config_padrao[key][subkey]

                # Priorizar variáveis de ambiente
                if os.environ.get("GEMINI_API_KEY"):
                    config["api"]["gemini_api_key"] = os.environ.get("GEMINI_API_KEY")
                if os.environ.get("OPENAI_API_KEY"):
                    config["api"]["openai_api_key"] = os.environ.get("OPENAI_API_KEY")
                if os.environ.get("ANTHROPIC_API_KEY"):
                    config["api"]["anthropic_api_key"] = os.environ.get(
                        "ANTHROPIC_API_KEY"
                    )

                # Atualizar cache
                _config_cache = config
                _config_cache_time = current_time
                return config
        else:
            # Criar arquivo de configuração padrão se não estiver na Vercel
            if "VERCEL" not in os.environ:
                salvar_configuracao(config_padrao)
            _config_cache = config_padrao
            _config_cache_time = current_time
            return config_padrao
    except Exception as e:
        print(f"Erro ao carregar configuração: {e}")
        return config_padrao


def salvar_configuracao(config):
    """Salva configurações no arquivo JSON e limpa cache."""
    global _config_cache, _config_cache_time

    # No ambiente Vercel, não tenta salvar no filesystem (read-only)
    if "VERCEL" in os.environ:
        print(
            "⚠️ Ambiente Vercel: configurações devem ser definidas como variáveis de ambiente"
        )
        return True

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Limpar cache
        _config_cache = None
        _config_cache_time = None
        carregar_configuracao.cache_clear()

        return True
    except Exception as e:
        print(f"Erro ao salvar configuração: {e}")
        return False


def carregar_logs():
    """Carrega os logs de arquivos já processados."""
    if not os.path.exists(LOG_PROCESSADOS_FILE):
        return set()
    try:
        arquivos_processados = set()
        with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    # Formato novo: "2025-09-26 12:00:00 - Processado: arquivo.jpg"
                    if " - Processado: " in linha:
                        nome_arquivo = linha.split(" - Processado: ")[-1]
                        arquivos_processados.add(nome_arquivo)
                    # Formato antigo: apenas o nome do arquivo
                    else:
                        arquivos_processados.add(linha)
        return arquivos_processados
    except IOError as e:
        print(f"⚠️ Erro ao ler log de arquivos processados: {e}")
        return set()


def verificar_e_corrigir_configuracao():
    """Verifica e corrige a configuração antes do processamento."""
    config = carregar_configuracao()
    api_key = config.get("api", {}).get("gemini_api_key", "")
    
    if not api_key or api_key.strip() == "":
        return False, "Chave da API Gemini não configurada"
    
    try:
        # Configuração já está em config/config.json (arquivo único)
        return True, f"Configuração válida (API Key: {api_key[:8]}...)"
        
    except Exception as e:
        return False, f"Erro ao sincronizar configuração: {e}"


def log_aplicacao(mensagem, tipo="info"):
    """Adiciona uma mensagem ao buffer de logs da aplicação."""
    global logs_aplicacao_buffer
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "tipo": tipo,
        "mensagem": mensagem
    }
    logs_aplicacao_buffer.append(log_entry)
    # Manter apenas os últimos 200 logs
    if len(logs_aplicacao_buffer) > 200:
        logs_aplicacao_buffer = logs_aplicacao_buffer[-200:]
    
    # Sempre imprimir no terminal
    print(mensagem)

def executar_processamento_principal():
    """Executa o processamento principal importando e rodando o script original."""
    global progresso_atual

    try:
        # Verificar e sincronizar configurações
        config_ok, config_msg = verificar_e_corrigir_configuracao()
        log_aplicacao(f"🔧 {config_msg}")
        progresso_atual["logs"].append(f"🔧 {config_msg}")
        
        if not config_ok:
            progresso_atual["status"] = "Erro: API Key não configurada"
            return False

        log_aplicacao("🔑 API Key encontrada, continuando...")
        progresso_atual["logs"].append("🔑 API Key encontrada, continuando...")

        # Verificar se há imagens para processar
        if not os.path.exists(DIRETORIO_IMAGENS):
            log_aplicacao("❌ Diretório de imagens não encontrado!")
            progresso_atual["logs"].append("❌ Diretório de imagens não encontrado!")
            return False

        imagens = [
            f
            for f in os.listdir(DIRETORIO_IMAGENS)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]

        if not imagens:
            log_aplicacao("❌ Nenhuma imagem encontrada para processar!")
            progresso_atual["logs"].append(
                "❌ Nenhuma imagem encontrada para processar!"
            )
            return False

        log_aplicacao(f"📸 Encontradas {len(imagens)} imagens para processar")
        progresso_atual["logs"].append(
            f"📸 Encontradas {len(imagens)} imagens para processar"
        )

        # No ambiente Vercel, o processamento completo pode ser limitado
        if "VERCEL" in os.environ:
            log_aplicacao("⚠️ Ambiente Vercel: processamento completo pode ser limitado")
            progresso_atual["logs"].append(
                "⚠️ Ambiente Vercel: processamento completo pode ser limitado"
            )
            return False

        # Importar e executar o módulo principal (apenas em desenvolvimento local)
        extrair_dados_path = os.path.join(BASE_PATH, "src", "extrair-dados.py")
        if os.path.exists(extrair_dados_path):
            log_aplicacao("⚙️ Carregando módulo de processamento...")
            progresso_atual["logs"].append("⚙️ Carregando módulo de processamento...")
            spec = importlib.util.spec_from_file_location(
                "extrair_dados", extrair_dados_path
            )
            extrair_dados = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(extrair_dados)
        else:
            log_aplicacao("❌ Script de processamento não encontrado")
            progresso_atual["logs"].append("❌ Script de processamento não encontrado")
            return False

        log_aplicacao("🚀 Iniciando análise com IA...")
        progresso_atual["logs"].append("🚀 Iniciando análise com IA...")

        # Executar a função principal
        extrair_dados.main()

        # Verificar se o relatório foi gerado
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            log_aplicacao("✅ Relatório Excel gerado com sucesso!")
            progresso_atual["logs"].append("✅ Relatório Excel gerado com sucesso!")
            return True
        else:
            log_aplicacao("⚠️ Processamento concluído, mas relatório não foi encontrado")
            progresso_atual["logs"].append(
                "⚠️ Processamento concluído, mas relatório não foi encontrado"
            )
            return False

    except Exception as e:
        erro_msg = f"Erro ao executar processamento: {str(e)}"
        log_aplicacao(f"❌ {erro_msg}", "erro")
        progresso_atual["logs"].append(f"❌ {erro_msg}")
        return False


def allowed_file(filename):
    """Verifica se o arquivo tem extensão permitida, incluindo extensões compostas."""
    if not filename or "." not in filename:
        return False
    
    filename_lower = filename.lower()
    
    # Verificar extensões compostas primeiro
    extensoes_compostas = [".tar.gz", ".tar.bz2", ".tgz"]
    for ext_composta in extensoes_compostas:
        if filename_lower.endswith(ext_composta):
            return True
    
    # Verificar extensão simples
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS


def obter_estatisticas():
    """Obtém estatísticas do sistema."""
    stats = {
        "imagens_total": 0,
        "imagens_processadas": 0,
        "imagens_pendentes": 0,
        "ultimo_processamento": "Nunca",
        "tokens_consumidos_hoje": 0,
        "relatorio_existe": False,
    }

    try:
        # Contar imagens apenas se diretório mudou
        if os.path.exists(DIRETORIO_IMAGENS):
            todos_arquivos = os.listdir(DIRETORIO_IMAGENS)
            # Filtro otimizado para extensões de imagem
            stats["imagens_total"] = sum(
                1 for f in todos_arquivos if f.lower().endswith(EXTENSOES_IMAGEM)
            )

        # Imagens já processadas
        processadas = carregar_logs()
        stats["imagens_processadas"] = len(processadas)
        stats["imagens_pendentes"] = max(
            0, stats["imagens_total"] - stats["imagens_processadas"]
        )

        # Último processamento - cache por arquivo
        if os.path.exists(LOG_PROCESSADOS_FILE):
            mod_time = os.path.getmtime(LOG_PROCESSADOS_FILE)
            stats["ultimo_processamento"] = datetime.fromtimestamp(mod_time).strftime(
                "%d/%m/%Y %H:%M"
            )

        # Tokens consumidos hoje - otimizado
        if os.path.exists(LOG_CONSUMO_FILE):
            hoje = datetime.now().strftime("%Y-%m-%d")
            try:
                with open(LOG_CONSUMO_FILE, "r", encoding="utf-8") as f:
                    # Ler apenas últimas linhas para performance
                    lines = f.readlines()[-50:]  # Últimas 50 linhas
                    for linha in lines:
                        if hoje in linha and "tokens consumidos:" in linha:
                            tokens_str = (
                                linha.split("tokens consumidos:")[1]
                                .strip()
                                .replace(",", "")
                            )
                            stats["tokens_consumidos_hoje"] += int(tokens_str)
            except (ValueError, IndexError):
                pass

        # Verifica se existe relatório
        stats["relatorio_existe"] = os.path.exists(ARQUIVO_SAIDA_EXCEL)

    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")

    return stats


def obter_resultados_recentes():
    """Obtém os resultados mais recentes do relatório."""
    resultados = {"avarias": [], "uso_interno": [], "erros": []}

    try:
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            # Ler as últimas 10 entradas de cada tipo
            sheets = pd.read_excel(
                ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl"
            )

            if "Avarias" in sheets:
                df_avarias = sheets["Avarias"].tail(10)
                # Tratar valores NaN
                df_avarias = df_avarias.fillna("-")
                resultados["avarias"] = df_avarias.to_dict("records")

            if "Uso Interno" in sheets:
                df_uso = sheets["Uso Interno"].tail(10)
                # Tratar valores NaN
                df_uso = df_uso.fillna("-")
                resultados["uso_interno"] = df_uso.to_dict("records")

            if "Erros de Análise" in sheets:
                df_erros = sheets["Erros de Análise"].tail(10)
                # Tratar valores NaN
                df_erros = df_erros.fillna("-")
                resultados["erros"] = df_erros.to_dict("records")

    except Exception as e:
        print(f"Erro ao ler resultados: {e}")

    return resultados


def extrair_arquivos_comprimidos(pasta_imagens, logs_callback=None):
    """
    Extrai arquivos comprimidos da pasta de imagens.
    
    Args:
        pasta_imagens (str): Caminho para a pasta de imagens
        logs_callback (function): Função callback para adicionar logs
    
    Returns:
        dict: Resultados da extração
    """
    try:
        extrator = ExtratorArquivos(pasta_origem=pasta_imagens)
        arquivos_comprimidos = extrator.listar_arquivos_comprimidos()
        
        if not arquivos_comprimidos:
            if logs_callback:
                logs_callback("📦 Nenhum arquivo comprimido encontrado")
            return {"arquivos_encontrados": 0, "arquivos_extraidos": 0}
        
        if logs_callback:
            logs_callback(f"📦 Encontrados {len(arquivos_comprimidos)} arquivos comprimidos")
            logs_callback("📦 Iniciando extração...")
        
        # Extrair todos os arquivos
        resultados = extrator.extrair_todos(
            criar_subpastas=False,  # Não criar subpastas para manter na pasta principal
            remover_originais=False  # Manter originais por segurança
        )
        
        sucessos = sum(1 for sucesso in resultados.values() if sucesso)
        
        if logs_callback:
            if sucessos > 0:
                logs_callback(f"✅ {sucessos}/{len(arquivos_comprimidos)} arquivos extraídos com sucesso")
                for arquivo, sucesso in resultados.items():
                    status = "✅" if sucesso else "❌"
                    logs_callback(f"  {status} {arquivo}")
            else:
                logs_callback("⚠️ Nenhum arquivo foi extraído com sucesso")
        
        return {
            "arquivos_encontrados": len(arquivos_comprimidos),
            "arquivos_extraidos": sucessos,
            "detalhes": resultados
        }
        
    except Exception as e:
        if logs_callback:
            logs_callback(f"⚠️ Erro durante extração: {str(e)}")
        return {
            "arquivos_encontrados": 0,
            "arquivos_extraidos": 0,
            "erro": str(e)
        }


def processar_em_background():
    """Executa o processamento em background."""
    global processamento_ativo, progresso_atual, processamento_cancelado

    try:
        processamento_ativo = True
        processamento_cancelado = False
        progresso_atual = {
            "progresso": 0,
            "status": "Iniciando processamento...",
            "logs": [],
        }

        # Limpar arquivo de cancelamento se existir
        cancel_file = os.path.join(BASE_PATH, ".cancel_processing")
        if os.path.exists(cancel_file):
            try:
                os.remove(cancel_file)
            except:
                pass

        # Log inicial
        timestamp = datetime.now().strftime("%H:%M:%S")
        progresso_atual["logs"].append(f"🚀 Iniciando processamento às {timestamp}")

        # Verificar se estamos na Vercel
        if "VERCEL" in os.environ:
            progresso_atual["status"] = (
                "❌ Erro: Processamento não disponível na Vercel"
            )
            progresso_atual["logs"].append(
                "❌ O processamento completo não está disponível no ambiente Vercel"
            )
            progresso_atual["logs"].append(
                "💡 Use o ambiente local para processamento de imagens"
            )
            return

        # Verificar configurações
        progresso_atual["progresso"] = 5
        progresso_atual["status"] = "🔍 Verificando configurações..."
        config = carregar_configuracao()
        api_key = config.get("api", {}).get("gemini_api_key", "")

        if not api_key:
            progresso_atual["status"] = "❌ Erro: API Key não configurada"
            progresso_atual["logs"].append("❌ Chave da API Gemini não encontrada!")
            progresso_atual["logs"].append(
                "⚙️ Configure a API Key na página de Configurações"
            )
            return

        # Verificar se foi cancelado
        if processamento_cancelado:
            progresso_atual["status"] = "❌ Processamento cancelado pelo usuário"
            progresso_atual["logs"].append("⚠️ Processamento cancelado")
            return

        # Extrair arquivos comprimidos se existirem
        progresso_atual["progresso"] = 8
        progresso_atual["status"] = "📦 Verificando arquivos comprimidos..."
        
        def adicionar_log(mensagem):
            progresso_atual["logs"].append(mensagem)
        
        resultado_extracao = extrair_arquivos_comprimidos(DIRETORIO_IMAGENS, adicionar_log)
        
        if resultado_extracao["arquivos_encontrados"] > 0:
            progresso_atual["status"] = "📦 Extração de arquivos concluída"
        else:
            progresso_atual["status"] = "📦 Nenhum arquivo comprimido encontrado"

        # Verificar imagens disponíveis
        progresso_atual["progresso"] = 10
        progresso_atual["status"] = "📸 Verificando imagens disponíveis..."

        if not os.path.exists(DIRETORIO_IMAGENS):
            progresso_atual["logs"].append("❌ Diretório de imagens não encontrado")
            progresso_atual["status"] = "❌ Erro: Diretório não encontrado"
            return

        imagens = [
            f
            for f in os.listdir(DIRETORIO_IMAGENS)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]

        if not imagens:
            progresso_atual["logs"].append(
                "❌ Nenhuma imagem encontrada para processar"
            )
            progresso_atual["status"] = "❌ Erro: Nenhuma imagem encontrada"
            return

        progresso_atual["logs"].append(
            f"📸 Encontradas {len(imagens)} imagens para processar"
        )

        # Verificar imagens já processadas
        progresso_atual["progresso"] = 20
        progresso_atual["status"] = "📋 Verificando arquivos já processados..."

        if os.path.exists(LOG_PROCESSADOS_FILE):
            with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
                processadas = set(line.strip() for line in f if line.strip())
            progresso_atual["logs"].append(
                f"📝 {len(processadas)} imagens já foram processadas anteriormente"
            )
        else:
            processadas = set()
            progresso_atual["logs"].append("📝 Nenhuma imagem processada anteriormente")

        novas_imagens = [img for img in imagens if img not in processadas]
        progresso_atual["logs"].append(
            f"🆕 {len(novas_imagens)} novas imagens para processar"
        )

        if not novas_imagens:
            progresso_atual["progresso"] = 100
            progresso_atual["status"] = "✅ Todas as imagens já foram processadas!"
            progresso_atual["logs"].append("✅ Todas as imagens já foram processadas!")
            return

        # Verificar se foi cancelado antes de iniciar processamento
        if processamento_cancelado:
            progresso_atual["status"] = "❌ Processamento cancelado pelo usuário"
            progresso_atual["logs"].append("⚠️ Processamento cancelado antes de iniciar análise")
            return

        # Executar processamento principal
        progresso_atual["progresso"] = 30
        progresso_atual["status"] = "🤖 Iniciando análise com IA Gemini..."
        progresso_atual["logs"].append("⚙️ Carregando script de processamento...")

        sucesso = executar_processamento_principal()

        if sucesso:
            progresso_atual["progresso"] = 100
            progresso_atual["status"] = "✅ Processamento concluído com sucesso!"
            progresso_atual["logs"].append("✅ Análise concluída com sucesso!")

            # Verificar resultados
            if os.path.exists(ARQUIVO_SAIDA_EXCEL):
                progresso_atual["logs"].append(
                    f"📄 Relatório Excel gerado: {ARQUIVO_SAIDA_EXCEL}"
                )

                # Contar resultados
                try:
                    sheets = pd.read_excel(
                        ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl"
                    )
                    for sheet_name, df in sheets.items():
                        if not df.empty:
                            progresso_atual["logs"].append(
                                f"📊 {sheet_name}: {len(df)} registros"
                            )
                except Exception as e:
                    progresso_atual["logs"].append(
                        f"⚠️ Erro ao ler estatísticas do relatório: {e}"
                    )
            else:
                progresso_atual["logs"].append("⚠️ Relatório não foi gerado")
        else:
            progresso_atual["status"] = "❌ Erro durante processamento"
            progresso_atual["logs"].append("❌ Erro durante o processamento principal")

    except Exception as e:
        erro_msg = f"Erro durante processamento: {str(e)}"
        progresso_atual["status"] = f"❌ Erro: {str(e)}"
        progresso_atual["logs"].append(f"❌ {erro_msg}")
        print(f"Erro em processar_em_background: {e}")

    finally:
        processamento_ativo = False
        processamento_cancelado = False
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Adicionar mensagem de finalização apenas se não foi adicionada antes
        if progresso_atual["logs"] and not progresso_atual["logs"][-1].startswith("🏁"):
            progresso_atual["logs"].append(f"🏁 Processamento finalizado às {timestamp}")


@app.route("/")
def index():
    """Página principal com cache de resposta."""
    response = make_response()

    # Cache para melhor performance
    if request.headers.get("Cache-Control") != "no-cache":
        response.headers["Cache-Control"] = "public, max-age=60"  # 1 minuto

    stats = obter_estatisticas()
    resultados = obter_resultados_recentes()

    # Renderizar template
    html = render_template("index.html", stats=stats, resultados=resultados)
    response.set_data(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"

    return response


@app.route("/upload")
def upload_page():
    """Página de upload."""
    return render_template("upload.html")


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

        uploaded_files = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                uploaded_files.append(filename)

        return jsonify(
            {
                "success": True,
                "message": f"{len(uploaded_files)} arquivo(s) enviado(s) com sucesso!",
                "files": uploaded_files,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro no upload: {str(e)}"})


@app.route("/processar", methods=["POST"])
def iniciar_processamento():
    """Inicia o processamento das imagens."""
    global processamento_ativo

    # Verificar se estamos na Vercel
    if "VERCEL" in os.environ:
        return jsonify(
            {
                "success": False,
                "message": "Processamento não disponível no ambiente Vercel. Use o ambiente local.",
            }
        )

    if processamento_ativo:
        return jsonify({"success": False, "message": "Processamento já em andamento"})

    # Verificar se há imagens para processar
    if not os.path.exists(DIRETORIO_IMAGENS):
        return jsonify({"success": False, "message": "Pasta de imagens não encontrada"})

    # Tentar extrair arquivos comprimidos antes de verificar imagens
    try:
        resultado_extracao = extrair_arquivos_comprimidos(DIRETORIO_IMAGENS)
        if resultado_extracao["arquivos_extraidos"] > 0:
            print(f"✅ Extraídos {resultado_extracao['arquivos_extraidos']} arquivos comprimidos")
    except Exception as e:
        # Se houver erro na extração, continuar com o processamento normal
        print(f"Aviso: Erro na extração de arquivos: {e}")

    imagens = [
        f for f in os.listdir(DIRETORIO_IMAGENS) if f.lower().endswith(EXTENSOES_IMAGEM)
    ]
    if not imagens:
        return jsonify(
            {"success": False, "message": "Nenhuma imagem encontrada para processar"}
        )

    # Iniciar processamento em background
    thread = threading.Thread(target=processar_em_background)
    thread.start()

    return jsonify({"success": True, "message": "Processamento iniciado!"})


@app.route("/cancelar", methods=["POST"])
def cancelar_processamento():
    """Cancela o processamento em andamento."""
    global processamento_cancelado, progresso_atual
    
    if not processamento_ativo:
        return jsonify({"success": False, "message": "Nenhum processamento em andamento"})
    
    processamento_cancelado = True
    progresso_atual["logs"].append("⚠️ Solicitação de cancelamento recebida...")
    progresso_atual["status"] = "⚠️ Cancelando processamento..."
    
    # Criar arquivo de sinalização para o script extrair-dados.py
    try:
        cancel_file = os.path.join(BASE_PATH, ".cancel_processing")
        with open(cancel_file, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        print(f"Erro ao criar arquivo de cancelamento: {e}")
    
    return jsonify({"success": True, "message": "Processamento cancelado!"})


@app.route("/status")
def obter_status():
    """Obtém o status atual do processamento."""
    # Adicionar informações extras ao progresso
    status_completo = progresso_atual.copy()

    # Adicionar contagem de imagens
    if os.path.exists(DIRETORIO_IMAGENS):
        imagens = [
            f
            for f in os.listdir(DIRETORIO_IMAGENS)
            if f.lower().endswith(EXTENSOES_IMAGEM)
        ]
        status_completo["total_imagens"] = len(imagens)
    else:
        status_completo["total_imagens"] = 0

    return jsonify(status_completo)


@app.route("/logs")
@app.route("/visualizar_logs")
def visualizar_logs():
    """Página de visualização de logs em tempo real."""
    return render_template("logs.html")


@app.route("/api/logs")
def api_logs():
    """API para obter logs em tempo real."""
    try:
        config = carregar_configuracao()
        logs_detalhados = config.get("interface", {}).get("logs_detalhados_aplicacao", False)
        logs = []

        # Se logs detalhados estiver ativo, retornar logs da aplicação
        if logs_detalhados and logs_aplicacao_buffer:
            logs.extend(logs_aplicacao_buffer[-100:])
        else:
            # Modo padrão - logs simplificados
            # Ler log de processamento
            if os.path.exists(LOG_PROCESSADOS_FILE):
                with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
                    linhas = f.readlines()
                    logs.extend(
                        [
                            {
                                "tipo": "processado",
                                "timestamp": datetime.now().strftime("%H:%M:%S"),
                                "mensagem": linha.strip(),
                            }
                            for linha in linhas[-20:]
                            if linha.strip()
                        ]
                    )  # Últimas 20 linhas

            # Ler log de consumo
            if os.path.exists(LOG_CONSUMO_FILE):
                with open(LOG_CONSUMO_FILE, "r", encoding="utf-8") as f:
                    linhas = f.readlines()
                    for linha in linhas[-10:]:  # Últimas 10 linhas
                        if linha.strip():
                            logs.append(
                                {
                                    "tipo": "consumo",
                                    "timestamp": (
                                        linha[:19]
                                        if len(linha) > 19
                                        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    ),
                                    "mensagem": linha.strip(),
                                }
                            )

            # Adicionar logs do progresso atual
            for log_msg in progresso_atual.get("logs", []):
                logs.append(
                    {
                        "tipo": "progresso",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "mensagem": log_msg,
                    }
                )

        return jsonify(
            {
                "logs": logs[-100:],  # Últimos 100 logs
                "processamento_ativo": processamento_ativo,
                "progresso": progresso_atual,
                "logs_detalhados": logs_detalhados,
            }
        )

    except Exception as e:
        return jsonify(
            {
                "logs": [
                    {
                        "tipo": "erro",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "mensagem": f"Erro ao ler logs: {str(e)}",
                    }
                ],
                "processamento_ativo": processamento_ativo,
                "progresso": progresso_atual,
            }
        )


@app.route("/relatorio")
@app.route("/visualizar_relatorio")
def visualizar_relatorio():
    """Página de visualização do relatório."""
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

        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
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

        return render_template("relatorio.html", dados=dados)

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
            sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
            
            # Criar arquivo filtrado
            xlsx_filename = f'Relatorio_Avarias_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
            xlsx_path = os.path.join(BASE_PATH, "resultados", f"temp_{xlsx_filename}")
            
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                for secao in secoes_selecionadas:
                    if secao in sheets:
                        df = sheets[secao]
                        colunas = colunas_por_secao.get(secao, [])
                        if colunas:
                            # Filtrar colunas existentes
                            colunas_existentes = [col for col in colunas if col in df.columns]
                            if colunas_existentes:
                                df_filtrado = df[colunas_existentes]
                                df_filtrado.to_excel(writer, sheet_name=secao, index=False)
            
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
        
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
        
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
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
        
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
        
        with open(txt_path, "w", encoding="utf-8") as f:
            # Cabeçalho do relatório
            f.write("="*80 + "\n")
            f.write("RELATÓRIO COMPLETO DE ANÁLISE DE PRODUTOS\n")
            f.write(f"Data de Geração: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
            
            # Processar cada sheet na ordem
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
            
            for sheet_name in sheet_order:
                df = sheets[sheet_name]
                
                if df is None or df.empty:
                    continue
                
                # Aplicar filtro de colunas se fornecido
                if colunas_por_secao_filtradas and sheet_name in colunas_por_secao_filtradas:
                    colunas = colunas_por_secao_filtradas[sheet_name]
                    colunas_existentes = [col for col in colunas if col in df.columns]
                    if colunas_existentes:
                        df = df[colunas_existentes]
                    else:
                        continue  # Pular se nenhuma coluna válida
                
                # Título da seção
                f.write("\n" + "="*80 + "\n")
                f.write(f"{sheet_name.upper()}\n")
                f.write("="*80 + "\n\n")
                f.write(f"Total de registros: {len(df)}\n")
                f.write("-"*80 + "\n\n")
                
                # Processar cada linha
                for idx, row in df.iterrows():
                    f.write(f"Registro #{idx + 1}:\n")
                    f.write("-"*40 + "\n")
                    
                    # Escrever cada coluna com seu valor
                    for col in df.columns:
                        valor = row[col]
                        # Tratar valores NaN
                        if pd.isna(valor) or valor == "" or str(valor).lower() == "nan":
                            valor = "-"
                        
                        # Formatação especial para observações longas
                        if "observ" in col.lower() or "detalhes" in col.lower():
                            f.write(f"\n{col}:\n")
                            f.write(f"  {str(valor)}\n")
                        else:
                            f.write(f"{col}: {str(valor)}\n")
                    
                    f.write("\n")
                
            # Rodapé
            f.write("\n" + "="*80 + "\n")
            f.write("FIM DO RELATÓRIO\n")
            f.write("="*80 + "\n")
        
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


@app.route("/api/obter_erros_pendentes")
def obter_erros_pendentes():
    """API para obter quantidade de erros pendentes."""
    try:
        from src.gerenciador_erros import criar_gerenciador
        
        gerenciador = criar_gerenciador(ARQUIVO_SAIDA_EXCEL)
        resumo = gerenciador.gerar_resumo_erros()
        
        return jsonify({
            "success": True,
            "total": resumo["total"],
            "tipos": resumo["tipos"],
            "arquivos": resumo["arquivos"]
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/reanalisar_erros", methods=["POST"])
def reanalisar_erros_api():
    """API para iniciar reanálise de erros."""
    global processamento_ativo, progresso_atual
    
    try:
        # Verificar se já há processamento ativo
        if processamento_ativo:
            return jsonify({
                "success": False,
                "message": "Já existe um processamento em andamento"
            }), 400
        
        from src.gerenciador_erros import criar_gerenciador
        
        # Verificar se há erros para reanalisar
        gerenciador = criar_gerenciador(ARQUIVO_SAIDA_EXCEL)
        total_erros = gerenciador.contar_erros_pendentes()
        
        if total_erros == 0:
            return jsonify({
                "success": True,
                "message": "Nenhum erro pendente para reanalisar",
                "resultado": {
                    "total_arquivos": 0,
                    "corrigidos": 0,
                    "ainda_com_erro": 0
                }
            })
        
        # Marcar processamento como ativo
        processamento_ativo = True
        progresso_atual = {
            "progresso": 0,
            "status": "Iniciando reanálise de erros",
            "logs": [f"🔄 Iniciando reanálise de {total_erros} itens com erro"]
        }
        
        # Função de callback para atualizar progresso
        def callback_progresso(info):
            global progresso_atual
            progresso = int((info["atual"] / info["total"]) * 100)
            progresso_atual["progresso"] = progresso
            progresso_atual["status"] = f"Reanalisando: {info['arquivo']}"
            progresso_atual["logs"].append(
                f"[{info['atual']}/{info['total']}] {info['arquivo']}"
            )
        
        # Executar reanálise em thread separada
        def executar_reanalise():
            global processamento_ativo, progresso_atual
            try:
                # Importar módulo com hífen no nome
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "extrair_dados", 
                    os.path.join(BASE_PATH, "src", "extrair-dados.py")
                )
                extrair_dados = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(extrair_dados)
                reanalisar_erros = extrair_dados.reanalisar_erros
                
                resultado = reanalisar_erros(
                    diretorio_imagens=DIRETORIO_IMAGENS,
                    arquivo_excel=ARQUIVO_SAIDA_EXCEL,
                    callback_progresso=callback_progresso
                )
                
                progresso_atual["progresso"] = 100
                progresso_atual["status"] = "Reanálise concluída"
                progresso_atual["resultado"] = resultado
                progresso_atual["logs"].append(
                    f"✅ Reanálise concluída: {resultado.get('corrigidos', 0)} corrigidos, "
                    f"{resultado.get('ainda_com_erro', 0)} ainda com erro"
                )
                
            except Exception as e:
                progresso_atual["status"] = f"Erro na reanálise: {str(e)}"
                progresso_atual["logs"].append(f"❌ Erro: {str(e)}")
                progresso_atual["erro"] = str(e)
            finally:
                processamento_ativo = False
        
        # Iniciar thread
        thread = threading.Thread(target=executar_reanalise, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "message": f"Reanálise iniciada para {total_erros} itens",
            "total_erros": total_erros
        })
        
    except Exception as e:
        processamento_ativo = False
        return jsonify({
            "success": False,
            "message": f"Erro ao iniciar reanálise: {str(e)}"
        }), 500


@app.route("/api/progresso_reanalise")
def progresso_reanalise():
    """API para obter progresso da reanálise."""
    global progresso_atual, processamento_ativo
    
    return jsonify({
        "ativo": processamento_ativo,
        "progresso": progresso_atual.get("progresso", 0),
        "status": progresso_atual.get("status", "Aguardando"),
        "logs": progresso_atual.get("logs", []),
        "resultado": progresso_atual.get("resultado"),
        "erro": progresso_atual.get("erro")
    })


@app.route("/api/provedores_disponiveis")
def provedores_disponiveis():
    """API para listar provedores de IA disponíveis."""
    try:
        from src.ai_providers import AIProviderFactory
        
        provedores = AIProviderFactory.listar_provedores()
        return jsonify({
            "success": True,
            "provedores": provedores
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/modelos_disponiveis/<provider>")
def modelos_disponiveis(provider):
    """API para listar modelos disponíveis de um provedor."""
    try:
        from src.ai_providers import AIProviderFactory
        
        modelos = AIProviderFactory.obter_modelos(provider)
        return jsonify({
            "success": True,
            "modelos": modelos,
            "provider": provider
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/configuracoes")
def configuracoes():
    """Página de configurações."""
    config = carregar_configuracao()
    stats = obter_estatisticas()

    # Avisar sobre limitações na Vercel
    if "VERCEL" in os.environ:
        config["_vercel_env"] = True

    return render_template("configuracoes.html", config=config, stats=stats)


@app.route("/salvar_configuracao", methods=["POST"])
def salvar_configuracao_route():
    """Salva as configurações do usuário."""
    try:
        data = request.json
        config = carregar_configuracao()

        # Atualizar configurações da API
        if "api" in data:
            for key, value in data["api"].items():
                config["api"][key] = value
            
            # Se um modelo específico foi selecionado, salvar nas configurações de processamento
            if "modelo_selecionado" in data["api"]:
                provider = data["api"].get("provider", "gemini")
                modelo_key = f"modelo_{provider}"
                if "processamento" not in config:
                    config["processamento"] = {}
                config["processamento"][modelo_key] = data["api"]["modelo_selecionado"]
        
        # Atualizar configurações de processamento
        if "processamento" in data:
            if "processamento" not in config:
                config["processamento"] = {}
            for key, value in data["processamento"].items():
                config["processamento"][key] = value
        
        # Atualizar configurações de interface
        if "interface" in data:
            if "interface" not in config:
                config["interface"] = {}
            config["interface"].update(data["interface"])

        # No ambiente Vercel, apenas simular salvamento
        if "VERCEL" in os.environ:
            return jsonify(
                {
                    "success": True,
                    "message": "No ambiente Vercel, use variáveis de ambiente para configurações",
                }
            )

        if salvar_configuracao(config):
            return jsonify(
                {"success": True, "message": "Configurações salvas com sucesso!"}
            )
        else:
            return jsonify(
                {"success": False, "message": "Erro ao salvar configurações"}
            )

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro: {str(e)}"})


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
        sheets = pd.read_excel(arquivo_encontrado, sheet_name=None, engine="openpyxl")
        
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
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")

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
        print(f"📊 Valor original: {original_value} -> Novo valor: {novo_valor}")

        # Atualizar valor
        df.at[linha_id, campo] = novo_valor
        sheets[sheet_name] = df

        # Criar backup antes de salvar
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)

        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)

        print(f"✅ Edição salva com sucesso!")
        return jsonify(
            {"success": True, "message": f'Campo "{campo}" atualizado com sucesso!'}
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
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")

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
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)

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
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)

        print(
            f"✅ Edição completa salva com sucesso! Campos atualizados: {', '.join(campos_atualizados)}"
        )
        return jsonify(
            {
                "success": True,
                "message": f"Linha atualizada com sucesso! ({len(campos_atualizados)} campos alterados)",
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
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")

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
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)

        # Remover linha
        df = df.drop(df.index[linha_id]).reset_index(drop=True)
        sheets[sheet_name] = df

        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)

        print(f"✅ Linha excluída com sucesso!")
        return jsonify({"success": True, "message": "Linha excluída com sucesso!"})

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
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")

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
                    "Detalhes",
                    "Observação da Mensagem",
                    "Caminho da Imagem",
                    "Ver Imagem",
                ]
            elif sheet_destino == "Uso Interno":
                colunas_destino = [
                    "Produto",
                    "Detalhes",
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
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)

        # Adaptar dados para a planilha de destino
        nova_linha = {}

        if sheet_destino == "Avarias":
            nova_linha = {
                "Produto": linha_dados.get(
                    "Produto", linha_dados.get("Arquivo", "N/A")
                ),
                "Detalhes": linha_dados.get(
                    "Detalhes",
                    linha_dados.get("Detalhes do Erro", "Movido de outra planilha"),
                ),
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
                "Detalhes": linha_dados.get(
                    "Detalhes",
                    linha_dados.get("Detalhes do Erro", "Movido de outra planilha"),
                ),
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
                    "Detalhes do Erro",
                    linha_dados.get("Detalhes", "Movido de outra planilha"),
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

        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
            for nome_sheet, dataframe in sheets.items():
                if not dataframe.empty:  # Só salvar planilhas não vazias
                    dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)

        produto_nome = nova_linha.get("Produto", nova_linha.get("Arquivo", "Item"))
        print(
            f"✅ Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!"
        )

        return jsonify(
            {
                "success": True,
                "message": f"Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!",
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
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")

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
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)

        # Adicionar nova linha
        df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
        sheets[sheet_name] = df

        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)

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


@app.route("/backup_relatorio")
def backup_relatorio():
    """Cria backup do relatório atual."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({"success": False, "message": "Nenhum relatório encontrado"})

        # Criar nome do backup com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_nome = f"Relatorio_Backup_{timestamp}.xlsx"
        backup_path = os.path.join("resultados", backup_nome)

        # Copiar arquivo
        shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_path)

        return jsonify(
            {
                "success": True,
                "message": f"Backup criado: {backup_nome}",
                "backup_file": backup_nome,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao criar backup: {str(e)}"})


@app.route("/download_backup/<filename>")
def download_backup(filename):
    """Download de arquivo de backup."""
    try:
        backup_path = os.path.join("resultados", filename)
        if not os.path.exists(backup_path):
            flash("Backup não encontrado", "warning")
            return redirect(url_for("configuracoes"))

        return send_file(backup_path, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"Erro no download: {str(e)}", "danger")
        return redirect(url_for("configuracoes"))


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
            message = "Logs limpos com sucesso!"

        elif tipo == "relatorio":
            if os.path.exists(ARQUIVO_SAIDA_EXCEL):
                os.remove(ARQUIVO_SAIDA_EXCEL)
            message = "Relatório removido com sucesso!"

        elif tipo == "imagens":
            if os.path.exists(DIRETORIO_IMAGENS):
                for arquivo in os.listdir(DIRETORIO_IMAGENS):
                    arquivo_path = os.path.join(DIRETORIO_IMAGENS, arquivo)
                    if os.path.isfile(arquivo_path):
                        os.remove(arquivo_path)
            message = "Imagens removidas com sucesso!"

        else:
            return jsonify({"success": False, "message": "Tipo de limpeza inválido"})

        return jsonify({"success": True, "message": message})

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro: {str(e)}"})


@app.route("/download_config")
def download_config():
    """Download das configurações como backup"""
    try:
        if not os.path.exists(CONFIG_FILE):
            flash("Arquivo de configuração não encontrado.", "warning")
            return redirect(url_for("configuracoes"))

        return send_file(
            CONFIG_FILE, as_attachment=True, download_name="config_backup.json"
        )
    except Exception as e:
        flash(f"Erro ao fazer download: {str(e)}", "error")
        return redirect(url_for("configuracoes"))


@app.route("/api/stats")
def api_stats():
    """API para obter estatísticas atualizadas."""
    return jsonify(obter_estatisticas())


@app.route("/verificar_relatorio")
def verificar_relatorio():
    """Verifica se o relatório existe e tem dados."""
    try:
        # Verificar múltiplos caminhos
        caminhos_possiveis = [
            ARQUIVO_SAIDA_EXCEL,
            os.path.join(os.getcwd(), "resultados", "Relatorio_Mestre_Produtos.xlsx"),
            "./resultados/Relatorio_Mestre_Produtos.xlsx"
        ]
        
        info = {
            "arquivo_principal": ARQUIVO_SAIDA_EXCEL,
            "arquivos_verificados": [],
            "arquivo_encontrado": None,
            "planilhas": {},
            "total_registros": 0
        }
        
        for caminho in caminhos_possiveis:
            status = {
                "caminho": caminho,
                "existe": os.path.exists(caminho),
                "tamanho": 0
            }
            
            if os.path.exists(caminho):
                status["tamanho"] = os.path.getsize(caminho)
                if not info["arquivo_encontrado"]:
                    info["arquivo_encontrado"] = caminho
            
            info["arquivos_verificados"].append(status)
        
        if info["arquivo_encontrado"]:
            try:
                sheets = pd.read_excel(info["arquivo_encontrado"], sheet_name=None, engine="openpyxl")
                for sheet_name, df in sheets.items():
                    if df is not None and not df.empty:
                        info["planilhas"][sheet_name] = len(df)
                        info["total_registros"] += len(df)
                
                info["sucesso"] = True
                info["mensagem"] = f"Relatório encontrado com {info['total_registros']} registros"
            
            except Exception as e:
                info["erro"] = f"Erro ao ler arquivo: {str(e)}"
                info["sucesso"] = False
        else:
            info["sucesso"] = False
            info["mensagem"] = "Nenhum arquivo de relatório encontrado"
        
        return jsonify(info)
        
    except Exception as e:
        return jsonify({"erro": str(e), "sucesso": False}), 500


@app.route("/debug_editar_dados")
def debug_editar_dados():
    """Rota de debug para testar carregamento de dados para edição."""
    try:
        resultado = {
            "arquivo_excel": ARQUIVO_SAIDA_EXCEL,
            "arquivo_existe": os.path.exists(ARQUIVO_SAIDA_EXCEL),
            "base_path": BASE_PATH,
            "cwd": os.getcwd()
        }
        
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            try:
                sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
                resultado["planilhas"] = {}
                
                for sheet_name, df in sheets.items():
                    resultado["planilhas"][sheet_name] = {
                        "total_linhas": len(df),
                        "colunas": list(df.columns),
                        "vazia": df.empty,
                        "primeiras_linhas": df.head(3).to_dict('records') if not df.empty else []
                    }
                
                resultado["sucesso"] = True
                resultado["total_planilhas"] = len(sheets)
                
            except Exception as e:
                resultado["erro_leitura"] = str(e)
                resultado["sucesso"] = False
        else:
            resultado["erro"] = "Arquivo não encontrado"
            resultado["sucesso"] = False
        
        return f"""
        <html>
        <head><title>Debug Editar Dados</title></head>
        <body>
        <h1>Debug - Editar Dados</h1>
        <pre>{json.dumps(resultado, indent=2, ensure_ascii=False)}</pre>
        <hr>
        <a href="/editar_dados">Tentar Editar Dados</a> | 
        <a href="/">Voltar ao Início</a>
        </body>
        </html>
        """
        
    except Exception as e:
        return f"<h1>Erro no Debug</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>"


@app.route("/api/debug_relatorio")
def debug_relatorio():
    """API para debugar problemas com o relatório."""
    try:
        debug_info = {
            "arquivo_excel": {
                "caminho": ARQUIVO_SAIDA_EXCEL,
                "existe": os.path.exists(ARQUIVO_SAIDA_EXCEL),
                "tamanho": os.path.getsize(ARQUIVO_SAIDA_EXCEL) if os.path.exists(ARQUIVO_SAIDA_EXCEL) else 0
            },
            "base_path": BASE_PATH,
            "working_directory": os.getcwd(),
            "sheets": {}
        }
        
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            try:
                sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
                debug_info["leitura_excel"] = "Sucesso"
                
                for sheet_name, df in sheets.items():
                    debug_info["sheets"][sheet_name] = {
                        "linhas": len(df),
                        "colunas": list(df.columns),
                        "vazio": df.empty
                    }
            except Exception as e:
                debug_info["leitura_excel"] = f"Erro: {str(e)}"
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# =============================================================================
# FUNCIONALIDADE DE UNIFICAÇÃO DE RELATÓRIOS
# =============================================================================

def normalizar_texto(texto):
    """Normaliza texto para comparação (remove acentos, maiúsculas, espaços extras)."""
    import unicodedata
    if pd.isna(texto) or texto == "" or texto == "-":
        return ""
    texto = str(texto).strip().lower()
    # Remover acentos
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(char for char in texto if unicodedata.category(char) != 'Mn')
    return texto


def extrair_quantidade_unidade(texto):
    """Extrai quantidade numérica e unidade de uma string.
    
    Exemplos:
        "2 kg" -> (2.0, "kg")
        "1,5 kg" -> (1.5, "kg")
        "3.5kg" -> (3.5, "kg")
        "500g" -> (500.0, "g")
        "2 unidades" -> (2.0, "unidades")
    """
    import re
    
    if pd.isna(texto) or texto == "" or texto == "-":
        return None, None
    
    texto = str(texto).strip()
    
    # Padrões para capturar número + unidade
    # Suporta: "2 kg", "2,5 kg", "2.5 kg", "2kg", etc.
    padroes = [
        r'([\d]+[,.]?[\d]*)\s*(kg|g|l|ml|unidade|unidades|un|und|caixa|caixas|pacote|pacotes|lata|latas)',
        r'([\d]+[,.]?[\d]*)\s*([a-zA-Z]+)',
    ]
    
    for padrao in padroes:
        match = re.search(padrao, texto.lower())
        if match:
            try:
                quantidade_str = match.group(1).replace(',', '.')
                quantidade = float(quantidade_str)
                unidade = match.group(2).strip()
                return quantidade, unidade
            except:
                continue
    
    return None, None


def extrair_peso_de_detalhes(detalhes):
    """Extrai valor numérico de peso do campo 'Detalhes' para AVARIAS.
    
    Regras:
    - Se contém 'Peso:', extrair o valor numérico
    - Tratar vírgulas como separadores de milhares: 1,500 -> 1.500
    - Se peso for 'N/A' ou inexistente, retornar None
    
    Args:
        detalhes: String com detalhes (ex: "Peso: 1,5 kg | Marca: XYZ")
        
    Returns:
        float ou None: Valor numérico do peso ou None se não encontrado
    """
    import re
    
    if pd.isna(detalhes) or detalhes == "" or detalhes == "-":
        return None
    
    detalhes_str = str(detalhes).strip()
    
    # Verificar se contém 'Peso' (case insensitive)
    if 'peso' not in detalhes_str.lower():
        return None
    
    # Verificar se é N/A
    if 'n/a' in detalhes_str.lower():
        return None
    
    # Padrão para extrair peso: "Peso: 1,5 kg" ou "Peso: 1.5 kg" ou "Peso: 1,500 kg"
    # Primeiro: tentar padrão com vírgula como decimal
    padrao_decimal = r'peso\s*:\s*([\d]+,[\d]+)\s*(?:kg|g)?'
    match = re.search(padrao_decimal, detalhes_str.lower())
    if match:
        try:
            # Substituir vírgula por ponto para conversão
            peso_str = match.group(1).replace(',', '.')
            return float(peso_str)
        except:
            pass
    
    # Segundo: tentar padrão com ponto como decimal ou vírgula como separador de milhares
    padrao_ponto = r'peso\s*:\s*([\d]+[.,]?[\d]*)\s*(?:kg|g)?'
    match = re.search(padrao_ponto, detalhes_str.lower())
    if match:
        try:
            peso_str = match.group(1).replace(',', '.')
            return float(peso_str)
        except:
            pass
    
    return None


def extrair_quantidade_de_observacao(observacao):
    """Extrai quantidade numérica do campo 'Observação da Mensagem' para USO INTERNO.
    
    Regras:
    - Se houver números (ex: "2" ou "46 unid"), extrair e somar
    - Se for "Nenhuma", retornar 1
    - Se não houver números, retornar 1
    
    Args:
        observacao: String com observação da mensagem
        
    Returns:
        float: Quantidade extraída (default: 1)
    """
    import re
    
    if pd.isna(observacao) or observacao == "" or observacao == "-":
        return 1.0
    
    observacao_str = str(observacao).strip()
    
    # Se for "Nenhuma", retornar 1
    if observacao_str.lower() == "nenhuma":
        return 1.0
    
    # Procurar por números na observação
    # Padrões: "2", "46", "46 unid", "46 unidades", etc.
    padrao = r'(\d+)(?:\s*(?:unid|unidade|unidades|un|und))?'
    matches = re.findall(padrao, observacao_str.lower())
    
    if matches:
        # Somar todos os números encontrados
        total = sum(float(m) for m in matches)
        return total
    
    # Se não encontrou números, retornar 1
    return 1.0


def extrair_codigo_barras_de_detalhes(detalhes):
    """Extrai código de barras do campo 'Detalhes' para USO INTERNO.
    
    Args:
        detalhes: String com detalhes (ex: "Marca: XYZ | Cód. Barras: 123456")
        
    Returns:
        str: Código de barras ou "N/A" se não encontrado
    """
    import re
    
    if pd.isna(detalhes) or detalhes == "" or detalhes == "-":
        return "N/A"
    
    detalhes_str = str(detalhes).strip()
    
    # Verificar se contém 'Cód. Barras' ou 'Codigo Barras'
    if 'barras' not in detalhes_str.lower():
        return "N/A"
    
    # Padrão para extrair código: "Cód. Barras: 123456" ou "Codigo Barras: 123456"
    padrao = r'c[oó]d\.?\s*barras\s*:\s*([\d]+)'
    match = re.search(padrao, detalhes_str.lower())
    
    if match:
        return match.group(1)
    
    return "N/A"


def unificar_itens_avarias(df):
    """Unifica itens de AVARIAS agrupando por Produto e somando pesos.
    
    Regras:
    - Chave de Agrupamento: Nome do Produto (normalizado)
    - Se 'Detalhes' contém 'Peso', extrair valor numérico e somar
    - Se peso for 'N/A' ou inexistente, contar como 1 unidade
    - Saída: NOME DO PRODUTO | QUANTIDADE TOTAL (kg ou un)
    
    Args:
        df: DataFrame com dados de AVARIAS
        
    Returns:
        tuple: (df_unificado, auditoria_dict)
    """
    if df.empty:
        return df.copy(), {}
    
    # Verificar colunas necessárias
    if "Produto" not in df.columns or "Detalhes" not in df.columns:
        return df.copy(), {}
    
    # Estrutura para armazenar agrupamentos
    # {produto_normalizado: {"produto_original": str, "quantidade_kg": float, "quantidade_un": int, "registros": [...]}}
    grupos = {}
    
    for idx, row in df.iterrows():
        produto = row.get("Produto", "")
        detalhes = row.get("Detalhes", "")
        
        # Normalizar produto para agrupamento
        produto_norm = normalizar_texto(produto)
        
        if not produto_norm:
            continue
        
        # Extrair peso dos detalhes
        peso = extrair_peso_de_detalhes(detalhes)
        
        # Inicializar grupo se não existir
        if produto_norm not in grupos:
            grupos[produto_norm] = {
                "produto_original": produto.strip().upper(),  # Converter para maiúsculas
                "quantidade_kg": 0.0,
                "quantidade_un": 0,
                "registros": []
            }
        
        # Adicionar quantidade ao grupo
        if peso is not None and peso > 0:
            grupos[produto_norm]["quantidade_kg"] += peso
        else:
            grupos[produto_norm]["quantidade_un"] += 1
        
        grupos[produto_norm]["registros"].append({
            "index": idx,
            "registro_completo": row.to_dict(),
            "peso_extraido": peso
        })
    
    # Criar DataFrame unificado
    registros_unificados = []
    auditoria = {}
    
    # Ordenar por nome do produto (alfabética)
    for produto_norm in sorted(grupos.keys()):
        info = grupos[produto_norm]
        
        # Pegar o primeiro registro como base
        registro_base = info["registros"][0]["registro_completo"].copy()
        
        # Determinar quantidade final
        if info["quantidade_kg"] > 0:
            # Formatar peso em kg
            quantidade_formatada = f"{info['quantidade_kg']:.3f} kg".replace('.', ',')
        else:
            # Usar unidades
            quantidade_formatada = f"{info['quantidade_un']} un"
        
        # Atualizar registro
        registro_base["Produto"] = info["produto_original"]
        registro_base["Quantidade Total"] = quantidade_formatada
        registro_base["Qtd_Registros_Consolidados"] = len(info["registros"])
        
        registros_unificados.append(registro_base)
        
        # Guardar auditoria
        chave_auditoria = f"{info['produto_original']} ({quantidade_formatada})"
        auditoria[chave_auditoria] = info["registros"]
    
    # Criar DataFrame unificado
    if registros_unificados:
        df_unificado = pd.DataFrame(registros_unificados)
        # Reorganizar colunas: Produto, Quantidade Total, outras colunas
        colunas = ["Produto", "Quantidade Total"]
        colunas += [c for c in df_unificado.columns if c not in colunas]
        df_unificado = df_unificado[colunas]
    else:
        df_unificado = df.copy()
    
    return df_unificado, auditoria


def unificar_itens_uso_interno(df):
    """Unifica itens de USO INTERNO agrupando por Produto + Código de Barras e somando quantidades.
    
    Regras:
    - Chave de Agrupamento: Nome do Produto + Código de Barras
    - Analisar 'Observação da Mensagem' para extrair quantidades
    - Se observação for "Nenhuma", contar como 1
    - Saída: NOME DO PRODUTO | QUANTIDADE TOTAL | CÓDIGO DE BARRAS
    
    Args:
        df: DataFrame com dados de USO INTERNO
        
    Returns:
        tuple: (df_unificado, auditoria_dict)
    """
    if df.empty:
        return df.copy(), {}
    
    # Verificar colunas necessárias
    if "Produto" not in df.columns or "Detalhes" not in df.columns or "Observação da Mensagem" not in df.columns:
        return df.copy(), {}
    
    # Estrutura para armazenar agrupamentos
    # {(produto_normalizado, codigo_barras): {"produto_original": str, "codigo_barras": str, "quantidade_total": float, "registros": [...]}}
    grupos = {}
    
    for idx, row in df.iterrows():
        produto = row.get("Produto", "")
        detalhes = row.get("Detalhes", "")
        observacao = row.get("Observação da Mensagem", "")
        
        # Normalizar produto para agrupamento
        produto_norm = normalizar_texto(produto)
        
        if not produto_norm:
            continue
        
        # Extrair código de barras
        codigo_barras = extrair_codigo_barras_de_detalhes(detalhes)
        
        # Extrair quantidade da observação
        quantidade = extrair_quantidade_de_observacao(observacao)
        
        # Criar chave do grupo
        chave = (produto_norm, codigo_barras)
        
        # Inicializar grupo se não existir
        if chave not in grupos:
            grupos[chave] = {
                "produto_original": produto.strip().upper(),  # Converter para maiúsculas
                "codigo_barras": codigo_barras,
                "quantidade_total": 0.0,
                "registros": []
            }
        
        # Adicionar quantidade ao grupo
        grupos[chave]["quantidade_total"] += quantidade
        
        grupos[chave]["registros"].append({
            "index": idx,
            "registro_completo": row.to_dict(),
            "quantidade_extraida": quantidade
        })
    
    # Criar DataFrame unificado
    registros_unificados = []
    auditoria = {}
    
    # Ordenar por nome do produto (alfabética)
    chaves_ordenadas = sorted(grupos.keys(), key=lambda x: x[0])
    
    for chave in chaves_ordenadas:
        info = grupos[chave]
        
        # Pegar o primeiro registro como base
        registro_base = info["registros"][0]["registro_completo"].copy()
        
        # Formatar quantidade
        quantidade_total = info["quantidade_total"]
        if quantidade_total == int(quantidade_total):
            quantidade_formatada = str(int(quantidade_total))
        else:
            quantidade_formatada = f"{quantidade_total:.2f}".replace('.', ',')
        
        # Atualizar registro
        registro_base["Produto"] = info["produto_original"]
        registro_base["Quantidade Total"] = quantidade_formatada
        registro_base["Código de Barras"] = info["codigo_barras"]
        registro_base["Qtd_Registros_Consolidados"] = len(info["registros"])
        
        registros_unificados.append(registro_base)
        
        # Guardar auditoria
        chave_auditoria = f"{info['produto_original']} - {info['codigo_barras']} ({quantidade_formatada})"
        auditoria[chave_auditoria] = info["registros"]
    
    # Criar DataFrame unificado
    if registros_unificados:
        df_unificado = pd.DataFrame(registros_unificados)
        # Reorganizar colunas: Produto, Quantidade Total, Código de Barras, outras colunas
        colunas = ["Produto", "Quantidade Total", "Código de Barras"]
        colunas += [c for c in df_unificado.columns if c not in colunas]
        df_unificado = df_unificado[colunas]
    else:
        df_unificado = df.copy()
    
    return df_unificado, auditoria


def processar_unificacao_completa(secoes_filtro=None, colunas_filtro=None):
    """Processa todo o relatório aplicando unificação e gerando planilha de auditoria.
    
    Args:
        secoes_filtro: Lista de seções para processar (None = todas)
        colunas_filtro: Dicionário {secao: [colunas]} para filtrar colunas (None = todas)
    
    Returns:
        tuple: (sucesso, mensagem, caminho_arquivo_gerado)
    """
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return False, "Relatório original não encontrado", None
        
        # Ler arquivo Excel original
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
        
        # Preparar arquivo de saída
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_unificado = os.path.join(
            BASE_PATH, 
            "resultados", 
            f"Relatorio_Unificado_{timestamp}.xlsx"
        )
        
        # Criar writer para o arquivo unificado
        with pd.ExcelWriter(arquivo_unificado, engine="openpyxl") as writer:
            
            # Processar cada sheet
            for sheet_name, df in sheets.items():
                
                # Verificar se a seção deve ser processada
                if secoes_filtro and sheet_name not in secoes_filtro:
                    continue
                
                if df.empty:
                    # Sheet vazia, copiar como está
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    continue
                
                # Identificar se é uma sheet que deve ser unificada
                # (Avarias ou Uso Interno)
                deve_unificar = False
                coluna_produto = None
                coluna_quantidade = None
                
                # Detectar tipo de sheet e colunas relevantes
                sheet_lower = sheet_name.lower()
                if "avaria" in sheet_lower or "uso interno" in sheet_lower:
                    deve_unificar = True
                    
                    # Tentar encontrar colunas de produto e quantidade
                    colunas = df.columns.tolist()
                    
                    for col in colunas:
                        col_lower = col.lower()
                        if "produto" in col_lower or "item" in col_lower or "descrição" in col_lower or "descricao" in col_lower:
                            coluna_produto = col
                        if "quantidade" in col_lower or "qtd" in col_lower or "peso" in col_lower:
                            coluna_quantidade = col
                
                if deve_unificar and coluna_produto:
                    # Determinar tipo de sheet e aplicar unificação apropriada
                    if "avaria" in sheet_lower:
                        # Processar AVARIAS
                        df_unificado, auditoria = unificar_itens_avarias(df)
                        tipo_processamento = "AVARIAS"
                    elif "uso interno" in sheet_lower:
                        # Processar USO INTERNO
                        df_unificado, auditoria = unificar_itens_uso_interno(df)
                        tipo_processamento = "USO INTERNO"
                    else:
                        # Fallback: não processar
                        df_unificado = df.copy()
                        auditoria = {}
                        tipo_processamento = "OUTRO"
                    
                    # Aplicar filtro de colunas se fornecido
                    if colunas_filtro and sheet_name in colunas_filtro:
                        colunas_selecionadas = colunas_filtro[sheet_name]
                        colunas_existentes = [col for col in colunas_selecionadas if col in df_unificado.columns]
                        if colunas_existentes:
                            df_unificado = df_unificado[colunas_existentes]
                    
                    # Salvar SOMENTE a sheet unificada
                    df_unificado.to_excel(writer, sheet_name=sheet_name, index=False)
                    
                else:
                    # Sheet não unificável
                    # Aplicar filtro de colunas se fornecido
                    if colunas_filtro and sheet_name in colunas_filtro:
                        colunas_selecionadas = colunas_filtro[sheet_name]
                        colunas_existentes = [col for col in colunas_selecionadas if col in df.columns]
                        if colunas_existentes:
                            df = df[colunas_existentes]
                    
                    # Copiar como está
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        
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
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return False, "Relatório original não encontrado", None
        
        # Ler arquivo Excel original
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
        
        # Preparar arquivo de saída
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_unificado = os.path.join(
            BASE_PATH, 
            "resultados", 
            f"Relatorio_Unificado_{timestamp}.txt"
        )
        
        conteudo_txt = []
        conteudo_txt.append("="*80)
        conteudo_txt.append("RELATÓRIO UNIFICADO DE AVARIAS E USO INTERNO")
        conteudo_txt.append(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        conteudo_txt.append("="*80)
        conteudo_txt.append("")
        
        # Processar cada sheet
        for sheet_name, df in sheets.items():
            # Verificar se a seção deve ser processada
            if secoes_filtro and sheet_name not in secoes_filtro:
                continue
                
            if df.empty:
                continue
            
            # Identificar se é uma sheet que deve ser unificada
            sheet_lower = sheet_name.lower()
            if "avaria" in sheet_lower or "uso interno" in sheet_lower:
                # Verificar se tem coluna Produto
                if "Produto" not in df.columns:
                    continue
                
                # Determinar tipo de sheet e aplicar unificação apropriada
                if "avaria" in sheet_lower:
                    # Processar AVARIAS
                    df_unificado, auditoria = unificar_itens_avarias(df)
                    tipo_processamento = "AVARIAS"
                elif "uso interno" in sheet_lower:
                    # Processar USO INTERNO
                    df_unificado, auditoria = unificar_itens_uso_interno(df)
                    tipo_processamento = "USO INTERNO"
                else:
                    continue
                
                # Aplicar filtro de colunas se fornecido
                if colunas_filtro and sheet_name in colunas_filtro:
                    colunas_selecionadas = colunas_filtro[sheet_name]
                    colunas_existentes = [col for col in colunas_selecionadas if col in df_unificado.columns]
                    if colunas_existentes:
                        df_unificado = df_unificado[colunas_existentes]
                
                # Adicionar ao conteúdo TXT
                conteudo_txt.append("-"*80)
                conteudo_txt.append(f"SEÇÃO: {sheet_name.upper()}")
                conteudo_txt.append("-"*80)
                conteudo_txt.append("")
                
                if tipo_processamento == "AVARIAS":
                    # Formato: PRODUTO | QUANTIDADE TOTAL
                    conteudo_txt.append("PRODUTO | QUANTIDADE TOTAL")
                    conteudo_txt.append("-"*80)
                    
                    for idx, row in df_unificado.iterrows():
                        produto = row.get("Produto", "N/A")
                        quantidade = row.get("Quantidade Total", "N/A")
                        conteudo_txt.append(f"{produto} | {quantidade}")
                
                elif tipo_processamento == "USO INTERNO":
                    # Formato: PRODUTO | QUANTIDADE TOTAL | CÓDIGO DE BARRAS
                    conteudo_txt.append("PRODUTO | QUANTIDADE TOTAL | CÓDIGO DE BARRAS")
                    conteudo_txt.append("-"*80)
                    
                    for idx, row in df_unificado.iterrows():
                        produto = row.get("Produto", "N/A")
                        quantidade = row.get("Quantidade Total", "N/A")
                        codigo_barras = row.get("Código de Barras", "N/A")
                        conteudo_txt.append(f"{produto} | {quantidade} | {codigo_barras}")
                
                conteudo_txt.append("")
                conteudo_txt.append(f"Total de itens: {len(df_unificado)}")
                conteudo_txt.append("")
        
        conteudo_txt.append("="*80)
        conteudo_txt.append("FIM DO RELATÓRIO")
        conteudo_txt.append("="*80)
        
        # Salvar arquivo TXT
        with open(arquivo_unificado, "w", encoding="utf-8") as f:
            f.write("\n".join(conteudo_txt))
        
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
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({"error": "Relatório não encontrado"}), 404
        
        # Ler arquivo Excel original
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine="openpyxl")
        
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


@app.route("/api/listar_modelos/<provider>")
def api_listar_modelos(provider):
    """
    API para listar modelos disponíveis de um provedor em tempo real.
    
    Args:
        provider: Nome do provedor (gemini, openai, claude, openrouter)
    
    Returns:
        JSON com lista de modelos disponíveis
    """
    try:
        from src.ai_providers import AIProviderFactory
        
        # Normalizar nome do provedor
        provider = provider.lower()
        
        # Obter configuração para pegar API key
        config = carregar_configuracao()
        api_keys = config.get("api", {})
        
        # Mapear nomes de provedores para chaves de configuração
        provider_key_map = {
            "gemini": "gemini_api_key",
            "openai": "openai_api_key",
            "claude": "anthropic_api_key",
            "anthropic": "anthropic_api_key",
            "openrouter": "openrouter_api_key"
        }
        
        # Obter API key do provedor
        api_key = None
        if provider in provider_key_map:
            api_key = api_keys.get(provider_key_map[provider], "")
        
        # Obter lista de modelos
        modelos = AIProviderFactory.obter_modelos(provider, api_key)
        
        if not modelos:
            return jsonify({
                "error": f"Provedor '{provider}' não encontrado ou sem modelos disponíveis"
            }), 404
        
        return jsonify({
            "provider": provider,
            "modelos": modelos,
            "success": True
        })
        
    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro ao listar modelos do provedor {provider}: {erro_completo}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500


@app.route("/api/testar_configuracao")
def testar_configuracao():
    """API para testar se a configuração está funcionando."""
    try:
        # Verificar configuração do Flask
        config_flask = carregar_configuracao()
        api_key_flask = config_flask.get("api", {}).get("gemini_api_key", "")
        
        # Verificar arquivos de configuração existentes
        arquivos_config = []
        
        # Verificar apenas o arquivo único de configuração
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config_arquivo = json.load(f)
                    api_key_arquivo = config_arquivo.get("api", {}).get("gemini_api_key", "")
                    arquivos_config.append({
                        "caminho": CONFIG_FILE,
                        "existe": True,
                        "api_key_definida": bool(api_key_arquivo and api_key_arquivo.strip()),
                        "api_key_preview": api_key_arquivo[:8] + "..." if api_key_arquivo else ""
                    })
            except Exception as e:
                arquivos_config.append({
                    "caminho": CONFIG_FILE,
                    "existe": True,
                    "erro": str(e)
                })
        else:
            arquivos_config.append({
                "caminho": CONFIG_FILE,
                "existe": False
            })
        
        # Sincronizar configuração
        config_sync_ok, config_sync_msg = verificar_e_corrigir_configuracao()
        
        resultado = {
            "flask_config": {
                "api_key_definida": bool(api_key_flask and api_key_flask.strip()),
                "api_key_preview": api_key_flask[:8] + "..." if api_key_flask else "",
                "modelo": config_flask.get("processamento", {}).get("modelo_gemini", "")
            },
            "arquivos_config": arquivos_config,
            "sincronizacao": {
                "sucesso": config_sync_ok,
                "mensagem": config_sync_msg
            }
        }
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/imagem/<path:filename>")
def servir_imagem(filename):
    """Serve imagens do diretório de imagens com cache otimizado."""
    try:
        # Verificar se o arquivo existe e é uma imagem
        caminho_completo = os.path.join(DIRETORIO_IMAGENS, filename)

        if not os.path.exists(caminho_completo):
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


# Função de entrada para Vercel (WSGI handler)
def application(environ, start_response):
    """Handler WSGI para Vercel."""
    return app(environ, start_response)


# Função adicional para compatibilidade
def handler(request):
    """Handler alternativo para Vercel."""
    return app


# Para desenvolvimento local
if __name__ == "__main__":
    # Garantir que as pastas necessárias existam apenas em desenvolvimento
    if "VERCEL" not in os.environ:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(os.path.join(BASE_PATH, "resultados"), exist_ok=True)
        os.makedirs(os.path.join(BASE_PATH, "logs"), exist_ok=True)
        os.makedirs(os.path.join(BASE_PATH, "config"), exist_ok=True)
        
        # Inicializar config.json com valores padrão se não existir
        if not os.path.exists(CONFIG_FILE):
            print("📝 Criando arquivo de configuração padrão...")
            carregar_configuracao()  # Isso criará o arquivo automaticamente
            print(f"✅ Arquivo de configuração criado em: {CONFIG_FILE}")
        else:
            print(f"✅ Arquivo de configuração encontrado: {CONFIG_FILE}")

    print("🚀 Iniciando Interface Web do Analisador de Avarias")
    print("📱 Acesse: http://localhost:5000")
    print("🌍 Compatível com Vercel para deploy")
    print("=" * 50)

    app.run(debug=True, host="0.0.0.0", port=5000)

# Exportar app para Vercel
app_vercel = app
