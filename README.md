# 🔍 AvarIA

**As perdas da loja à vista.**

Sistema web para automatizar o registro de avarias e uso interno de mercadorias em loja: a partir de fotos dos produtos (e, opcionalmente, da conversa do WhatsApp que acompanha o envio), o sistema identifica cada item, extrai os dados relevantes (código de barras, peso, quantidade) e monta um relatório estruturado — pronto para exportar em Excel/TXT — separando os casos em **Avaria**, **Uso Interno** e **Erro**.

## 🎯 Como funciona

Cada execução processa um lote de imagens em duas frentes, que podem ser combinadas:

1. **Leitura de código de barras (sem IA)** — decodifica localmente o EAN-13 da etiqueta usando `opencv` + `zxing-cpp`, sem chamadas de rede. Reconhece tanto o EAN-13 comum (produto industrializado) quanto o código de balança de peso variável (que já embute o valor em centavos).
2. **Extração com IA** — quando o código de barras não é suficiente (etiqueta ilegível, produto sem código, contexto da conversa), a imagem (e o texto do WhatsApp associado a ela) é enviada a um provedor de IA (Gemini, OpenAI, Claude ou OpenRouter) que devolve os dados estruturados da avaria.

O resultado de cada execução fica registrado no histórico (SQLite), com **versionamento**: é possível reanalisar apenas os itens que deram erro, ou reprocessar uma execução inteira como uma nova versão, sem perder o histórico da versão anterior. Depois, os relatórios de várias execuções podem ser **unificados** em um único Excel/TXT, com filtros por período, loja, etc.

## 📚 Funcionalidades

- ✅ **Extração híbrida**: código de barras local (rápido, sem custo de API) + IA como complemento/fallback
- ✅ **Múltiplos provedores de IA**: Gemini, OpenAI, Claude e OpenRouter, com busca automática dos modelos disponíveis
- ✅ **Histórico com versionamento**: cada reprocessamento gera uma nova versão da execução, mantendo a anterior rastreável
- ✅ **Reanálise sob demanda**: reanalisa só os itens com erro ou a execução inteira, com opção de forçar reprocessamento
- ✅ **Edição de relatório**: corrige, move, adiciona ou exclui linhas do relatório direto pela interface
- ✅ **Unificação de relatórios**: combina o resultado de várias execuções em um único relatório exportável
- ✅ **Exportação em Excel e TXT**, com filtros personalizados de colunas/período
- ✅ **Interface web** (Flask + Bootstrap) com tema claro/escuro, logs em tempo real e dashboard de estatísticas

## 🚀 Início Rápido

### Pré-requisitos
- Python 3.8+
- Pip (gerenciador de pacotes Python)

### Instalação

1. **Clone o repositório**
```bash
git clone https://github.com/MarcosViniicius/AvarIA
cd AvarIA
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

O arquivo `config/config.json` será **criado automaticamente** na primeira execução com as configurações padrão.

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
avariaia/
├── app.py                              # Entrypoint (Flask app + handlers p/ Vercel)
├── config/
│   ├── config.json                     # Configurações (gerado automaticamente, não versionado)
│   └── config.example.json             # Template de configuração
├── avariaia/
│   ├── routes/                         # Blueprints Flask (upload, processamento, histórico,
│   │                                    # relatório, edição, unificação, erros/reanálise, etc.)
│   ├── services/                       # Regras de negócio: extração (IA + código de barras),
│   │                                    # banco de dados, relatórios, unificação, config, etc.
│   ├── core/                           # Paths, logging e exceções compartilhadas
│   ├── templates/                      # Templates HTML (Jinja)
│   └── static/                         # CSS e JS
├── database/                           # Banco SQLite com o índice de execuções/histórico
├── imagens_para_analisar/              # Upload de imagens
├── imagens_processadas/                # Imagens já processadas
├── resultados/                         # Relatórios gerados (Excel/TXT)
├── logs/                                # Logs do sistema
└── tests/                              # Testes automatizados (pytest)
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

## 🧪 Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## 🌐 Deploy

### Vercel

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

**AvarIA** — desenvolvido com ❤️ usando Flask e IA.
