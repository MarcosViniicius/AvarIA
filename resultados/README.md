# Pasta de resultados

Esta pasta contém os relatórios e logs gerados pela aplicação.

## Arquivos gerados:
- `Relatorio_Mestre_Produtos.xlsx` - Relatório principal em Excel
- `log_consumo_tokens.txt` - Log de consumo de tokens da API
- `log_mestre.txt` - Log de arquivos processados
- Backups automáticos (*.bak)

## Nota para Vercel:
- Esta pasta será criada dinamicamente no ambiente `/tmp/`
- Os arquivos são temporários devido às limitações da Vercel
- Para persistência, considere integração com serviços de armazenamento externos