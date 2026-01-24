# Funcionalidade de Reanálise de Erros

## 📋 Visão Geral

Esta funcionalidade permite reanalisar automaticamente itens que falharam durante o processamento inicial, sem reprocessar os dados já analisados com sucesso.

## 🎯 Objetivo

Quando o sistema processa imagens e mensagens, alguns itens podem falhar por diversos motivos (erro de API, problemas de parsing JSON, timeout, etc.). Esta funcionalidade permite:

1. Identificar automaticamente itens com erro
2. Listar esses erros na aba "Erros de Análise" do relatório
3. Reanalisar apenas os itens com erro através de um botão dedicado
4. Atualizar o relatório automaticamente após correção

## 🚀 Como Usar

### 1. Visualizar Erros

Após executar uma análise, acesse o **Relatório** e navegue até a aba **"Erros de Análise"**.

Esta aba mostrará:
- Arquivo que falhou
- Detalhes do erro ocorrido
- Observação da mensagem associada
- Botão para visualizar a imagem

### 2. Reanalisar Erros

Na aba "Erros de Análise", clique no botão **"Reanalisar Erros"** (ícone de seta circular).

Um modal será exibido mostrando:
- Barra de progresso da reanálise
- Status atual do processamento
- Arquivo sendo processado no momento

### 3. Ver Resultados

Ao final da reanálise, o modal mostrará:
- Total de arquivos processados
- ✅ Quantidade de itens corrigidos
- ⚠️ Quantidade de itens ainda com erro

Clique em **"Atualizar Relatório"** para ver as mudanças aplicadas.

## 🔧 Arquitetura Técnica

### Arquivos Modificados/Criados

#### 1. `src/gerenciador_erros.py` (NOVO)
**Responsabilidade:** Gerenciar rastreamento e estado dos erros

**Principais funções:**
- `obter_erros_pendentes()`: Retorna lista de erros do Excel
- `contar_erros_pendentes()`: Conta quantos erros existem
- `obter_arquivos_com_erro()`: Lista nomes de arquivos com erro
- `marcar_erro_como_reprocessado()`: Atualiza status após reanálise
- `gerar_resumo_erros()`: Cria estatísticas de erros

**Isolamento:** Este módulo não interfere com o processamento principal. Apenas lê e atualiza a planilha de erros.

#### 2. `src/extrair-dados.py` (MODIFICADO)
**Adicionado:** Função `reanalisar_erros()`

**O que faz:**
1. Carrega lista de arquivos com erro do Excel
2. Processa cada arquivo individualmente usando a mesma lógica da análise principal
3. Atualiza o Excel removendo erros corrigidos
4. Registra tentativas de reanálise no log

**Isolamento:** 
- Usa as mesmas funções de processamento existentes
- Não modifica dados já processados com sucesso
- Executa de forma independente do fluxo principal

#### 3. `app.py` (MODIFICADO)
**Adicionadas 3 novas rotas:**

##### `/api/obter_erros_pendentes` (GET)
Retorna informações sobre erros pendentes:
```json
{
  "success": true,
  "total": 5,
  "tipos": {
    "Erro de API": 3,
    "Erro de parsing JSON": 2
  },
  "arquivos": ["img1.jpg", "img2.jpg", ...]
}
```

##### `/api/reanalisar_erros` (POST)
Inicia o processo de reanálise em background:
```json
{
  "success": true,
  "message": "Reanálise iniciada para 5 itens",
  "total_erros": 5
}
```

##### `/api/progresso_reanalise` (GET)
Monitora progresso da reanálise em tempo real:
```json
{
  "ativo": true,
  "progresso": 60,
  "status": "Reanalisando: img3.jpg",
  "logs": ["[1/5] img1.jpg", "[2/5] img2.jpg", ...],
  "resultado": null
}
```

**Isolamento:** 
- Usa thread separada para não bloquear a aplicação
- Reutiliza variáveis globais de controle de processamento existentes
- Não interfere com outras rotas

#### 4. `templates/relatorio.html` (MODIFICADO)
**Modificações:**

1. **Aba de Erros:** Identificação visual melhorada com ícone específico
2. **Botão "Reanalisar Erros":** Aparece apenas na aba de erros
3. **Modal de Progresso:** Interface visual para acompanhar reanálise
4. **JavaScript inline:** Lógica de comunicação com API e atualização de UI

**Isolamento:**
- JavaScript só é ativado quando botão existe na página
- Não interfere com funcionalidades existentes de busca, filtro, etc.
- Modal é independente do modal de visualização de imagens

### Fluxo de Dados

```
[Usuário clica "Reanalisar Erros"]
         ↓
[JavaScript faz POST para /api/reanalisar_erros]
         ↓
[Backend inicia thread de reanálise]
         ↓
[Thread executa reanalisar_erros() do extrair-dados.py]
         ↓
[Para cada erro:]
  → Carrega imagem
  → Processa com Gemini AI
  → Se sucesso: adiciona ao relatório e remove do erros
  → Se falha: atualiza detalhes do erro
         ↓
[JavaScript monitora via /api/progresso_reanalise]
         ↓
[Atualiza UI em tempo real]
         ↓
[Ao final: exibe resultado e botão "Atualizar Relatório"]
```

## 🔒 Garantias de Isolamento

### ✅ O que NÃO é afetado:

1. **Processamento Principal:** O fluxo normal de análise continua exatamente igual
2. **Dados Existentes:** Itens já processados com sucesso não são tocados
3. **Interface Principal:** Dashboard, upload, configurações permanecem inalterados
4. **Logs Existentes:** Sistema de logs mantém seu funcionamento normal

### ✅ Como o isolamento é garantido:

1. **Módulo Separado:** `gerenciador_erros.py` é totalmente independente
2. **Thread Isolada:** Reanálise roda em thread separada sem bloquear aplicação
3. **Verificação de Estado:** Sistema verifica se há processamento ativo antes de iniciar
4. **Logs Separados:** Cria `log_reanalise.txt` sem tocar nos logs principais
5. **Processamento Seletivo:** Apenas arquivos na lista de erros são processados

## 📊 Logs e Rastreabilidade

### Log de Reanálise (`logs/log_reanalise.txt`)
Formato: `TIMESTAMP | ARQUIVO | STATUS | DETALHES`

Exemplo:
```
2026-01-24 14:30:15 | IMG_001.jpg | sucesso | Tipo: Avaria
2026-01-24 14:30:18 | IMG_005.jpg | falha | Timeout na API
2026-01-24 14:30:21 | IMG_010.jpg | sucesso | Tipo: Uso Interno
```

### Atualização do Excel
- **Sucesso:** Linha é removida da aba "Erros de Análise" e adicionada na aba correspondente
- **Falha:** Linha permanece com detalhes atualizados incluindo timestamp da tentativa

## 🧪 Testando a Funcionalidade

### Teste Manual

1. **Preparar Ambiente:**
   ```bash
   # Certificar-se que o ambiente virtual está ativo
   .\vev\Scripts\activate
   
   # Instalar dependências se necessário
   pip install -r requirements.txt
   ```

2. **Criar Erros Simulados:**
   - Execute uma análise normal
   - Manualmente adicione linhas na aba "Erros de Análise" do Excel
   - Ou force erros removendo temporariamente a API key

3. **Testar Reanálise:**
   - Acesse o relatório
   - Vá para aba "Erros de Análise"
   - Clique em "Reanalisar Erros"
   - Observe o progresso no modal
   - Verifique resultados ao final

4. **Verificar Isolamento:**
   - Confirme que dados das outras abas não foram alterados
   - Verifique que logs principais não foram afetados
   - Teste outras funcionalidades (upload, configuração, etc.)

### Teste Programático

```python
# Testar gerenciador de erros
from src.gerenciador_erros import criar_gerenciador

gerenciador = criar_gerenciador()
resumo = gerenciador.gerar_resumo_erros()
print(f"Total de erros: {resumo['total']}")
print(f"Tipos: {resumo['tipos']}")
```

## 🐛 Troubleshooting

### Problema: Botão "Reanalisar Erros" não aparece
**Solução:** Verifique se há uma aba chamada "Erros de Análise" no relatório

### Problema: Reanálise não inicia
**Possíveis causas:**
- Já existe processamento ativo
- API key não configurada
- Nenhum erro pendente

**Verificar:**
```python
# No console Python
from src.gerenciador_erros import criar_gerenciador
g = criar_gerenciador()
print(g.contar_erros_pendentes())
```

### Problema: Progresso não atualiza
**Solução:** 
- Verificar console do navegador (F12) para erros JavaScript
- Confirmar que `/api/progresso_reanalise` está acessível
- Verificar logs do servidor Flask

## 📈 Melhorias Futuras

Possíveis aprimoramentos:

1. **Reanálise Seletiva:** Permitir selecionar quais erros reanalisar
2. **Retry Automático:** Tentar automaticamente após primeira falha
3. **Categorização de Erros:** Agrupar por tipo de erro
4. **Histórico:** Manter histórico de tentativas de reanálise
5. **Notificações:** Email/webhook ao final da reanálise

## 🔐 Segurança

- Apenas processa arquivos que já estão no diretório de imagens
- Valida existência de arquivos antes de processar
- Usa mesmas validações da análise principal
- Logs de reanálise para auditoria

## 📝 Conclusão

Esta funcionalidade adiciona capacidade de recuperação de erros ao sistema sem modificar seu comportamento padrão. Toda a implementação é isolada e pode ser facilmente removida se necessário, sem afetar o restante da aplicação.

---

**Criado em:** 24 de Janeiro de 2026
**Versão:** 1.0
**Compatibilidade:** Python 3.8+, Flask 3.x
