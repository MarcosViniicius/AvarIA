# Deploy na Vercel - Guia Completo

## 🚀 Passos para Deploy

### 1. Preparação do Código
✅ Arquivos já configurados:
- `vercel.json` - Configuração de runtime Python 3.11
- `requirements.txt` - Dependências com versões específicas
- `.vercelignore` - Arquivos a serem ignorados no deploy
- `.env.example` - Exemplo de variáveis de ambiente

### 2. Configurar Variáveis de Ambiente na Vercel

**OBRIGATÓRIAS:**
```bash
GEMINI_API_KEY=your_gemini_api_key_here
SECRET_KEY=your_secret_key_here_change_in_production
FLASK_ENV=production
VERCEL=1
```

**OPCIONAIS:**
```bash
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### 3. Deploy via CLI da Vercel
```bash
# Instalar Vercel CLI
npm i -g vercel

# Fazer login
vercel login

# Deploy
vercel --prod
```

### 4. Deploy via GitHub (Recomendado)
1. Conecte seu repositório ao GitHub
2. Importe o projeto na Vercel
3. Configure as variáveis de ambiente no dashboard
4. Deploy automático a cada push

## ⚠️ Limitações Conhecidas

### Ambiente Serverless
- **Filesystem read-only**: Não é possível salvar arquivos permanentemente
- **Timeout**: Máximo 60 segundos por requisição (Hobby plan)
- **Memória**: Limitada a 1GB (Hobby plan)
- **Armazenamento temporário**: Apenas `/tmp/` disponível

### Funcionalidades Afetadas
- ❌ **Processamento completo de imagens**: Desabilitado em produção
- ❌ **Salvamento de configurações**: Usa apenas variáveis de ambiente
- ❌ **Relatórios persistentes**: Arquivos temporários em `/tmp/`
- ✅ **Upload de arquivos**: Funcional (armazenamento temporário)
- ✅ **Interface web**: Totalmente funcional
- ✅ **Visualização**: Funcional para dados existentes

## 🔧 Configurações Importantes

### Runtime
- **Python**: 3.11 (mais estável na Vercel)
- **Framework**: Flask 3.0.0
- **WSGI**: Handler configurado para Vercel

### Headers de Segurança
```python
# Já configurado no app.py
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
```

### Cache
- Cache de configurações: 5 minutos
- Cache de estatísticas: Usando @lru_cache
- Cache de resposta HTTP: 1 minuto para assets

## 🐛 Solução de Problemas

### Erro de Importação
```bash
# Se houver erro de importação, verifique:
pip install -r requirements.txt
```

### Timeout na Vercel
- Funções limitadas a 60s (Hobby) / 900s (Pro)
- Processamento de imagens desabilitado automaticamente

### Erro 500
- Verifique logs na dashboard da Vercel
- Confirme se variáveis de ambiente estão configuradas
- Verifique se SECRET_KEY está definido

### Problemas de Cache
```python
# Para limpar cache manualmente
carregar_configuracao.cache_clear()
```

## 📁 Estrutura de Arquivos na Vercel

```
/tmp/
├── imagens_para_analisar/  # Upload temporário
├── resultados/             # Relatórios temporários
└── config/                 # Configurações temporárias
```

## 🌟 Recomendações para Produção

### Para uso completo em produção:
1. **VPS/Servidor dedicado**: Para processamento de imagens
2. **Banco de dados**: Para persistir dados
3. **Armazenamento externo**: S3, Cloudinary, etc.
4. **Queue system**: Para processamento background

### Para demo/interface:
- Vercel é perfeita para demonstrar a interface
- Funcionalidades de visualização funcionam normalmente
- Upload funciona (temporariamente)

## 🔐 Segurança

### Variáveis de Ambiente Sensíveis
- Nunca commite API keys no código
- Use o dashboard da Vercel para configurar variáveis
- Gere SECRET_KEY forte para produção

### Headers de Segurança
```python
# Já configurado
response.headers['X-Content-Type-Options'] = 'nosniff'
response.headers['X-Frame-Options'] = 'DENY'
```

## 📊 Monitoramento

### Logs
- Acesse via `vercel logs`
- Dashboard da Vercel mostra métricas
- Erros são reportados automaticamente

### Performance
- Vercel Analytics disponível
- Monitor de uptime integrado
- Edge locations globais

## 🎯 Próximos Passos

1. ✅ **Deploy inicial**: Arquivos já configurados
2. 🔄 **Configurar variáveis**: Na dashboard da Vercel
3. 🚀 **Testar deploy**: Fazer primeiro deploy
4. 📊 **Monitorar**: Verificar logs e performance
5. 🔧 **Otimizar**: Baseado em métricas reais