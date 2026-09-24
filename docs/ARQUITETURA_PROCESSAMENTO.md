# Arquitetura de Processamento, Categorização e Classificação

Deep dive do backend que transforma foto em linha de relatório. Público: desenvolvedores e IAs.

## 1. Visão do fluxo

```
Upload/ZIP ──ExtratorArquivos──▶ imagens_para_analisar/ + conversa.txt
        │
        ▼
pipeline.main()
  ├─ listar_imagens_pendentes()   (nome vs log_mestre.txt)
  ├─ db.iniciar_execucao()
  ├─ conversa.mapear_contextos()  (texto + quantidade por imagem)
  ├─ construir_motor(ia|sem_ia|hibrido)
  ├─ ThreadPool(tamanho_lote=12) → motor.processar_lote()
  │     └─ ai_extraction.processar_resultado_arquivo()  (Avaria/Uso Interno/Erro)
  ├─ _persistir_lote()            (Excel mestre + DB, por lote)
  ├─ registrar_log() + image_archive.arquivar_imagem()  (só sucesso)
  └─ db.finalizar_execucao() + tokens
        │
        ▼
reanalisar_erros() (só aba Erros, sem versão) | reanalisar_execucao() (tudo, nova versão)
        │
        ▼
unificação (agrupar) → exportação (xlsx/txt detalhado|compacto)
```

Ordem anti-perda: **gravar (Excel+DB) antes de marcar (log+arquivar)**. Falha no Excel → imagem continua pendente.

## 2. Código de barras (sem IA) — `services/barcode.py`

- Deps opcionais `opencv + zxing-cpp`; sem elas, `LEITURA_DISPONIVEL=False` e o modo sem IA faz fallback para IA.
- `ler_imagem(caminho)`: cinza → resize `MAX_LADO=1600` → variantes (original → CLAHE → 2x → nitidez → rot90/270) → ladrilhos 3×3 overlap 25% → `_decodificar` (só `ean13_valido`) → dedup.
- Validação: `ean13_valido()` confere DV `(10-sum%10)%10`. Dígito trocado = rejeitado (é por isso que o leitor ganha da IA em código: IA alucina dígito, leitor não).
- Balança: `eh_etiqueta_balanca()` = prefixo `2`. `interpretar_etiqueta_balanca("2001400005167")` → `("00140", 5.16)`: `PLU=codigo[1:6]`, `total=int(codigo[6:12])/100`. `calcular_peso(total, preco_kg)` = `round(total/preco, 3)`.
- O peso **não está** no código; só o total. Precisa do `preco_kg` do catálogo.

## 3. Conversa do WhatsApp — `services/conversa.py`

Terceira fonte de dados: `código → identidade`, `conversa → quantidade + observações`, `IA → resto`.

- `encontrar_arquivo_conversa()`: primeiro `.txt` ordenado do diretório.
- `parsear_mensagens()`: regex de cabeçalho `dd/mm/aaaa hh:mm - resto`, autor, anexo `(arquivo anexado)`, continuação sem cabeçalho = legenda, filtra ruído, remove U+200E.
- `construir_contextos()` — 3 regras: (1) legenda própria, (2) texto seguinte até próxima imagem dentro de 15 min, (3) menção `IMG-*.jpg` em qualquer ponto. Depois `quantidade = extrair_quantidade(texto)`.
- `extrair_quantidade()`: padrões `N+un/und/cx/pct/...`, `xN/Nx`, linha só-número, range 1–9999. **Ignora** linhas com `kg/g/R$` — `0,738kg` é peso, não quantidade.

## 4. Catálogo — `services/catalogo.py`

Tradução código→produto + fator interno `preco_kg` (nunca exibido; só `peso = total/preco`).

- `ean`: nome+marca. `plu` (5 dígitos): `preco_kg` + categoria `Avarias`.
- Escrita não-destrutiva (`registrar()`): vazio nunca apaga preenchido.
- `aprender()` (origem `ia`): alimenta pelo híbrido. `aprender_preco_kg()`: valida peso 0,02–30 kg; fora disso → `propor_revisao()` (fila `catalogo_revisoes`), não aprende.
- `esta_desatualizado(atualizado_em, dias=30)`: protege contra preço mudado silenciosamente.
- `popular_do_historico()`: backfill idempotente (`INSERT OR IGNORE`, sem bump) só com `ean13_valido` — histórico da IA contém DVs quebrados que não podem poluir o catálogo.

## 5. IA — `services/ai.py` + `ai_extraction.py`

- `AIProvider`: `temperatura 0.1, max_tokens 4000, timeout 60`, `gerar_conteudo(partes)->(texto, tokens)`. Gemini usa `response_mime_type=json` + thinking budget zerado em 2.x; OpenAI com retry sem `response_format`; Claude soma input+output; OpenRouter via base URL. Cache de modelos 600s.
- `PROMPT_INSTRUCAO`: **REGRA DE OURO texto>imagem**. Cenário 1 texto descreve → extrai do texto; Cenário 2 texto vazio + etiqueta legível → extrai da imagem; Cenário 3 impossível → Erro. Saída `{arquivo: {tipo, itens:[{produto,peso,marca,codigo_barras,quantidade}]}}`.
- `extrair_dados_de_lote()`: valida `PIL.Image.verify` (corrompida vira Erro sem derrubar o lote), retry 3×/5s, `_extrair_json_da_resposta` tolera cercas ```json, falha total → Erro "Falha na API".
- `processar_resultado_arquivo()`: `Misto` → split por `item.categoria` (qualquer item sem categoria ou lista vazia → Erro); `Avaria+itens` → `_processar_avaria` (Produto, Quantidade default 1, Peso, Observação, Caminho, Ver); `Uso Interno+itens` → idem com Marca+Código; senão Erro (inclui Avaria/Uso sem itens → "sem itens").

## 6. Motores — `services/extraction_engines.py`

Mesmo contrato de saída; resto do pipeline não sabe qual motor produziu.

- `MotorIA`: delega + `_aplicar_quantidade` + `_aprender_do_resultado`.
- `MotorCodigoBarras.processar_imagem()`:
  - `RuntimeError` (sem deps) → Erro; `[]` → Erro "Nenhum código legível".
  - Por código: balança → `_item_de_balanca` (sempre bucket **Avaria**, peso formatado `0,738kg` ou `N/A`, guarda `_catalogo_atualizado_em` interno); EAN → `buscar` + `_categoria_do_contexto` ou `_categoria_catalogo`, senão **Erro orientando** (nunca assume).
  - Agrega por categoria: ambos → `Misto` (com `categoria` por item); um só → respectivo tipo.
- `_categoria_do_contexto()`: keywords avaria (`avaria/avariado/quebrado/estragado/danificado/vencido/perda/descarte`) e uso interno (`uso interno/consumo interno/para equipe/funcionários`).
- `MotorHibrido`: roda barras em tudo; `_precisa_de_ia()` = tipo Erro, ou balança com peso `N/A`, ou `esta_desatualizado(...)`; pendentes → IA + quantidade + aprendizado.
- `_aplicar_quantidade()`: só preenche item sem quantidade. `_aprender_do_resultado()`: só `ean13_valido`; balança deriva `preco_kg=total/peso_IA` (ou registra PLU); EAN aprende produto/marca/categoria. Exceção no aprendizado nunca quebra o processamento.
- `construir_motor()`: fallback seguro para IA se barras indisponível; erros claros se provider faltando.

## 7. Pipeline — `services/extraction_pipeline.py`

- `main(modo_extracao)`: config (`tamanho_lote 12, max_workers, request_delay, dias_para_reverificar`), motor, pendentes, `iniciar_execucao`, contextos, `ThreadPool` por lote → resultado → persistência → log → arquivamento (só sucesso). Cancelamento via `.cancel_processing`. Finaliza com tokens.
- `reanalisar_erros()`: lê `obter_arquivos_com_erro()` do Excel, sempre IA, remove do Excel se sucesso, arquiva, `log_reanalise.txt`.
- `reanalisar_execucao(run_id, categorias=None, item_ids=None)`: dedup por caminho, `iniciar_reanalise_de_execucao` (versão max+1), reaproveita observação do DB, remove linhas antigas por caminho (após backup) e reinsere. **Seletiva**: com `categorias` (ex.: `["Erros de Análise"]`) ou `item_ids` (ids do banco, precedência sobre categorias), só a seleção vai para a IA e o resto é **copiado intacto** (`_item_db_para_linha`) para a nova versão — cada versão continua representando a execução inteira. Validação em `_validar_categorias` (categoria inválida/lista vazia/id fora da execução → `ValueError`).
- `reanalisar_selecao_mestre(imagens=None, categorias=None, ...)`: mesma ideia para o Excel acumulado (telas Relatório/Editar, sem execução): `imagens` (nomes) tem precedência; sem elas, `categorias` deriva as imagens das abas; sem nenhum → `ValueError`. Substitui as linhas daquelas imagens no Excel e arquiva sucessos, com run `reanalise` no histórico.
- `listar_imagens_pendentes()`: fonte única (nome vs `carregar_logs()`).

## 8. Persistência: Excel + DB

- `excel_report.salvar_relatorio_excel()`: `concat` por aba, `_garantir_quantidade` (legadas → 1), filtra abas vazias (ou `Sem Dados`), escrita atômica temp+`os.replace` via `export_service.escrever_xlsx(..., aplicar_formatacao=True)` (hyperlink Ver Imagem + autofit até 60).
- `db.py`: runs versionadas (`raiz_execucao_id`, `versao`), `registrar_itens()` mapeia colunas, CRUD de edição + `recalcular_contagens`, unificados (`registrar_relatorio_unificado`, `backfill`), `resumo_geral()` (DB + Excel sem dupla contagem).

## 9. Unificação — `services/unification.py` (pura, sem I/O)

- Helpers: `normalizar_texto` (lower, sem acento), `extrair_peso_de_valor` (`500g→0.5`, sem unidade=`kg`, `N/A→None`), `extrair_quantidade_de_observacao` (legado), `extrair_codigo_barras_de_detalhes` (legado).
- `unificar_itens_avarias(df)`: chave nome normalizado; peso>0 soma `quantidade_kg` senão soma `quantidade_linha` (ou 1); saída `Quantidade Total = "X,XXX kg"` ou `"N un"` + `Qtd_Registros_Consolidados` + auditoria.
- `unificar_itens_uso_interno(df)`: chave **só código**; inválidos (`N/A/-/vazio`) cada um sua linha; quantidade = `Quantidade` ou fallback observação; nome exibido = mais frequente; saída `[Produto, Quantidade Total, Código]` + auditoria.
- Usada pela rota `/api/unificar_relatorio`, `execucao_export` e `db.resumo_geral`.

## 10. Exemplos canônicos

- Balança real: `2001400005167` → PLU `00140`, R$ 5,16; com `preco_kg=6.99` → `0,738kg`, Avaria.
- EAN sem contexto e sem cadastro → Erro ("não informa se é Avaria ou Uso Interno").
- EAN + texto "uso interno" → Uso Interno (quantidade do texto).
- Balança sem preço → Avaria `N/A` no sem IA; híbrido manda para IA e aprende `preco_kg`.
- IA com peso `50kg` num tomate → não aprendido; vai para revisão.
- `COENTRO`/`coentro`/`Coentro` → mesma chave na unificação; `500g` + `1kg` → `1,500 kg`.
