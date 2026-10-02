# AvarIA — Identidade da marca

Guia curto de como escrever e aplicar o nome do produto. Vale para UI, relatórios,
documentação, commits e comunicação.

## Nome

- **Marca:** `AvarIA` (sempre com **IA** em caixa alta).
- **Leitura:** "avaria" — o "IA" é a assinatura visual de inteligência artificial.
- **Artigo:** "o AvarIA" (o sistema). Ex.: "o AvarIA gerou o relatório".
- **Slug técnico:** `avariaia` — pacote Python, pasta do projeto, build e deploy.
- **Repositório:** `avariaia` (renomear no GitHub; ver `MIGRACAO_NOME.md`).

## Tagline

> **As perdas da loja à vista.**

Usos: README, página inicial, descrição de repositório. Não repetir a tagline em
toda tela — ela acompanha a marca, não substitui o nome.

## O que evitar

- `Auto Avaria`, `autoavaria`, `Avaria IA`, `AvariaIA`, `Avar IA`, `Avaria iA`.
- Usar a marca para nomear as **categorias** do relatório: elas continuam sendo
  **Avaria**, **Uso Interno** e **Erro** (sem "IA").
- Traduzir o nome ("AvarIA IA" é redundante) ou flexioná-lo ("AvarIAs").

## Onde a marca aparece

| Lugar | Como |
|---|---|
| UI | navbar `AvarIA`; títulos `Página · AvarIA`; rodapé com a tagline; `<meta description>` |
| Relatórios TXT | título `AvarIA — <título>` + linha `Gerado por AvarIA` |
| Código | pacote `avariaia`; exceção base `AvarIAError` |
| Banco | `database/avariaia.db` (o legado `autoavaria.db` vira `.bak` no primeiro boot) |
| Favicon/ícone | lente/câmera atual serve; `aria-label="AvarIA"` |

## Tom de voz

- **Interface do usuário:** direto e operacional, focada no problema da loja
  ("perdas", "avarias", "uso interno"). Sem jargão de IA.
- **Documentação técnica:** pode citar IA, provedores e código de barras normalmente.
- **Comunicação da marca:** uma frase, um benefício. Ex.: "As perdas da loja à vista."
