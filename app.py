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
from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for, make_response
import pandas as pd
import threading
import time
from functools import lru_cache
import gzip
from werkzeug.middleware.proxy_fix import ProxyFix

# Detectar ambiente e ajustar caminhos
def get_base_path():
    """Obtém o caminho base da aplicação considerando ambiente Vercel."""
    if 'VERCEL' in os.environ:
        # Em produção na Vercel
        return '/tmp'
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

app = Flask(__name__, 
           template_folder=os.path.join(BASE_PATH, 'templates'),
           static_folder=os.path.join(BASE_PATH, 'static'))

app.secret_key = os.environ.get('SECRET_KEY', 'sua_chave_secreta_aqui_mude_em_producao')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max por upload

# Otimizações de performance
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(hours=1)  # Cache estático
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Aplicar otimizações
init_optimizations(app)

# Cache para configurações
_config_cache = None
_config_cache_time = None
CONFIG_CACHE_TTL = 300  # 5 minutos

# Configurações básicas adaptadas para ambiente
UPLOAD_FOLDER = os.path.join(BASE_PATH, 'imagens_para_analisar')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'txt'}
EXTENSOES_IMAGEM = ('.png', '.jpg', '.jpeg')
DIRETORIO_IMAGENS = UPLOAD_FOLDER
ARQUIVO_SAIDA_EXCEL = os.path.join(BASE_PATH, 'resultados', 'Relatorio_Mestre_Produtos.xlsx')
LOG_CONSUMO_FILE = os.path.join(BASE_PATH, 'resultados', 'log_consumo_tokens.txt')
LOG_PROCESSADOS_FILE = os.path.join(BASE_PATH, 'resultados', 'log_mestre.txt')
CONFIG_FILE = os.path.join(BASE_PATH, 'config', 'config.json')

# Garantir que os diretórios existam
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, 'resultados'), exist_ok=True)

# Variáveis globais para controle de processamento
processamento_ativo = False
progresso_atual = {"progresso": 0, "status": "Aguardando", "logs": []}

@lru_cache(maxsize=1)
def carregar_configuracao():
    """Carrega configurações do arquivo JSON com cache."""
    global _config_cache, _config_cache_time
    
    # Verificar cache
    current_time = time.time()
    if (_config_cache is not None and 
        _config_cache_time is not None and 
        current_time - _config_cache_time < CONFIG_CACHE_TTL):
        return _config_cache
    
    config_padrao = {
        "api": {
            "provider": "gemini",
            "gemini_api_key": os.environ.get('GEMINI_API_KEY', ''),
            "openai_api_key": os.environ.get('OPENAI_API_KEY', ''),
            "anthropic_api_key": os.environ.get('ANTHROPIC_API_KEY', '')
        },
        "processamento": {
            "modelo_gemini": "gemini-1.5-flash",
            "temperatura": 0.1,
            "max_tokens": 1000,
            "timeout": 30
        },
        "interface": {
            "tema": "claro",
            "auto_refresh": True,
            "logs_tempo_real": True
        }
    }
    
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
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
                if os.environ.get('GEMINI_API_KEY'):
                    config['api']['gemini_api_key'] = os.environ.get('GEMINI_API_KEY')
                if os.environ.get('OPENAI_API_KEY'):
                    config['api']['openai_api_key'] = os.environ.get('OPENAI_API_KEY')
                if os.environ.get('ANTHROPIC_API_KEY'):
                    config['api']['anthropic_api_key'] = os.environ.get('ANTHROPIC_API_KEY')
                
                # Atualizar cache
                _config_cache = config
                _config_cache_time = current_time
                return config
        else:
            # Criar arquivo de configuração padrão se não estiver na Vercel
            if 'VERCEL' not in os.environ:
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
    if 'VERCEL' in os.environ:
        print("⚠️ Ambiente Vercel: configurações devem ser definidas como variáveis de ambiente")
        return True
        
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
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
        with open(LOG_PROCESSADOS_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    except IOError as e:
        print(f"⚠️ Erro ao ler log de arquivos processados: {e}")
        return set()

def executar_processamento_principal():
    """Executa o processamento principal importando e rodando o script original."""
    global progresso_atual
    
    try:
        # Verificar se há configurações válidas
        config = carregar_configuracao()
        api_key = config.get("api", {}).get("gemini_api_key", "")
        
        if not api_key:
            progresso_atual["logs"].append("❌ Chave da API Gemini não configurada!")
            progresso_atual["status"] = "Erro: API Key não configurada"
            return False
        
        progresso_atual["logs"].append("🔑 API Key encontrada, continuando...")
        
        # Verificar se há imagens para processar
        if not os.path.exists(DIRETORIO_IMAGENS):
            progresso_atual["logs"].append("❌ Diretório de imagens não encontrado!")
            return False
        
        imagens = [f for f in os.listdir(DIRETORIO_IMAGENS) 
                  if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        if not imagens:
            progresso_atual["logs"].append("❌ Nenhuma imagem encontrada para processar!")
            return False
        
        progresso_atual["logs"].append(f"📸 Encontradas {len(imagens)} imagens para processar")
        
        # No ambiente Vercel, o processamento completo pode ser limitado
        if 'VERCEL' in os.environ:
            progresso_atual["logs"].append("⚠️ Ambiente Vercel: processamento completo pode ser limitado")
            return False
        
        # Importar e executar o módulo principal (apenas em desenvolvimento local)
        extrair_dados_path = os.path.join(BASE_PATH, 'src', 'extrair-dados.py')
        if os.path.exists(extrair_dados_path):
            progresso_atual["logs"].append("⚙️ Carregando módulo de processamento...")
            spec = importlib.util.spec_from_file_location("extrair_dados", extrair_dados_path)
            extrair_dados = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(extrair_dados)
        else:
            progresso_atual["logs"].append("❌ Script de processamento não encontrado")
            return False
        
        progresso_atual["logs"].append("🚀 Iniciando análise com IA...")
        
        # Executar a função principal
        extrair_dados.main()
        
        # Verificar se o relatório foi gerado
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            progresso_atual["logs"].append("✅ Relatório Excel gerado com sucesso!")
            return True
        else:
            progresso_atual["logs"].append("⚠️ Processamento concluído, mas relatório não foi encontrado")
            return False
        
    except Exception as e:
        erro_msg = f"Erro ao executar processamento: {str(e)}"
        print(erro_msg)
        progresso_atual["logs"].append(f"❌ {erro_msg}")
        return False

def allowed_file(filename):
    """Verifica se o arquivo tem extensão permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@lru_cache(maxsize=128, typed=True)
def obter_estatisticas():
    """Obtém estatísticas do sistema com cache."""
    stats = {
        'imagens_total': 0,
        'imagens_processadas': 0,
        'imagens_pendentes': 0,
        'ultimo_processamento': 'Nunca',
        'tokens_consumidos_hoje': 0,
        'relatorio_existe': False
    }
    
    try:
        # Contar imagens apenas se diretório mudou
        if os.path.exists(DIRETORIO_IMAGENS):
            todos_arquivos = os.listdir(DIRETORIO_IMAGENS)
            # Filtro otimizado para extensões de imagem
            stats['imagens_total'] = sum(1 for f in todos_arquivos 
                                       if f.lower().endswith(EXTENSOES_IMAGEM))
        
        # Imagens já processadas
        processadas = carregar_logs()
        stats['imagens_processadas'] = len(processadas)
        stats['imagens_pendentes'] = max(0, stats['imagens_total'] - stats['imagens_processadas'])
        
        # Último processamento - cache por arquivo
        if os.path.exists(LOG_PROCESSADOS_FILE):
            mod_time = os.path.getmtime(LOG_PROCESSADOS_FILE)
            stats['ultimo_processamento'] = datetime.fromtimestamp(mod_time).strftime('%d/%m/%Y %H:%M')
        
        # Tokens consumidos hoje - otimizado
        if os.path.exists(LOG_CONSUMO_FILE):
            hoje = datetime.now().strftime('%Y-%m-%d')
            try:
                with open(LOG_CONSUMO_FILE, 'r', encoding='utf-8') as f:
                    # Ler apenas últimas linhas para performance
                    lines = f.readlines()[-50:]  # Últimas 50 linhas
                    for linha in lines:
                        if hoje in linha and 'tokens consumidos:' in linha:
                            tokens_str = linha.split('tokens consumidos:')[1].strip().replace(',', '')
                            stats['tokens_consumidos_hoje'] += int(tokens_str)
            except (ValueError, IndexError):
                pass
        
        # Verifica se existe relatório
        stats['relatorio_existe'] = os.path.exists(ARQUIVO_SAIDA_EXCEL)
        
    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")
    
    return stats

def obter_resultados_recentes():
    """Obtém os resultados mais recentes do relatório."""
    resultados = {'avarias': [], 'uso_interno': [], 'erros': []}
    
    try:
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            # Ler as últimas 10 entradas de cada tipo
            sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
            
            if 'Avarias' in sheets:
                df_avarias = sheets['Avarias'].tail(10)
                # Tratar valores NaN
                df_avarias = df_avarias.fillna('-')
                resultados['avarias'] = df_avarias.to_dict('records')
            
            if 'Uso Interno' in sheets:
                df_uso = sheets['Uso Interno'].tail(10)
                # Tratar valores NaN
                df_uso = df_uso.fillna('-')
                resultados['uso_interno'] = df_uso.to_dict('records')
            
            if 'Erros de Análise' in sheets:
                df_erros = sheets['Erros de Análise'].tail(10)
                # Tratar valores NaN
                df_erros = df_erros.fillna('-')
                resultados['erros'] = df_erros.to_dict('records')
                
    except Exception as e:
        print(f"Erro ao ler resultados: {e}")
    
    return resultados

def processar_em_background():
    """Executa o processamento em background."""
    global processamento_ativo, progresso_atual
    
    try:
        processamento_ativo = True
        progresso_atual = {"progresso": 0, "status": "Iniciando processamento...", "logs": []}
        
        # Log inicial
        timestamp = datetime.now().strftime('%H:%M:%S')
        progresso_atual["logs"].append(f"🚀 Iniciando processamento às {timestamp}")
        
        # Verificar se estamos na Vercel
        if 'VERCEL' in os.environ:
            progresso_atual["status"] = "❌ Erro: Processamento não disponível na Vercel"
            progresso_atual["logs"].append("❌ O processamento completo não está disponível no ambiente Vercel")
            progresso_atual["logs"].append("💡 Use o ambiente local para processamento de imagens")
            return
        
        # Verificar configurações
        progresso_atual["progresso"] = 5
        progresso_atual["status"] = "🔍 Verificando configurações..."
        config = carregar_configuracao()
        api_key = config.get("api", {}).get("gemini_api_key", "")
        
        if not api_key:
            progresso_atual["status"] = "❌ Erro: API Key não configurada"
            progresso_atual["logs"].append("❌ Chave da API Gemini não encontrada!")
            progresso_atual["logs"].append("⚙️ Configure a API Key na página de Configurações")
            return
        
        # Verificar imagens disponíveis
        progresso_atual["progresso"] = 10
        progresso_atual["status"] = "📸 Verificando imagens disponíveis..."
        
        if not os.path.exists(DIRETORIO_IMAGENS):
            progresso_atual["logs"].append("❌ Diretório de imagens não encontrado")
            progresso_atual["status"] = "❌ Erro: Diretório não encontrado"
            return
        
        imagens = [f for f in os.listdir(DIRETORIO_IMAGENS) 
                  if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        if not imagens:
            progresso_atual["logs"].append("❌ Nenhuma imagem encontrada para processar")
            progresso_atual["status"] = "❌ Erro: Nenhuma imagem encontrada"
            return
        
        progresso_atual["logs"].append(f"📸 Encontradas {len(imagens)} imagens para processar")
        
        # Verificar imagens já processadas
        progresso_atual["progresso"] = 20
        progresso_atual["status"] = "📋 Verificando arquivos já processados..."
        
        if os.path.exists(LOG_PROCESSADOS_FILE):
            with open(LOG_PROCESSADOS_FILE, 'r', encoding='utf-8') as f:
                processadas = set(line.strip() for line in f if line.strip())
            progresso_atual["logs"].append(f"📝 {len(processadas)} imagens já foram processadas anteriormente")
        else:
            processadas = set()
            progresso_atual["logs"].append("📝 Nenhuma imagem processada anteriormente")
        
        novas_imagens = [img for img in imagens if img not in processadas]
        progresso_atual["logs"].append(f"🆕 {len(novas_imagens)} novas imagens para processar")
        
        if not novas_imagens:
            progresso_atual["progresso"] = 100
            progresso_atual["status"] = "✅ Todas as imagens já foram processadas!"
            progresso_atual["logs"].append("✅ Todas as imagens já foram processadas!")
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
                progresso_atual["logs"].append(f"📄 Relatório Excel gerado: {ARQUIVO_SAIDA_EXCEL}")
                
                # Contar resultados
                try:
                    sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
                    for sheet_name, df in sheets.items():
                        if not df.empty:
                            progresso_atual["logs"].append(f"📊 {sheet_name}: {len(df)} registros")
                except Exception as e:
                    progresso_atual["logs"].append(f"⚠️ Erro ao ler estatísticas do relatório: {e}")
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
        timestamp = datetime.now().strftime('%H:%M:%S')
        progresso_atual["logs"].append(f"🏁 Processamento finalizado às {timestamp}")

@app.route('/')
def index():
    """Página principal com cache de resposta."""
    response = make_response()
    
    # Cache para melhor performance
    if request.headers.get('Cache-Control') != 'no-cache':
        response.headers['Cache-Control'] = 'public, max-age=60'  # 1 minuto
    
    stats = obter_estatisticas()
    resultados = obter_resultados_recentes()
    
    # Renderizar template
    html = render_template('index.html', stats=stats, resultados=resultados)
    response.set_data(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    
    return response

@app.route('/upload')
def upload_page():
    """Página de upload."""
    return render_template('upload.html')

@app.route('/upload_files', methods=['POST'])
def upload_files():
    """Endpoint para upload de arquivos."""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'message': 'Nenhum arquivo selecionado'})
        
        files = request.files.getlist('files')
        if not files or files[0].filename == '':
            return jsonify({'success': False, 'message': 'Nenhum arquivo selecionado'})
        
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
        
        return jsonify({
            'success': True, 
            'message': f'{len(uploaded_files)} arquivo(s) enviado(s) com sucesso!',
            'files': uploaded_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro no upload: {str(e)}'})

@app.route('/processar', methods=['POST'])
def iniciar_processamento():
    """Inicia o processamento das imagens."""
    global processamento_ativo
    
    # Verificar se estamos na Vercel
    if 'VERCEL' in os.environ:
        return jsonify({
            'success': False, 
            'message': 'Processamento não disponível no ambiente Vercel. Use o ambiente local.'
        })
    
    if processamento_ativo:
        return jsonify({'success': False, 'message': 'Processamento já em andamento'})
    
    # Verificar se há imagens para processar
    if not os.path.exists(DIRETORIO_IMAGENS):
        return jsonify({'success': False, 'message': 'Pasta de imagens não encontrada'})
    
    imagens = [f for f in os.listdir(DIRETORIO_IMAGENS) if f.lower().endswith(EXTENSOES_IMAGEM)]
    if not imagens:
        return jsonify({'success': False, 'message': 'Nenhuma imagem encontrada para processar'})
    
    # Iniciar processamento em background
    thread = threading.Thread(target=processar_em_background)
    thread.start()
    
    return jsonify({'success': True, 'message': 'Processamento iniciado!'})

@app.route('/status')
def obter_status():
    """Obtém o status atual do processamento."""
    # Adicionar informações extras ao progresso
    status_completo = progresso_atual.copy()
    
    # Adicionar contagem de imagens
    if os.path.exists(DIRETORIO_IMAGENS):
        imagens = [f for f in os.listdir(DIRETORIO_IMAGENS) if f.lower().endswith(EXTENSOES_IMAGEM)]
        status_completo['total_imagens'] = len(imagens)
    else:
        status_completo['total_imagens'] = 0
    
    return jsonify(status_completo)

@app.route('/logs')
@app.route('/visualizar_logs')
def visualizar_logs():
    """Página de visualização de logs em tempo real."""
    return render_template('logs.html')

@app.route('/api/logs')
def api_logs():
    """API para obter logs em tempo real."""
    try:
        logs = []
        
        # Ler log de processamento
        if os.path.exists(LOG_PROCESSADOS_FILE):
            with open(LOG_PROCESSADOS_FILE, 'r', encoding='utf-8') as f:
                linhas = f.readlines()
                logs.extend([{
                    'tipo': 'processado',
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'mensagem': linha.strip()
                } for linha in linhas[-20:] if linha.strip()])  # Últimas 20 linhas
        
        # Ler log de consumo
        if os.path.exists(LOG_CONSUMO_FILE):
            with open(LOG_CONSUMO_FILE, 'r', encoding='utf-8') as f:
                linhas = f.readlines()
                for linha in linhas[-10:]:  # Últimas 10 linhas
                    if linha.strip():
                        logs.append({
                            'tipo': 'consumo',
                            'timestamp': linha[:19] if len(linha) > 19 else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'mensagem': linha.strip()
                        })
        
        # Adicionar logs do progresso atual
        for log_msg in progresso_atual.get('logs', []):
            logs.append({
                'tipo': 'progresso',
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'mensagem': log_msg
            })
        
        return jsonify({
            'logs': logs[-50:],  # Últimos 50 logs
            'processamento_ativo': processamento_ativo,
            'progresso': progresso_atual
        })
        
    except Exception as e:
        return jsonify({
            'logs': [{'tipo': 'erro', 'timestamp': datetime.now().strftime('%H:%M:%S'), 'mensagem': f'Erro ao ler logs: {str(e)}'}],
            'processamento_ativo': processamento_ativo,
            'progresso': progresso_atual
        })

@app.route('/relatorio')
@app.route('/visualizar_relatorio')
def visualizar_relatorio():
    """Página de visualização do relatório."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            flash('Nenhum relatório encontrado. Execute o processamento primeiro.', 'warning')
            return redirect(url_for('index'))
        
        # Verificar se o arquivo não está vazio
        if os.path.getsize(ARQUIVO_SAIDA_EXCEL) == 0:
            flash('Arquivo de relatório está vazio. Execute o processamento novamente.', 'warning')
            return redirect(url_for('index'))
        
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        dados = {}
        
        if not sheets:
            flash('Relatório não contém dados válidos.', 'warning')
            return redirect(url_for('index'))
        
        for sheet_name, df in sheets.items():
            if df is not None and not df.empty:
                # Tratar valores NaN
                df = df.fillna('-')
                dados[sheet_name] = {
                    'colunas': df.columns.tolist(),
                    'dados': df.to_dict('records'),
                    'total': len(df)
                }
        
        if not dados:
            flash('Nenhum dado válido encontrado no relatório.', 'warning')
            return redirect(url_for('index'))
        
        return render_template('relatorio.html', dados=dados)
        
    except FileNotFoundError:
        flash('Arquivo de relatório não encontrado.', 'danger')
        return redirect(url_for('index'))
    except PermissionError:
        flash('Sem permissão para acessar o arquivo de relatório.', 'danger')
        return redirect(url_for('index'))
    except pd.errors.EmptyDataError:
        flash('Arquivo de relatório está vazio ou corrompido.', 'danger')
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Erro detalhado ao carregar relatório: {e}")
        flash(f'Erro ao carregar relatório: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/download_relatorio')
def download_relatorio():
    """Download do relatório em Excel."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            flash('Relatório não encontrado', 'warning')
            return redirect(url_for('index'))
        
        return send_file(
            ARQUIVO_SAIDA_EXCEL,
            as_attachment=True,
            download_name=f'Relatorio_Avarias_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
        )
    except Exception as e:
        flash(f'Erro no download: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/configuracoes')
def configuracoes():
    """Página de configurações."""
    config = carregar_configuracao()
    stats = obter_estatisticas()
    
    # Avisar sobre limitações na Vercel
    if 'VERCEL' in os.environ:
        config['_vercel_env'] = True
    
    return render_template('configuracoes.html', config=config, stats=stats)

@app.route('/salvar_configuracao', methods=['POST'])
def salvar_configuracao_route():
    """Salva as configurações do usuário."""
    try:
        data = request.json
        config = carregar_configuracao()
        
        # Atualizar configurações
        if 'api' in data:
            config['api'].update(data['api'])
        if 'processamento' in data:
            config['processamento'].update(data['processamento'])
        if 'interface' in data:
            config['interface'].update(data['interface'])
        
        # No ambiente Vercel, apenas simular salvamento
        if 'VERCEL' in os.environ:
            return jsonify({
                'success': True, 
                'message': 'No ambiente Vercel, use variáveis de ambiente para configurações'
            })
        
        if salvar_configuracao(config):
            return jsonify({'success': True, 'message': 'Configurações salvas com sucesso!'})
        else:
            return jsonify({'success': False, 'message': 'Erro ao salvar configurações'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/editar_dados')
def editar_dados():
    """Página de edição de dados do relatório."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            flash('Nenhum relatório encontrado para editar.', 'warning')
            return redirect(url_for('configuracoes'))
        
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        dados = {}
        
        for sheet_name, df in sheets.items():
            if df is not None and not df.empty:
                # Adicionar índice para edição
                df = df.reset_index()
                df['id_linha'] = df.index
                
                # Tratar valores NaN para evitar erros no template
                df = df.fillna('')  # Substitui NaN por string vazia
                
                dados[sheet_name] = {
                    'colunas': df.columns.tolist(),
                    'dados': df.to_dict('records'),
                    'total': len(df)
                }
        
        return render_template('editar_dados.html', dados=dados)
        
    except Exception as e:
        flash(f'Erro ao carregar dados para edição: {str(e)}', 'danger')
        return redirect(url_for('configuracoes'))

@app.route('/salvar_edicao', methods=['POST'])
def salvar_edicao():
    """Salva as edições feitas nos dados."""
    try:
        data = request.json
        sheet_name = data.get('sheet_name')
        linha_id = data.get('linha_id')
        campo = data.get('campo')
        novo_valor = data.get('novo_valor')
        
        print(f"📝 Salvando edição: Sheet={sheet_name}, Linha={linha_id}, Campo={campo}, Valor={novo_valor}")
        
        # Validação mais detalhada
        if not sheet_name:
            return jsonify({'success': False, 'message': 'Nome da planilha é obrigatório'})
        if linha_id is None:
            return jsonify({'success': False, 'message': 'ID da linha é obrigatório'})
        if not campo:
            return jsonify({'success': False, 'message': 'Nome do campo é obrigatório'})
        if novo_valor is None:
            novo_valor = ''  # Permitir valores vazios
        
        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
        
        # Ler arquivo Excel
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        
        if sheet_name not in sheets:
            return jsonify({'success': False, 'message': f'Planilha "{sheet_name}" não encontrada'})
        
        df = sheets[sheet_name]
        
        # Verificar se a linha existe
        if linha_id >= len(df) or linha_id < 0:
            return jsonify({'success': False, 'message': f'Linha {linha_id} não encontrada (total: {len(df)} linhas)'})
        
        # Verificar se a coluna existe
        if campo not in df.columns:
            return jsonify({'success': False, 'message': f'Campo "{campo}" não encontrado. Campos disponíveis: {list(df.columns)}'})
        
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
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine='openpyxl') as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)
        
        print(f"✅ Edição salva com sucesso!")
        return jsonify({'success': True, 'message': f'Campo "{campo}" atualizado com sucesso!'})
        
    except FileNotFoundError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
    except PermissionError:
        return jsonify({'success': False, 'message': 'Sem permissão para editar o arquivo. Verifique se está aberto em outro programa'})
    except pd.errors.EmptyDataError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório está vazio ou corrompido'})
    except Exception as e:
        print(f"❌ Erro ao salvar edição: {e}")
        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})

@app.route('/salvar_edicao_completa', methods=['POST'])
def salvar_edicao_completa():
    """Salva as edições completas feitas em uma linha."""
    try:
        data = request.json
        sheet_name = data.get('sheet_name')
        linha_id = data.get('linha_id')
        dados_linha = data.get('dados_linha')
        
        print(f"📝 Salvando edição completa: Sheet={sheet_name}, Linha={linha_id}, Dados={dados_linha}")
        
        # Validação
        if not sheet_name:
            return jsonify({'success': False, 'message': 'Nome da planilha é obrigatório'})
        if linha_id is None:
            return jsonify({'success': False, 'message': 'ID da linha é obrigatório'})
        if not dados_linha or not isinstance(dados_linha, dict):
            return jsonify({'success': False, 'message': 'Dados da linha são obrigatórios'})
        
        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
        
        # Ler arquivo Excel
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        
        if sheet_name not in sheets:
            return jsonify({'success': False, 'message': f'Planilha "{sheet_name}" não encontrada'})
        
        df = sheets[sheet_name]
        
        # Verificar se a linha existe
        if linha_id >= len(df) or linha_id < 0:
            return jsonify({'success': False, 'message': f'Linha {linha_id} não encontrada (total: {len(df)} linhas)'})
        
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
            return jsonify({'success': False, 'message': 'Nenhum campo válido foi encontrado para atualizar'})
        
        sheets[sheet_name] = df
        
        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine='openpyxl') as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)
        
        print(f"✅ Edição completa salva com sucesso! Campos atualizados: {', '.join(campos_atualizados)}")
        return jsonify({'success': True, 'message': f'Linha atualizada com sucesso! ({len(campos_atualizados)} campos alterados)'})
        
    except FileNotFoundError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
    except PermissionError:
        return jsonify({'success': False, 'message': 'Sem permissão para editar o arquivo. Verifique se está aberto em outro programa'})
    except pd.errors.EmptyDataError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório está vazio ou corrompido'})
    except Exception as e:
        print(f"❌ Erro ao salvar edição completa: {e}")
        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})

@app.route('/excluir_linha', methods=['POST'])
def excluir_linha():
    """Exclui uma linha do relatório."""
    try:
        data = request.json
        sheet_name = data.get('sheet_name')
        linha_id = data.get('linha_id')
        
        print(f"🗑️ Excluindo linha: Sheet={sheet_name}, Linha={linha_id}")
        
        if not sheet_name:
            return jsonify({'success': False, 'message': 'Nome da planilha é obrigatório'})
        if linha_id is None:
            return jsonify({'success': False, 'message': 'ID da linha é obrigatório'})
        
        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
        
        # Ler arquivo Excel
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        
        if sheet_name not in sheets:
            return jsonify({'success': False, 'message': f'Planilha "{sheet_name}" não encontrada'})
        
        df = sheets[sheet_name]
        
        # Verificar se a linha existe
        if linha_id >= len(df) or linha_id < 0:
            return jsonify({'success': False, 'message': f'Linha {linha_id} não encontrada (total: {len(df)} linhas)'})
        
        # Criar backup antes de excluir
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)
        
        # Remover linha
        df = df.drop(df.index[linha_id]).reset_index(drop=True)
        sheets[sheet_name] = df
        
        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine='openpyxl') as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)
        
        print(f"✅ Linha excluída com sucesso!")
        return jsonify({'success': True, 'message': 'Linha excluída com sucesso!'})
        
    except FileNotFoundError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
    except PermissionError:
        return jsonify({'success': False, 'message': 'Sem permissão para editar o arquivo. Verifique se está aberto em outro programa'})
    except Exception as e:
        print(f"❌ Erro ao excluir linha: {e}")
        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})

@app.route('/mover_item', methods=['POST'])
def mover_item():
    """Move um item de uma tabela para outra."""
    try:
        data = request.json
        sheet_origem = data.get('sheet_origem')
        sheet_destino = data.get('sheet_destino')
        linha_id = data.get('linha_id')
        
        print(f"🔄 Movendo item: {sheet_origem} -> {sheet_destino}, Linha={linha_id}")
        
        # Validação
        if not sheet_origem or not sheet_destino:
            return jsonify({'success': False, 'message': 'Planilhas de origem e destino são obrigatórias'})
        if linha_id is None:
            return jsonify({'success': False, 'message': 'ID da linha é obrigatório'})
        if sheet_origem == sheet_destino:
            return jsonify({'success': False, 'message': 'Planilha de origem e destino não podem ser iguais'})
        
        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
        
        # Ler arquivo Excel
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        
        if sheet_origem not in sheets:
            return jsonify({'success': False, 'message': f'Planilha de origem "{sheet_origem}" não encontrada'})
        if sheet_destino not in sheets:
            # Se a planilha de destino não existir, criar uma vazia
            # Definir colunas baseadas no tipo de planilha
            if sheet_destino == 'Avarias':
                colunas_destino = ["Produto", "Detalhes", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]
            elif sheet_destino == 'Uso Interno':
                colunas_destino = ["Produto", "Detalhes", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]
            elif sheet_destino == 'Erros de Análise':
                colunas_destino = ["Arquivo", "Detalhes do Erro", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]
            else:
                return jsonify({'success': False, 'message': f'Tipo de planilha destino "{sheet_destino}" não reconhecido'})
            
            sheets[sheet_destino] = pd.DataFrame(columns=colunas_destino)
        
        df_origem = sheets[sheet_origem]
        df_destino = sheets[sheet_destino]
        
        # Verificar se a linha existe na origem
        if linha_id >= len(df_origem) or linha_id < 0:
            return jsonify({'success': False, 'message': f'Linha {linha_id} não encontrada na planilha origem (total: {len(df_origem)} linhas)'})
        
        # Obter dados da linha
        linha_dados = df_origem.iloc[linha_id].copy()
        
        # Criar backup antes de mover
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)
        
        # Adaptar dados para a planilha de destino
        nova_linha = {}
        
        if sheet_destino == 'Avarias':
            nova_linha = {
                "Produto": linha_dados.get("Produto", linha_dados.get("Arquivo", "N/A")),
                "Detalhes": linha_dados.get("Detalhes", linha_dados.get("Detalhes do Erro", "Movido de outra planilha")),
                "Observação da Mensagem": linha_dados.get("Observação da Mensagem", "N/A"),
                "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
                "Ver Imagem": linha_dados.get("Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A"))
            }
        elif sheet_destino == 'Uso Interno':
            nova_linha = {
                "Produto": linha_dados.get("Produto", linha_dados.get("Arquivo", "N/A")),
                "Detalhes": linha_dados.get("Detalhes", linha_dados.get("Detalhes do Erro", "Movido de outra planilha")),
                "Observação da Mensagem": linha_dados.get("Observação da Mensagem", "N/A"),
                "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
                "Ver Imagem": linha_dados.get("Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A"))
            }
        elif sheet_destino == 'Erros de Análise':
            nova_linha = {
                "Arquivo": linha_dados.get("Arquivo", linha_dados.get("Produto", "N/A")),
                "Detalhes do Erro": linha_dados.get("Detalhes do Erro", linha_dados.get("Detalhes", "Movido de outra planilha")),
                "Observação da Mensagem": linha_dados.get("Observação da Mensagem", "N/A"),
                "Caminho da Imagem": linha_dados.get("Caminho da Imagem", "N/A"),
                "Ver Imagem": linha_dados.get("Ver Imagem", linha_dados.get("Caminho da Imagem", "N/A"))
            }
        
        # Adicionar nova linha à planilha de destino
        df_destino = pd.concat([df_destino, pd.DataFrame([nova_linha])], ignore_index=True)
        
        # Remover linha da planilha de origem
        df_origem = df_origem.drop(df_origem.index[linha_id]).reset_index(drop=True)
        
        # Atualizar sheets
        sheets[sheet_origem] = df_origem
        sheets[sheet_destino] = df_destino
        
        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine='openpyxl') as writer:
            for nome_sheet, dataframe in sheets.items():
                if not dataframe.empty:  # Só salvar planilhas não vazias
                    dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)
        
        produto_nome = nova_linha.get("Produto", nova_linha.get("Arquivo", "Item"))
        print(f"✅ Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!")
        
        return jsonify({
            'success': True, 
            'message': f"Item '{produto_nome}' movido com sucesso de '{sheet_origem}' para '{sheet_destino}'!"
        })
        
    except FileNotFoundError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
    except PermissionError:
        return jsonify({'success': False, 'message': 'Sem permissão para editar o arquivo. Verifique se está aberto em outro programa'})
    except pd.errors.EmptyDataError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório está vazio ou corrompido'})
    except Exception as e:
        print(f"❌ Erro ao mover item: {e}")
        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})

@app.route('/adicionar_linha', methods=['POST'])
def adicionar_linha():
    """Adiciona uma nova linha ao relatório."""
    try:
        data = request.json
        sheet_name = data.get('sheet_name')
        dados_linha = data.get('dados_linha')
        
        print(f"➕ Adicionando linha: Sheet={sheet_name}, Dados={dados_linha}")
        
        if not sheet_name:
            return jsonify({'success': False, 'message': 'Nome da planilha é obrigatório'})
        if not dados_linha or not isinstance(dados_linha, dict):
            return jsonify({'success': False, 'message': 'Dados da linha são obrigatórios'})
        
        # Verificar se arquivo existe
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
        
        # Ler arquivo Excel
        sheets = pd.read_excel(ARQUIVO_SAIDA_EXCEL, sheet_name=None, engine='openpyxl')
        
        if sheet_name not in sheets:
            return jsonify({'success': False, 'message': f'Planilha "{sheet_name}" não encontrada'})
        
        df = sheets[sheet_name]
        
        # Validar campos obrigatórios (se aplicável)
        campos_obrigatorios = ['Produto', 'Quantidade']
        for campo in campos_obrigatorios:
            if campo in df.columns and not dados_linha.get(campo, '').strip():
                return jsonify({'success': False, 'message': f'Campo "{campo}" é obrigatório'})
        
        # Criar nova linha com as colunas existentes
        nova_linha = {}
        for coluna in df.columns:
            valor = dados_linha.get(coluna, '')
            # Adicionar timestamp para campos de data se estiverem vazios
            if 'Data' in coluna and not valor:
                valor = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            nova_linha[coluna] = valor
        
        # Criar backup antes de adicionar
        backup_file = f"{ARQUIVO_SAIDA_EXCEL}.bak"
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_file)
        
        # Adicionar nova linha
        df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
        sheets[sheet_name] = df
        
        # Salvar arquivo Excel
        with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine='openpyxl') as writer:
            for nome_sheet, dataframe in sheets.items():
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)
        
        print(f"✅ Linha adicionada com sucesso! Total de linhas: {len(df)}")
        return jsonify({'success': True, 'message': f'Nova linha adicionada com sucesso! Total: {len(df)} registros'})
        
    except FileNotFoundError:
        return jsonify({'success': False, 'message': 'Arquivo de relatório não encontrado'})
    except PermissionError:
        return jsonify({'success': False, 'message': 'Sem permissão para editar o arquivo. Verifique se está aberto em outro programa'})
    except Exception as e:
        print(f"❌ Erro ao adicionar linha: {e}")
        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})

@app.route('/backup_relatorio')
def backup_relatorio():
    """Cria backup do relatório atual."""
    try:
        if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
            return jsonify({'success': False, 'message': 'Nenhum relatório encontrado'})
        
        # Criar nome do backup com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_nome = f"Relatorio_Backup_{timestamp}.xlsx"
        backup_path = os.path.join("resultados", backup_nome)
        
        # Copiar arquivo
        shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_path)
        
        return jsonify({
            'success': True, 
            'message': f'Backup criado: {backup_nome}',
            'backup_file': backup_nome
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao criar backup: {str(e)}'})

@app.route('/download_backup/<filename>')
def download_backup(filename):
    """Download de arquivo de backup."""
    try:
        backup_path = os.path.join("resultados", filename)
        if not os.path.exists(backup_path):
            flash('Backup não encontrado', 'warning')
            return redirect(url_for('configuracoes'))
        
        return send_file(backup_path, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'Erro no download: {str(e)}', 'danger')
        return redirect(url_for('configuracoes'))

@app.route('/limpar_dados', methods=['POST'])
def limpar_dados():
    """Limpa dados processados."""
    try:
        tipo = request.json.get('tipo', '')
        
        if tipo == 'logs':
            if os.path.exists(LOG_PROCESSADOS_FILE):
                os.remove(LOG_PROCESSADOS_FILE)
            if os.path.exists(LOG_CONSUMO_FILE):
                os.remove(LOG_CONSUMO_FILE)
            message = 'Logs limpos com sucesso!'
            
        elif tipo == 'relatorio':
            if os.path.exists(ARQUIVO_SAIDA_EXCEL):
                os.remove(ARQUIVO_SAIDA_EXCEL)
            message = 'Relatório removido com sucesso!'
            
        elif tipo == 'imagens':
            if os.path.exists(DIRETORIO_IMAGENS):
                for arquivo in os.listdir(DIRETORIO_IMAGENS):
                    arquivo_path = os.path.join(DIRETORIO_IMAGENS, arquivo)
                    if os.path.isfile(arquivo_path):
                        os.remove(arquivo_path)
            message = 'Imagens removidas com sucesso!'
            
        else:
            return jsonify({'success': False, 'message': 'Tipo de limpeza inválido'})
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/download_config')
def download_config():
    """Download das configurações como backup"""
    try:
        config_path = os.path.join(app.root_path, 'config.json')
        if not os.path.exists(config_path):
            flash('Arquivo de configuração não encontrado.', 'warning')
            return redirect(url_for('configuracoes'))
        
        return send_file(config_path, as_attachment=True, download_name='config_backup.json')
    except Exception as e:
        flash(f'Erro ao fazer download: {str(e)}', 'error')
        return redirect(url_for('configuracoes'))

@app.route('/api/stats')
def api_stats():
    """API para obter estatísticas atualizadas."""
    return jsonify(obter_estatisticas())

@app.route('/imagem/<path:filename>')
def servir_imagem(filename):
    """Serve imagens do diretório de imagens com cache otimizado."""
    try:
        # Verificar se o arquivo existe e é uma imagem
        caminho_completo = os.path.join(DIRETORIO_IMAGENS, filename)
        
        if not os.path.exists(caminho_completo):
            return jsonify({'error': 'Imagem não encontrada'}), 404
        
        # Verificar se é realmente uma imagem
        _, ext = os.path.splitext(filename.lower())
        if ext not in EXTENSOES_IMAGEM:
            return jsonify({'error': 'Arquivo não é uma imagem válida'}), 400
        
        # Configurar headers de cache para imagens
        def add_cache_headers(response):
            # Cache por 1 hora para imagens estáticas
            response.headers['Cache-Control'] = 'public, max-age=3600'
            response.headers['ETag'] = f'"{hash(filename + str(os.path.getmtime(caminho_completo)))}"'
            return response
        
        # Verificar ETag para cache condicional
        if_none_match = request.headers.get('If-None-Match')
        current_etag = f'"{hash(filename + str(os.path.getmtime(caminho_completo)))}"'
        
        if if_none_match == current_etag:
            response = make_response('', 304)  # Not Modified
            response.headers['ETag'] = current_etag
            return response
        
        response = make_response(send_file(caminho_completo))
        return add_cache_headers(response)
        
    except Exception as e:
        print(f"❌ Erro ao servir imagem {filename}: {e}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

# Função de entrada para Vercel (WSGI handler)
def application(environ, start_response):
    """Handler WSGI para Vercel."""
    return app(environ, start_response)

# Função adicional para compatibilidade
def handler(request):
    """Handler alternativo para Vercel."""
    return app

# Para desenvolvimento local
if __name__ == '__main__':
    # Garantir que as pastas necessárias existam apenas em desenvolvimento
    if 'VERCEL' not in os.environ:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(os.path.join(BASE_PATH, 'resultados'), exist_ok=True)
    
    print("🚀 Iniciando Interface Web do Analisador de Avarias")
    print("📱 Acesse: http://localhost:5000")
    print("🌍 Compatível com Vercel para deploy")
    print("=" * 50)
    
    app.run(debug=True, host='0.0.0.0', port=5000)

# Exportar app para Vercel
app_vercel = app
