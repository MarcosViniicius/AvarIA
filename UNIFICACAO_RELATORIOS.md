# 📊 Funcionalidade de Unificação de Relatórios

## 🎯 Visão Geral

A funcionalidade de **pós-processamento de unificação** consolida itens equivalentes nos relatórios de Avarias e Uso Interno, gerando uma nova planilha com dados agregados e auditoria completa.

---

## ✨ Características

### 🔍 Identificação Inteligente
- **Normalização de texto**: Remove acentos, converte para minúsculas, ignora espaços extras
- **Detecção de equivalência**: Identifica "tomate", "Tomate", "TOMATE" como o mesmo produto
- **Suporte a múltiplas unidades**: kg, g, l, ml, unidades, caixas, pacotes, latas

### ➕ Consolidação Precisa
- **Soma de quantidades**: Agrega valores numéricos respeitando unidades de medida
- **Preservação de dados**: Mantém todas as informações originais
- **Formatação correta**: Usa vírgula decimal no padrão brasileiro

### 📋 Auditoria Completa
- **Rastreabilidade total**: Cada item consolidado lista todos os registros originais
- **Transparência**: Visualização de como os dados foram agrupados
- **Verificação facilitada**: Permite conferência manual dos agrupamentos

---

## 📝 Exemplo de Uso

### Entrada (Dados Originais)
```
Produto         | Quantidade
----------------|------------
tomate          | 2 kg
Tomate          | 3 kg
cebola          | 1,232 kg
CEBOLA          | 2 kg
alface          | 500 g
Alface          | 1,5 kg
```

### Saída (Dados Unificados)
```
Produto         | Quantidade      | Qtd_Registros_Consolidados
----------------|-----------------|---------------------------
tomate          | 5 kg           | 2
cebola          | 3,232 kg       | 2
alface          | 2,000 kg       | 2
```

### Auditoria
```
Produto_Unificado  | Quantidade_Extraida | Produto (Original) | Quantidade (Original)
-------------------|---------------------|-------------------|----------------------
tomate (5 kg)      | 2.0                | tomate            | 2 kg
tomate (5 kg)      | 3.0                | Tomate            | 3 kg
cebola (3,232 kg)  | 1.232              | cebola            | 1,232 kg
cebola (3,232 kg)  | 2.0                | CEBOLA            | 2 kg
alface (2,000 kg)  | 0.5                | alface            | 500 g
alface (2,000 kg)  | 1.5                | Alface            | 1,5 kg
```

---

## 🚀 Como Usar

### 1. Acessar a Página de Relatórios
- Navegue até a página de **Relatório** na aplicação
- Certifique-se de que há um relatório processado disponível

### 2. Iniciar Unificação
- Clique no botão **"Unificar Relatório"** (ícone de funil, cor amarela)
- Leia as informações sobre o processo no modal que aparece
- Clique em **"Iniciar Unificação"**

### 3. Aguardar Processamento
- O sistema processará automaticamente:
  - Leitura do relatório original
  - Identificação de itens equivalentes
  - Consolidação de quantidades
  - Geração de auditoria
  - Criação da nova planilha

### 4. Download do Resultado
- Quando concluído, clique em **"Baixar Relatório Unificado"**
- O arquivo Excel contém:
  - **[Seção] - Unificado**: Dados consolidados
  - **[Seção] - Auditoria**: Rastreamento completo
  - **[Seção] - Original**: Dados originais para referência

---

## 📄 Estrutura do Arquivo Gerado

```
Relatorio_Unificado_YYYYMMDD_HHMMSS.xlsx
│
├── Avarias - Unificado         (Dados consolidados)
├── Avarias - Auditoria         (Rastreamento de registros)
├── Avarias - Original          (Dados originais preservados)
│
├── Uso Interno - Unificado     (Dados consolidados)
├── Uso Interno - Auditoria     (Rastreamento de registros)
├── Uso Interno - Original      (Dados originais preservados)
│
└── [Outras seções]             (Copiadas sem alteração)
```

---

## 🔧 Detalhes Técnicos

### Normalização de Texto
```python
def normalizar_texto(texto):
    """
    - Remove acentos (café -> cafe)
    - Converte para minúsculas (TOMATE -> tomate)
    - Remove espaços extras
    """
```

### Extração de Quantidade
```python
def extrair_quantidade_unidade(texto):
    """
    Suporta:
    - "2 kg", "2,5 kg", "2.5 kg", "2kg"
    - "500g", "1,5 l", "3 unidades"
    - Converte vírgula para ponto internamente
    """
```

### Agrupamento
- Chave de grupo: `(produto_normalizado, unidade)`
- Soma de quantidades: Precisão de ponto flutuante
- Preservação: Primeiro nome encontrado + quantidade total

---

## ⚠️ Regras Importantes

### ✅ O que é unificado:
- Itens com nomes equivalentes (ignorando maiúsculas/minúsculas/acentos)
- Mesma unidade de medida
- Seções: "Avarias" e "Uso Interno"

### ❌ O que NÃO é unificado:
- Itens com unidades diferentes (2 kg + 3 unidades)
- Seções de erro (mantidas como estão)
- Outras colunas além de Produto e Quantidade

### 🔒 Garantias:
- **Nenhum dado original é perdido** (sempre preservado em aba separada)
- **Precisão numérica** (usa aritmética de ponto flutuante Python)
- **Rastreabilidade total** (cada item unificado lista suas origens)

---

## 🛡️ Segurança

- **Validação de nomes de arquivo**: Apenas arquivos com prefixo correto podem ser baixados
- **Sem alteração do original**: O relatório mestre nunca é modificado
- **Arquivos temporários**: Gerenciados automaticamente pelo sistema
- **Timestamp único**: Evita conflitos de nomes de arquivo

---

## 🎨 Interface

### Botão Principal
- **Localização**: Cabeçalho da página de Relatórios
- **Cor**: Amarelo (warning)
- **Ícone**: Funil (bi-funnel)
- **Tooltip**: "Unificar itens equivalentes e gerar relatório consolidado"

### Modal de Unificação
- **Explicação inicial**: Como funciona o processo
- **Exemplo visual**: Entrada e saída esperada
- **Avisos**: Informações sobre o arquivo gerado
- **Estados**: Processando, Sucesso, Erro

---

## 🐛 Tratamento de Erros

### Erros Comuns
1. **Relatório não encontrado**: Processe imagens primeiro
2. **Colunas não identificadas**: Verifique estrutura do relatório
3. **Erro de parsing**: Formatos de quantidade não suportados

### Mensagens
- Sempre exibidas no modal
- Logs detalhados no console do servidor
- Stack trace completo para debugging

---

## 📊 Performance

- **Processamento**: Linear com número de registros
- **Memória**: Eficiente (streaming com Pandas)
- **Arquivo gerado**: Proporcional ao tamanho original (3x aproximadamente)

---

## 🔄 Fluxo Técnico

```
1. Usuário clica em "Unificar Relatório"
   ↓
2. Frontend envia POST /api/unificar_relatorio
   ↓
3. Backend carrega relatório original
   ↓
4. Para cada sheet (Avarias, Uso Interno):
   a. Identifica colunas de Produto e Quantidade
   b. Normaliza produtos
   c. Extrai quantidades e unidades
   d. Agrupa por (produto_normalizado, unidade)
   e. Soma quantidades
   f. Gera auditoria
   ↓
5. Cria novo arquivo Excel com:
   - Sheets unificadas
   - Sheets de auditoria
   - Sheets originais
   ↓
6. Retorna URL de download
   ↓
7. Frontend exibe botão de download
   ↓
8. Usuário baixa arquivo
```

---

## 📚 APIs Implementadas

### POST /api/unificar_relatorio
- **Descrição**: Processa unificação do relatório
- **Resposta de sucesso**:
  ```json
  {
    "success": true,
    "message": "Relatório unificado gerado com sucesso",
    "download_url": "/download_relatorio_unificado/Relatorio_Unificado_...",
    "filename": "Relatorio_Unificado_20260126_143022.xlsx"
  }
  ```
- **Resposta de erro**:
  ```json
  {
    "success": false,
    "message": "Descrição do erro"
  }
  ```

### GET /download_relatorio_unificado/<filename>
- **Descrição**: Download do arquivo unificado
- **Parâmetros**: filename (validado por segurança)
- **Resposta**: Arquivo Excel para download

---

## 🎓 Casos de Uso

### 1. Consolidação Semanal
- Processar várias análises durante a semana
- No final, unificar para relatório consolidado
- Apresentar números totais à gestão

### 2. Auditoria de Processos
- Verificar se houve duplicação de registros
- Identificar padrões de avarias recorrentes
- Validar consistência dos dados

### 3. Relatórios Executivos
- Simplificar visualização de dados
- Remover redundâncias
- Focar em totais por produto

---

## 🔮 Possíveis Melhorias Futuras

- [ ] Suporte a conversão de unidades (kg ↔ g, l ↔ ml)
- [ ] Configuração de sinônimos (ex: "tomate" = "tomate cereja")
- [ ] Filtros de unificação por data/lote
- [ ] Exportação de relatório de diferenças
- [ ] Análise de tendências (produtos mais avariados)
- [ ] Integração com sistemas externos

---

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique os logs do servidor
2. Consulte esta documentação
3. Revise o código fonte em `app.py` (linhas de unificação)
4. Entre em contato com o desenvolvedor

---

**Desenvolvido com ❤️ para facilitar a gestão de avarias**
