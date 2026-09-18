# Sincronização de indicadores PMO → Google Sheets (Bay Area 2026/2)

Este pacote sincroniza automaticamente, todo dia via GitHub Actions, dois
conjuntos de dados dos repositórios Chat, Prontuário e Time Tracker:

1. **`sync_dependabot_to_sheets.py`** — alertas do Dependabot → aba
   **🔒 Segurança**.
2. **`sync_code_churn.py`** — estatísticas semanais de linhas adicionadas e
   removidas (churn de código) → aba **🛠 Desenvolvimento**.

Os dois usam o mesmo token do GitHub (`DEPENDABOT_PAT`) e a mesma Service
Account do Google — não precisa configurar nada em duplicidade. O nome do
secret `DEPENDABOT_PAT` ficou assim por ter sido criado primeiro; ele serve
para os dois scripts.

> ⚠️ **Churn de código não é um indicador de qualidade de código isolado** —
> ele mede o quanto de código é reescrito logo depois de escrito. Um churn
> alto pode significar retrabalho, mas também pode significar refino natural
> em uma sprint de descoberta. Trate como um sinal para investigar, não como
> um veredito automático — a mesma lógica que já vale para os RAGs das
> outras abas.

## O que este script faz — e o que NÃO faz

✅ Preenche automaticamente: ID, Produto, Descrição, Data de Identificação,
Data de Aceitação do Risco (quando o alerta for dispensado com motivo
"tolerable_risk") e Método de Detecção (sempre "Automatizado").

⚠️ **Não preenche** "Data de Início do Tratamento" — a API do Dependabot não
tem um campo equivalente a esse marco. Se sua equipe quiser acompanhar essa data,
ela precisa ser lançada manualmente na linha correspondente.

⚠️ **Não alimenta o lado "manual" do Índice de Detecção Manual** — como o
Dependabot é detecção automatizada por definição, vulnerabilidades encontradas
por teste manual (pentest, revisão de código, etc.) continuam precisando ser
lançadas à mão na mesma tabela para que esse indicador tenha sentido.

✅ **Nunca sobrescreve linhas preenchidas manualmente** — só cria ou atualiza
linhas cujo ID já siga o padrão `CHAT-`, `PRONT-` ou `TT-` (gerado por este
script). Qualquer linha com outro ID (ex.: um teste manual que você nomeou)
fica intocada.

---

## Passo a passo de configuração

### 1. Criar o Personal Access Token do GitHub (leitura dos alertas)

1. Acesse **GitHub → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
2. Dê acesso aos 3 repositórios (`Chat-2026-2`, `Prontuario`, `TimeTracker-2026-2`).
3. Em **Repository permissions**, habilite **Dependabot alerts: Read-only** (para o script de Segurança) **e Contents: Read-only** (para o script de Churn de Código, que lê estatísticas de commits).
4. Gere o token e copie o valor (ele só aparece uma vez).

> Se algum desses repositórios pertencer a uma organização com políticas de
> segurança mais restritas, pode ser necessário um administrador da
> organização aprovar o token.

### 2. Criar a Service Account do Google (escrita na planilha)

1. No [Google Cloud Console](https://console.cloud.google.com/), crie um
   projeto (ou use um existente).
2. Ative as APIs **Google Sheets API** e **Google Drive API**.
3. Vá em **IAM & Admin → Service Accounts → Create Service Account**.
4. Crie uma chave para essa conta no formato **JSON** e baixe o arquivo.
5. Abra o arquivo JSON e copie o valor de `"client_email"`.
6. Na sua planilha do Google Sheets, clique em **Compartilhar** e adicione
   esse e-mail como **Editor**.

### 3. Pegar o ID da planilha

Na URL do Google Sheets, o ID é o trecho entre `/d/` e `/edit`:
`https://docs.google.com/spreadsheets/d/**ESTE_TRECHO**/edit`

### 4. Configurar os secrets no repositório onde este workflow vai rodar

Em **Settings → Secrets and variables → Actions → New repository secret**,
crie três secrets:

| Nome do secret | Valor |
|---|---|
| `DEPENDABOT_PAT` | o token gerado no passo 1 |
| `GOOGLE_SHEET_ID` | o ID da planilha (passo 3) |
| `GCP_SERVICE_ACCOUNT_JSON` | o **conteúdo completo** do arquivo JSON do passo 2 (cole o JSON inteiro como valor do secret) |

### 5. Colocar os arquivos no repositório

Copie para o repositório que vai rodar a automação:
- `sync_dependabot_to_sheets.py` (raiz do repositório)
- `requirements.txt` (raiz do repositório)
- `.github/workflows/sync-seguranca.yml`

### 6. Testar manualmente antes de confiar no agendamento

Vá em **Actions → Sincronizar indicadores de Segurança → Run workflow** para
rodar uma vez na mão e conferir se a aba 🔒 Segurança foi preenchida
corretamente antes de deixar no automático.

---

## Frequência

O workflow está configurado para rodar todo dia às 04:00 (horário de
Brasília). Para mudar, edite a linha `cron:` no arquivo do workflow
(formato: minuto hora dia mês dia-da-semana, sempre em UTC).

## Se algo der errado

- **Erro 403/404 ao buscar alertas de um repositório**: confirme que o
  Dependabot alerts está habilitado no repositório (Settings → Security →
  Code security) e que o token tem a permissão certa.
- **Erro de autenticação no Google Sheets**: confirme que o e-mail da
  Service Account foi mesmo adicionado como Editor na planilha.
- **"Tabela sem linhas livres"**: a tabela de vulnerabilidades na aba
  🔒 Segurança vai da linha 21 à 220 (200 linhas). Se esgotar, é preciso
  expandir esse intervalo na planilha e nas fórmulas de resumo.
