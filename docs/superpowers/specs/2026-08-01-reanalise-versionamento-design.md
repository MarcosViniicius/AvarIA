# Reanálise sob demanda com versionamento

Data: 2026-08-01

## Problema

1. Reenviar o mesmo ZIP de imagens para reanalisar não reprocessa nada: a
   extração roda, mas nenhuma imagem nova chega à pasta de pendentes, então o
   pipeline não encontra nada a fazer.
2. Não existe forma de reanalisar uma execução específica do Histórico nem de
   ver múltiplas versões dos resultados de uma mesma análise.

## Causa raiz do item 1

`nome_para_gravar()` ([extraction.py:41-86](../../../src/autoavaria/services/extraction.py#L41-L86))
compara o conteúdo (hash SHA-256) de todo arquivo gravado — seja upload direto,
seja membro extraído de um ZIP — contra o que já existe na pasta de pendentes
**e** na pasta de imagens arquivadas (`imagens_processadas/`). Se o conteúdo é
idêntico a um arquivo já existente em qualquer uma das duas, a gravação é
silenciosamente ignorada (retorna `None`).

Essa checagem foi adicionada de propósito para corrigir um bug anterior:
reenviar o mesmo lote duplicava linhas no relatório e inflava as contagens de
avarias (comentário em [db.py:504-512](../../../src/autoavaria/services/db.py#L504-L512)
confirma isso). O botão "Reprocessar Tudo" em Configurações limpa a pasta de
pendentes e o log de processados, mas não `imagens_processadas/` — então a
checagem por hash contra o arquivo ainda bloqueia.

## Arquitetura

### Excel mestre como "estado atual"

Os totais gerais do Histórico (avarias, uso interno, peso, top produtos) são
lidos direto do Excel mestre (`resumo_geral()`, [db.py:501-576](../../../src/autoavaria/services/db.py#L501-L576)),
não somados a partir do banco. Isso significa: se a reanálise substituir, no
Excel, as linhas antigas das imagens reanalisadas pelas novas, os totais gerais
automaticamente refletem só a versão mais recente — sem precisar de nenhum
filtro extra "ignora versões antigas" nos cards do painel.

`total_execucoes` e `total_tokens` continuam somando todas as execuções do
banco (incluindo reanálises) — são métricas de atividade histórica, não de
estado atual, e já funcionam assim hoje.

### Versionamento (schema)

Duas colunas novas em `processing_runs`:

- `raiz_execucao_id INTEGER` — aponta para a execução original da linhagem.
  Uma execução nova (upload normal) tem `raiz_execucao_id = id` (a própria).
  Uma reanálise herda o `raiz_execucao_id` da execução que originou.
- `versao INTEGER NOT NULL DEFAULT 1` — 1, 2, 3... dentro da mesma linhagem.

Migração idempotente (mesmo padrão de `_migrar_colunas_report_items`):
adiciona as colunas se não existirem e faz backfill (`raiz_execucao_id = id`,
`versao = 1`) nas linhas existentes.

Nova função `db.listar_versoes(raiz_execucao_id)` retorna todas as execuções
da linhagem, ordenadas por `versao`.

## Funcionalidade 1 — Forçar reprocessamento (Upload)

Checkbox **"Forçar reprocessamento (ignorar duplicados)"** na tela de Upload,
ao lado do botão "Processar Agora".

- `nome_para_gravar()` ganha parâmetro opcional `forcar: bool = False`. Quando
  `True`, o caso de "conteúdo idêntico já existente" deixa de retornar `None`
  — passa a gravar com sufixo numérico, igual ao caso de "mesmo nome, conteúdo
  diferente".
- O flag é propagado por toda a cadeia de chamadas: `/upload_files` →
  `nome_para_gravar`; `/processar` → `extrair_arquivos_comprimidos()` →
  `ExtratorArquivos.extrair_todos()` → `_extrair_membro()` → `nome_para_gravar()`.
- Sem marcar o checkbox, o comportamento atual (proteção contra duplicar sem
  querer) continua exatamente como está.
- Como o arquivo grava com um nome novo (sufixo), ele automaticamente aparece
  como "pendente" para o pipeline — não é necessário alterar a lógica de
  `log_mestre.txt`/`listar_imagens_pendentes()`.

## Funcionalidade 2 — Botão "Reanalisar" + versionamento (Histórico)

### Botão "Reanalisar"

Na tela `historico_execucao.html`, novo botão no cabeçalho de ações (junto de
"Unificar", exportar Excel/TXT). **Só aparece na versão mais recente de cada
linhagem** — versões antigas são só para consulta/exportação, não podem gerar
uma nova reanálise a partir delas (evita bifurcar o histórico de versões; a
linha do tempo é sempre linear).

Nova função `reanalisar_execucao(run_id)` em `extraction_pipeline.py`,
modelada em cima do `reanalisar_erros()` já existente:

1. Lê os `report_items` da execução (`db.obter_execucao(run_id)["itens"]`),
   usando o `caminho_imagem` já salvo em cada item (funciona tanto para
   imagens já arquivadas quanto para as que ainda estão pendentes por erro).
2. Roda a extração de IA nessas imagens novamente.
3. Ao ter o primeiro resultado (novo ou erro) pronto: remove do Excel mestre
   as linhas cujo `Caminho da Imagem` pertence a este lote (todas as abas:
   Avarias, Uso Interno, Erros de Análise), depois grava as novas linhas.
   Removido **só depois** de ter os novos resultados prontos, para nunca
   ficar sem dado nenhum no meio de uma falha.
4. Cria uma nova linha em `processing_runs` (`tipo='reanalise'`,
   `raiz_execucao_id` herdado, `versao` incrementada) e os novos
   `report_items` vinculados a ela. Os `report_items` da versão antiga
   permanecem no banco intocados (para consulta da versão antiga).
5. Roda em thread de background com progresso, reaproveitando o mesmo padrão
   de polling que `/api/progresso_reanalise` já usa hoje.

### Lista de versões

Na mesma tela de detalhe, uma lista simples e clicável (“Versão 1 — data”,
“Versão 2 — data (atual)”...). Clicar em qualquer uma navega para o detalhe
daquela versão específica, reaproveitando a página de detalhe já existente.

## Tratamento de erros

- Falha da IA num lote durante a reanálise: item vira "Erro de Análise" na
  nova versão, não interrompe o resto do lote nem apaga a versão anterior.
- As linhas antigas do Excel só são removidas depois que a nova versão já tem
  resultado (novo ou erro) pronto para substituí-las — uma queda no meio do
  processo nunca deixa o relatório sem as linhas de uma versão anterior
  válida.

## Testes

- `nome_para_gravar(..., forcar=True)` sempre grava (nunca retorna `None`)
  mesmo com conteúdo idêntico já existente.
- Reanalisar uma execução cria uma nova linha em `processing_runs` com o
  mesmo `raiz_execucao_id` e `versao` incrementada.
- Depois de reanalisar, as linhas antigas dessas imagens não aparecem mais no
  Excel mestre (sem duplicar contagem) e as novas aparecem.
- Botão "Reanalisar" não aparece/é bloqueado ao visualizar uma versão que não
  é a mais recente da linhagem.

## Fora de escopo deste documento

Ficam para specs separados, menores:

- Auditoria da aba Configurações (bugs, opções que não deveriam estar lá).
- Aviso na tela de Upload sobre os formatos de imagem suportados (código de
  barras de produto = uso interno; etiqueta de pesagem/avaria = avaria).
