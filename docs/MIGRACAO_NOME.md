# Migração do nome: Auto Avaria → AvarIA

Registro do rebrand feito em **out/2026** (branch `rebrand-avariaia`, três commits:
rename do pacote, marca na UI/banco/relatórios e documentação).

## Antes e depois

| Item | Antes | Depois |
|---|---|---|
| Marca | Auto Avaria / "Analisador de Avarias" | **AvarIA** |
| Tagline | — | **As perdas da loja à vista** |
| Pacote Python | `autoavaria` | `avariaia` |
| Exceção base | `AutoAvariaError` | `AvarIAError` (alias antigo mantido) |
| Banco SQLite | `database/autoavaria.db` | `database/avariaia.db` |
| Tema (localStorage) | `autoavaria-theme` | `avariaia-theme` (fallback para a antiga) |
| Rota estática no Vercel | `/static/...` → `autoavaria/static` | `/static/...` → `avariaia/static` |
| Repositório | `MarcosViniicius/autoavaria` | `MarcosViniicius/AvarIA` (renomeado no GitHub; o antigo redireciona) |

## Compatibilidades mantidas (de propósito)

- **Exceção:** `AutoAvariaError = AvarIAError` continua importável.
- **Banco:** na primeira execução após a atualização, o boot copia
  `database/autoavaria.db` para `database/avariaia.db` e renomeia o antigo para
  `autoavaria.db.bak`. É idempotente (só roda se o novo ainda não existir) e, se a
  cópia falhar, o boot **aborta com erro** em vez de iniciar com banco vazio.
- **Tema:** a chave nova é lida primeiro, mas a antiga ainda é usada como fallback —
  ninguém perde a preferência claro/escuro.
- **Intocados:** todas as rotas HTTP, a URL pública do invertexto
  (`https://www.invertexto.com/autoava`), os nomes dos arquivos exportados
  (`Relatorio_Unificado_*`, `Historico_Execucao_*`) e o esquema/tabelas do banco.
- **Histórico:** os documentos datados em `docs/superpowers/` não foram reescritos —
  são registro do que foi planejado na época, com os caminhos antigos.

## Passos manuais (fora do código)

1. **GitHub (feito):** repositório renomeado para `MarcosViniicius/AvarIA`; o remote
   local já aponta para o endereço novo. O GitHub redireciona o nome antigo.
2. **Vercel (opcional):** renomear o projeto no dashboard. O deploy usa `vercel.json`,
   já atualizado para `/avariaia/static/...`.
3. **Deploy/reinício:** na próxima subida, a migração do banco roda sozinha e imprime
   `📦 Banco migrado: autoavaria.db -> avariaia.db (backup preservado)`.

## Rollback

- **Código:** `git revert` dos commits do rebrand (ou voltar para a branch anterior).
- **Banco:** parar o app e renomear `database/avariaia.db` de volta para
  `database/autoavaria.db` (ou restaurar o conteúdo de `autoavaria.db.bak`).
- Nenhum dado é apagado em nenhum passo da migração.

## Verificação feita

- Suíte completa verde (638 testes, incluindo 3 novos da migração do banco).
- Smoke das páginas (`/`, `/upload`, `/relatorio`, `/historico`, `/editar_dados`,
  `/configuracoes`) com título contendo "AvarIA".
- Migração validada na base real: `avariaia.db` idêntico ao legado (mesmo hash) e
  `autoavaria.db.bak` preservado.
- TXT gerado conferido: título `AvarIA — ...` e linha `Gerado por AvarIA`.
