# 🔄 Funcionalidade de Reanálise de Erros

## ✨ Resumo

Sistema isolado para reanalisar automaticamente itens que falharam durante o processamento, sem afetar dados já processados.

## 🎯 Como Usar

1. **Acesse o Relatório** após executar uma análise
2. **Vá para aba "Erros de Análise"** se houver erros
3. **Clique em "Reanalisar Erros"** 
4. **Acompanhe o progresso** no modal exibido
5. **Clique em "Atualizar Relatório"** ao final

## 📁 Arquivos Novos/Modificados

### Criados
- `src/gerenciador_erros.py` - Gerenciador de erros isolado
- `docs/REANALISE_ERROS.md` - Documentação completa
- `logs/log_reanalise.txt` - Log específico de reanálise

### Modificados
- `src/extrair-dados.py` - Adicionada função `reanalisar_erros()`
- `app.py` - 3 novas rotas de API para reanálise
- `templates/relatorio.html` - Botão e modal de reanálise

## 🔒 Garantias

✅ **Não afeta processamento principal**  
✅ **Não modifica dados já processados**  
✅ **Funciona de forma isolada**  
✅ **Pode ser removido sem impacto**

## 📊 APIs Adicionadas

- `GET /api/obter_erros_pendentes` - Lista erros
- `POST /api/reanalisar_erros` - Inicia reanálise
- `GET /api/progresso_reanalise` - Monitor progresso

## 📖 Documentação Completa

Veja [docs/REANALISE_ERROS.md](docs/REANALISE_ERROS.md) para detalhes técnicos completos.

---

**Versão:** 1.0 | **Data:** 24/01/2026
