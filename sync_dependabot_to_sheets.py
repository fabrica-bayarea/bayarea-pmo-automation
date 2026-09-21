#!/usr/bin/env python3
"""
Sincroniza alertas do Dependabot (GitHub) dos repositórios do Bay Area 2026/2
para a aba "🔒 Segurança" da planilha de acompanhamento no Google Sheets.

Mapeamento de colunas na aba (linhas de dados: 21 a 220):
  C = ID              D = Produto           E = Descrição
  F = Data Identificação   G = Data Início Tratamento   H = Data Aceitação do Risco
  I, J = fórmulas (NÃO são escritas por este script)
  K = Método de Detecção

Regras:
- Só cria/atualiza linhas cujo ID comece com um prefixo conhecido (CHAT-, PRONT-, TT-).
  Linhas preenchidas manualmente (ex.: VUL-001, ou testes manuais) nunca são sobrescritas.
- "Data Início Tratamento" só é preenchida quando a API do GitHub fornecer uma data
  com confiança razoável; caso contrário, fica em branco (não inventamos o dado).
- "Método de Detecção" é sempre "Automatizado" para registros vindos do Dependabot.
"""

import os
import sys
import requests
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Configuração — ajuste aqui se mudar de repositório ou de planilha
# ---------------------------------------------------------------------------
REPO_PRODUCT_MAP = {
    "fabrica-bayarea/Chat-2026-2":       {"prefix": "CHAT",  "produto": "Projeto Chat"},
    "fabrica-bayarea/Prontuario":        {"prefix": "PRONT", "produto": "Projeto Prontuário"},
    "fabrica-bayarea/TimeTracker-2026-2":{"prefix": "TT",    "produto": "Projeto Time Tracker"},
}

SHEET_TAB_NAME = "🔒 Segurança"
DATA_START_ROW = 21
DATA_END_ROW = 220
COL_ID, COL_PRODUTO, COL_DESC = "C", "D", "E"
COL_DATA_IDENT, COL_DATA_INICIO, COL_DATA_ACEITE = "F", "G", "H"
COL_METODO = "K"
COL_SEVERIDADE = "L"
COL_LINK = "M"

GITHUB_TOKEN = os.environ["DEPENDABOT_PAT"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GCP_SERVICE_ACCOUNT_JSON"]  # conteúdo do JSON, não o caminho

GITHUB_API = "https://api.github.com"


def fetch_dependabot_alerts(owner_repo: str):
    """Busca todos os alertas do Dependabot (todas as páginas) de um repositório."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    alerts = []
    # Sem filtro "state": a API já retorna todos os estados por padrão.
    # "state=all" NÃO é um valor válido para este endpoint (só aceita
    # open/fixed/dismissed/auto_dismissed) — usá-lo faz a API devolver 0 resultados.
    url = f"{GITHUB_API}/repos/{owner_repo}/dependabot/alerts?per_page=100"
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            print(f"  [aviso] Dependabot alerts não habilitado ou sem permissão em {owner_repo} (404).")
            return []
        if resp.status_code == 403:
            print(f"  [erro] Sem permissão para ler alertas em {owner_repo} (403). "
                  f"Confirme o escopo do token e se o Dependabot alerts está habilitado no repositório.")
            return []
        resp.raise_for_status()
        alerts.extend(resp.json())
        # paginação via header Link
        url = None
        if "next" in resp.links:
            url = resp.links["next"]["url"]
    return alerts


def map_alert_to_row(alert: dict, prefix: str, produto: str, owner_repo: str) -> dict:
    number = alert.get("number")
    state = alert.get("state")  # open | fixed | dismissed | auto_dismissed
    dismissed_reason = alert.get("dismissed_reason")  # fix_started | inaccurate | no_bandwidth | not_used | tolerable_risk
    advisory = alert.get("security_advisory", {}) or {}
    severity_raw = (advisory.get("severity") or "").lower()
    dependency = alert.get("dependency", {}) or {}
    package = dependency.get("package", {}) or {}
    pacote = package.get("name", "(pacote desconhecido)")
    ecosystem = package.get("ecosystem", "")

    # Mapeia severidade do GitHub (inglês) para rótulo em português, compatível
    # com o dropdown já existente na coluna Severidade da planilha.
    severidade_map = {"low": "Baixa", "medium": "Média", "high": "Alta", "critical": "Crítica"}
    severidade = severidade_map.get(severity_raw, severity_raw.capitalize() or "—")

    data_identificacao = alert.get("created_at")
    data_aceite = None
    if state == "dismissed" and dismissed_reason == "tolerable_risk":
        data_aceite = alert.get("dismissed_at")

    # "Início do tratamento" não tem correspondência confiável na API — deixamos em branco
    # por padrão. Ajuste esta lógica se sua organização definir um proxy aceitável.
    data_inicio = None

    # Sem resumo técnico completo por decisão de segurança: a descrição aqui é
    # só o nome do pacote/ecossistema, o que já dá contexto de gestão sem
    # revelar como o problema pode ser explorado. O detalhe técnico completo
    # fica só atrás do link, que exige acesso ao repositório no GitHub.
    descricao = f"{pacote} ({ecosystem})" if ecosystem else pacote
    link = f"https://github.com/{owner_repo}/security/dependabot/{number}"

    return {
        "id": f"{prefix}-{number}",
        "produto": produto,
        "descricao": descricao[:300],
        "severidade": severidade,
        "link": link,
        "data_identificacao": data_identificacao,
        "data_inicio": data_inicio,
        "data_aceite": data_aceite,
        "metodo": "Automatizado",
    }


def to_sheets_date(iso_str):
    if not iso_str:
        return ""
    # gspread/Sheets aceita string de data; convertendo para DD/MM/AAAA para casar com o formato da planilha
    from datetime import datetime
    dt = datetime.strptime(iso_str[:10], "%Y-%m-%d")
    return dt.strftime("%d/%m/%Y")


def main():
    creds_info = __import__("json").loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.worksheet(SHEET_TAB_NAME)

    # Lê o bloco de dados atual (IDs já existentes) para decidir update x insert
    existing_ids = ws.get(f"{COL_ID}{DATA_START_ROW}:{COL_ID}{DATA_END_ROW}")
    # A API do Sheets corta linhas em branco no final do intervalo pedido — sem
    # completar (pad) a lista, o script "acha" menos linhas livres do que existem.
    expected_len = DATA_END_ROW - DATA_START_ROW + 1
    existing_ids += [[] for _ in range(expected_len - len(existing_ids))]
    id_to_row = {}
    for i, row in enumerate(existing_ids):
        if row and row[0]:
            id_to_row[row[0]] = DATA_START_ROW + i

    # Linhas com só o ID placeholder (VUL-001, VUL-002...) e nenhum outro dado
    # preenchido (Produto/Descrição/datas) contam como livres — esse ID nunca
    # foi um dado real, é só numeração decorativa herdada do modelo da aba.
    existing_full = ws.get(f"{COL_ID}{DATA_START_ROW}:{COL_DATA_ACEITE}{DATA_END_ROW}")
    existing_full += [[] for _ in range(expected_len - len(existing_full))]

    def has_real_data(row):
        # colunas depois do ID (Produto, Descrição, datas) — índices 1 em diante
        return any(v for v in row[1:5])

    truly_free = [
        DATA_START_ROW + i for i, row in enumerate(existing_full) if not has_real_data(row)
    ]
    free_iter = iter(truly_free)

    updates = []  # (a1_range, values)
    total_synced = 0

    for owner_repo, cfg in REPO_PRODUCT_MAP.items():
        print(f"Buscando alertas do Dependabot em {owner_repo} ...")
        alerts = fetch_dependabot_alerts(owner_repo)
        print(f"  {len(alerts)} alerta(s) encontrados.")
        for alert in alerts:
            record = map_alert_to_row(alert, cfg["prefix"], cfg["produto"], owner_repo)
            row_num = id_to_row.get(record["id"])
            if row_num is None:
                try:
                    row_num = next(free_iter)
                except StopIteration:
                    print("  [erro] Tabela de vulnerabilidades sem linhas livres (limite de "
                          f"{DATA_END_ROW - DATA_START_ROW + 1} linhas atingido). Expanda o intervalo na planilha.")
                    continue
                id_to_row[record["id"]] = row_num

            values = [
                record["id"], record["produto"], record["descricao"],
                to_sheets_date(record["data_identificacao"]),
                to_sheets_date(record["data_inicio"]),
                to_sheets_date(record["data_aceite"]),
            ]
            updates.append({"range": f"{COL_ID}{row_num}:{COL_DATA_ACEITE}{row_num}", "values": [values]})
            updates.append({
                "range": f"{COL_METODO}{row_num}:{COL_LINK}{row_num}",
                "values": [[record["metodo"], record["severidade"], record["link"]]],
            })
            total_synced += 1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    print(f"\nSincronização concluída: {total_synced} alerta(s) processado(s).")


if __name__ == "__main__":
    main()
