# Guia do Usuário — Auto Avaria

Para quem opera a loja: envia fotos, confere o relatório, exporta e corrige erros.
Sem jargão técnico. Se você desenvolve, vá para `GUIA_DESENVOLVEDOR.md`.

## 1. O que o sistema faz (em 30 segundos)

1. Você envia **fotos das etiquetas/produtos** (e, se tiver, a **conversa do WhatsApp** em `.txt`).
2. O sistema identifica cada item e separa em 3 grupos:
   - **Avaria** — produto estragado, quebrado, vencido, perda/descarte. Vai para baixa no estoque.
   - **Uso Interno** — produto consumido pela equipe/loja. Identificado pelo **código de barras**.
   - **Erro** — não deu para identificar. Precisa de revisão sua.
3. Você confere, corrige se precisar, e exporta em **Excel ou TXT**.

## 2. Passo a passo

### 2.1 Enviar imagens

- Acesse `http://localhost:5000` → **Upload**.
- Arraste fotos (`JPG/PNG/JPEG`) ou um compactado (`ZIP/TAR/RAR/7Z`). O sistema extrai sozinho.
- Pode mandar de uma vez; duplicadas são ignoradas automaticamente.
- Opcional, mas recomendado: inclua o `.txt` exportado do WhatsApp junto. É ele que diz a **quantidade** ("7 unidades") e o contexto ("perda de hoje", "uso interno").

> Dica: uma foto com legenda "7" significa 7 unidades. Sem legenda, conta como 1.

### 2.2 Processar

- Na tela de processamento, escolha o modo:
  - **Somente IA** — entende foto + texto, mas consome API (custo).
  - **Sem IA (código de barras)** — grátis e instantâneo, mas só resolve etiqueta legível com produto já conhecido. O resto cai em Erro.
  - **Híbrido** (recomendado) — tenta de graça primeiro, manda para a IA só o que faltar. Cada rodada ensina o sistema para a próxima.
- Clique **Processar** e acompanhe o progresso e os logs em tempo real.

### 2.3 Conferir o relatório

- Abra **Relatório**: abas `Avarias`, `Uso Interno`, `Erros de Análise`.
- Colunas principais:
  - Avarias: Produto, Quantidade, **Peso**, Observação, imagem (clique em "Ver Imagem").
  - Uso Interno: Produto, Quantidade, Marca, **Código de Barras**, Observação, imagem.
  - Erros: Arquivo, motivo (ex.: "Nenhum código legível"), Observação, imagem.
- Erros comuns e o que fazer:
  - "Não informa se é Avaria ou Uso Interno" → escreva na conversa "avaria" ou "uso interno", ou reprocesse no modo híbrido.
  - "Nenhum código legível" → foto tremida/escura; reenvie foto melhor ou complete manualmente.

### 2.4 Corrigir, mover, adicionar, excluir

- Na tela **Editar dados** (ou no Histórico da execução) você pode:
  - Corrigir um campo (nome, peso, quantidade...).
  - **Mover** um item para outra aba (ex.: de Erro para Avaria).
  - **Adicionar** uma linha manual.
  - **Excluir** linha errada.
- Tudo fica registrado no histórico com versão (nada se perde).

### 2.5 Reanalisar erros / reprocessar execução

- **Reanalisar erros**: pega só a aba Erros e tenta de novo (sempre com IA). O que for resolvido sai da aba de erros e a foto é arquivada.
- **Reanalisar execução** (no Histórico): reprocessa uma execução inteira como **nova versão** (v1, v2...). A versão antiga continua consultável.
- **Reanálise seletiva** (um tipo, vários ou todos):
  - Na **exibição** (Relatório ou detalhe da execução no Histórico), marque as linhas com o checkbox ✓ e use o menu **Reanalisar**: todas, só Avarias, só Uso Interno, só Erros ou só os marcados. Vira nova versão da execução (o resto é copiado intacto).
  - Na **aba Editar** (relatório geral), marque as linhas ou use **Reanalisar → Aba atual**; as linhas daquelas imagens são substituídas no Excel.

### 2.6 Unificar e exportar

- **Unificar**: junta várias execuções (ou a última) num relatório resumido:
  - Avarias: agrupa por produto e **soma o peso** (`0,738kg + 0,500kg = 1,238 kg`) ou conta unidades quando não há peso.
  - Uso Interno: agrupa **pelo código de barras** (nomes diferentes com mesmo código viram uma linha só) e soma quantidades.
- **Exportar**: baixe em `.xlsx` (com link para a imagem) ou `.txt` (detalhado ou compacto). Dá para filtrar colunas e período.

## 3. Conceitos que valem ouro

- **Etiqueta de balança (começa com `2`)**: etiqueta impressa na loja. O código já traz o valor (ex.: `2001400005167` = PLU `00140`, total R$ 5,16). O peso é calculado dividindo pelo preço/kg cadastrado. Sempre cai em **Avaria**.
- **EAN comum (ex.: `789...`)**: produto industrializado. Identifica o produto, mas **não diz sozinho** se é Avaria ou Uso Interno — precisa do texto ("avariado", "uso interno") ou do cadastro.
- **Quantidade**: só existe no texto do WhatsApp. "3 cx", "x7", "7" sozinho = 7 unidades. Peso (`kg/g`) e preço (`R$`) nunca são confundidos com quantidade.
- **Aprendizado**: quando a IA descobre um produto novo, o sistema aprende. Na próxima vez, resolve sem IA. Preço/kg expira em ~30 dias para revalidar (preço muda).

## 4. FAQ

| Pergunta | Resposta |
|---|---|
| Foto sem etiqueta resolve? | Só com IA + texto descritivo. Sem IA, vira Erro. |
| Preciso da conversa do WhatsApp? | Não é obrigatório, mas sem ela você perde quantidade e contexto. Recomendado. |
| Erro "sem API key"? | Vá em Configurações e cole a chave do provedor (Gemini tem plano gratuito). Modo "Sem IA" dispensa chave. |
| Relatório sumiu? | Veja `resultados/Relatorio_Mestre_Produtos.xlsx` e o **Histórico** (versões). |
| Imagem não abre no Excel? | O link aponta para o caminho original; se você apagou `imagens_processadas/`, o link quebra (o dado continua lá). |
| Posso apagar imagens? | Sim, em Manutenção, mas entenda: apagar a imagem quebra o "Ver Imagem" antigo. O sistema avisa antes. |

## 5. Onde fica cada coisa (pastas)

- `imagens_para_analisar/` — fila de entrada (o que ainda será processado).
- `imagens_processadas/` — arquivadas após sucesso.
- `resultados/` — Excel/TXT gerados.
- `logs/` — `log_mestre.txt` (processadas), `log_consumo_tokens.txt`, `log_reanalise.txt`.
- `database/autoavaria.db` — histórico (não mexa manualmente).
