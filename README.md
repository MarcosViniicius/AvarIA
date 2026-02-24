# 🔍 Auto Avaria - Sistema de Análise de Avarias

Sistema inteligente para análise automatizada de imagens de avarias usando IA.

## 🚀 Início Rápido

### Pré-requisitos
- Python 3.8+
- Pip (gerenciador de pacotes Python)

### Instalação

1. **Clone o repositório**
```bash
git clone <seu-repositorio>
cd autoavaria
```

2. **Crie e ative o ambiente virtual**
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

3. **Instale as dependências**
```bash
pip install -r requirements.txt
```

4. **Execute o projeto**
```bash
python app.py
```

O arquivo `config.json` será **criado automaticamente** na primeira execução com as configurações padrão!

## ⚙️ Configuração

### Configuração Automática (Recomendado)

Na primeira execução, o sistema criará automaticamente o arquivo `config/config.json` com as seguintes configurações padrão:

```json
{
  "api": {
    "provider": "gemini",
    "modelo_selecionado": "gemini-2.5-flash-lite"
  },
  "processamento": {
    "modelo_gemini": "gemini-2.5-flash-lite",
    "temperatura": 0.1,
    "max_tokens": 4000,
    "timeout": 60,
    "tamanho_lote": 12,
    "max_workers": 1,
    "request_delay": 13.0
  },
  "interface": {
    "tema": "escuro",
    "auto_refresh": true,
    "logs_tempo_real": true,
    "logs_detalhados_aplicacao": false
  }
}
```

### Configuração via Interface Web

1. Acesse: **http://localhost:5000**
2. Vá em **Configurações** no menu
3. Configure:
   - **API Key**: Adicione sua chave de API do provedor escolhido
   - **Provedor**: Gemini, OpenAI, Claude ou OpenRouter
   - **Modelo**: O sistema busca automaticamente os modelos disponíveis
   - **Parâmetros avançados**: Ajuste temperatura, tokens, workers, etc.

As configurações são salvas automaticamente no arquivo `config.json`.

## 🔑 Obtendo API Keys

### Google Gemini (Recomendado - Gratuito)
1. Acesse: https://makersuite.google.com/app/apikey
2. Clique em "Create API Key"
3. Copie a chave gerada
4. Cole na interface web em **Configurações > API > Gemini API Key**

### OpenAI
- **URL**: https://platform.openai.com/api-keys
- Requer cartão de crédito (pago)

### Claude (Anthropic)
- **URL**: https://console.anthropic.com/account/keys
- Requer cartão de crédito (pago)

### OpenRouter
- **URL**: https://openrouter.ai/keys
- Acesso a múltiplos modelos (pago)

## 📁 Estrutura do Projeto

```
autoavaria/
├── app.py                          # Aplicação Flask principal
├── config/
│   ├── config.json                 # Configurações (gerado automaticamente)
│   └── config.example.json         # Template de configuração
├── src/
│   ├── ai_providers.py             # Abstração de provedores de IA
│   ├── extrair_arquivos.py         # Extração de dados
│   └── ...
├── templates/                      # Templates HTML
├── static/                         # CSS, JS, imagens
├── imagens_para_analisar/          # Upload de imagens
├── resultados/                     # Relatórios gerados
└── logs/                           # Logs do sistema
```

## 🔒 Segurança

⚠️ **IMPORTANTE**: O arquivo `config.json` contém API keys sensíveis e está no `.gitignore`.

**NUNCA** commite o arquivo `config.json` no Git!

### Boas Práticas

1. Use o `config.example.json` como referência
2. Cada desenvolvedor cria seu próprio `config.json` localmente
3. Use variáveis de ambiente para produção:
   ```bash
   export GEMINI_API_KEY="sua-chave-aqui"
   export OPENAI_API_KEY="sua-chave-aqui"
   ```

## 🌐 Deploy

### Vercel (Recomendado)

1. Instale o Vercel CLI:
```bash
npm i -g vercel
```

2. Configure as variáveis de ambiente no dashboard da Vercel:
   - `GEMINI_API_KEY`
   - `OPENAI_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `OPENROUTER_API_KEY`

3. Deploy:
```bash
vercel
```

## 📚 Funcionalidades

- ✅ **Análise Automatizada**: Processa imagens de avarias usando IA
- ✅ **Múltiplos Provedores**: Suporte para Gemini, OpenAI, Claude e OpenRouter
- ✅ **Busca Dinâmica de Modelos**: Lista automaticamente modelos disponíveis de cada API
- ✅ **Relatórios Unificados**: Exportação em Excel e TXT com filtros personalizados
- ✅ **Interface Web Moderna**: Bootstrap 5 com tema escuro/claro
- ✅ **Configuração Simplificada**: Config.json gerado automaticamente

## 🆘 Solução de Problemas

### Config.json não é criado
```bash
# Crie manualmente a pasta
mkdir config

# Execute novamente
python app.py
```

### Erro de API Key
- Verifique se a API key está correta em **Configurações**
- Confira se a API key tem permissões necessárias
- Para Gemini, certifique-se que tem acesso ao modelo selecionado

### Erro ao instalar dependências
```bash
# Atualize o pip
python -m pip install --upgrade pip

# Reinstale as dependências
pip install -r requirements.txt --force-reinstall
```

## 📝 Licença

Este projeto é de uso interno/privado.

## 🤝 Contribuindo

1. Fork o projeto
2. Crie uma branch: `git checkout -b feature/nova-funcionalidade`
3. Commit suas mudanças: `git commit -m 'Adiciona nova funcionalidade'`
4. Push para a branch: `git push origin feature/nova-funcionalidade`
5. Abra um Pull Request

---

**Desenvolvido com ❤️ usando Flask e IA**
