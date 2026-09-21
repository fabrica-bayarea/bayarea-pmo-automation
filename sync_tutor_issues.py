#!/usr/bin/env python3
"""
Piloto: sincroniza as Issues do repositório público fabrica-bayarea/Tutor
para a aba "🎓 Piloto Tutor" no Google Sheets.

Objetivo: demonstrar, usando um projeto já concluído, como o PMO consegue
indicadores automaticamente quando os times usam GitHub Issues + labels —
sem precisar de nenhuma planilha preenchida à mão.

Conversão de esforço: o Tutor já usa labels de duração em vez de "pontos"
numéricos. Convertemos para uma escala numérica (Fibonacci-like) só para
permitir soma/média — a escala em si é uma escolha nossa, ajuste se quiser
outra proporção.
"""

import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

REPO = "fabrica-bayarea/Tutor"
SHEET_TAB_NAME = "🎓 Piloto Tutor"
DATA_START_ROW = 27
DATA_END_ROW = 226
# C=Nº Issue D=Título E=Label F=Pontos G=Tipo H=Estado I=Abertura J=Fechamento
# K=Tempo de Ciclo (fórmula, não escrita aqui) L=Help Wanted M=Good First Issue
COL_NUM, COL_TITULO, COL_LABEL, COL_PONTOS = "C", "D", "E", "F"
COL_TIPO, COL_ESTADO, COL_ABERTURA, COL_FECHAMENTO = "G", "H", "I", "J"
COL_HELP, COL_GOOD_FIRST = "L", "M"

DURACAO_PONTOS = {
    "Meio período/dia": 1,
    "Um/Dois dias": 2,
    "Três/Quatro dias": 3,
    "Uma semana": 5,
    "Duas semanas": 8,
    "Três semanas": 13,
    "Um mês": 21,
}

GITHUB_TOKEN = os.environ["DEPENDABOT_PAT"]  # mesmo token, precisa de Issues: Read-only neste repo
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GCP_SERVICE_ACCOUNT_JSON"]

GITHUB_API = "https://api.github.com"


def fetch_issues():
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    issues = []
    url = f"{GITHUB_API}/repos/{REPO}/issues?state=all&per_page=100"
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code in (403, 404):
            print(f"  [erro] Não consegui ler Issues de {REPO} ({resp.status_code}). "
                  f"Confirme se o token tem 'Issues: Read-only' neste repositório.")
            return []
        resp.raise_for_status()
        for item in resp.json():
            if "pull_request" in item:
                continue  # a API de issues também retorna PRs; ignoramos
            issues.append(item)
        url = None
        if "next" in resp.links:
            url = resp.links["next"]["url"]
    return issues


def map_issue(issue: dict) -> dict:
    labels = [l["name"] for l in issue.get("labels", [])]
    pontos = 0
    label_duracao = ""
    for nome, valor in DURACAO_PONTOS.items():
        if nome in labels:
            pontos = valor
            label_duracao = nome
            break

    if "bug" in labels:
        tipo = "Bug"
    elif "enhancement" in labels:
        tipo = "Enhancement"
    elif "documentation" in labels:
        tipo = "Documentação"
    else:
        tipo = "Outro"

    return {
        "numero": issue["number"],
        "titulo": issue.get("title", "")[:120],
        "label_duracao": label_duracao,
        "pontos": pontos,
        "tipo": tipo,
        "estado": "Fechada" if issue.get("state") == "closed" else "Aberta",
        "abertura": issue.get("created_at"),
        "fechamento": issue.get("closed_at"),
        "help_wanted": "Sim" if "help wanted" in labels else "Não",
        "good_first_issue": "Sim" if "good first issue" in labels else "Não",
    }


def to_sheets_date(iso_str):
    if not iso_str:
        return ""
    dt = datetime.strptime(iso_str[:10], "%Y-%m-%d")
    return dt.strftime("%d/%m/%Y")


def main():
    creds_info = __import__("json").loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.worksheet(SHEET_TAB_NAME)

    existing = ws.get(f"{COL_NUM}{DATA_START_ROW}:{COL_NUM}{DATA_END_ROW}")
    expected_len = DATA_END_ROW - DATA_START_ROW + 1
    existing += [[] for _ in range(expected_len - len(existing))]

    num_to_row = {}
    free_rows = []
    for i, row in enumerate(existing):
        rownum = DATA_START_ROW + i
        if row and row[0]:
            num_to_row[str(row[0])] = rownum
        else:
            free_rows.append(rownum)
    free_iter = iter(free_rows)

    print(f"Buscando issues de {REPO} ...")
    issues = fetch_issues()
    print(f"  {len(issues)} issue(s) encontrada(s) (PRs excluídos).")

    updates = []
    for issue in issues:
        record = map_issue(issue)
        key = str(record["numero"])
        row_num = num_to_row.get(key)
        if row_num is None:
            try:
                row_num = next(free_iter)
            except StopIteration:
                print("  [erro] Tabela de issues do Tutor sem linhas livres — expanda o intervalo na planilha.")
                continue
            num_to_row[key] = row_num

        values = [
            record["numero"], record["titulo"], record["label_duracao"], record["pontos"],
            record["tipo"], record["estado"], to_sheets_date(record["abertura"]),
            to_sheets_date(record["fechamento"]),
        ]
        updates.append({"range": f"{COL_NUM}{row_num}:{COL_FECHAMENTO}{row_num}", "values": [values]})
        updates.append({
            "range": f"{COL_HELP}{row_num}:{COL_GOOD_FIRST}{row_num}",
            "values": [[record["help_wanted"], record["good_first_issue"]]],
        })

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    print(f"\nSincronização concluída: {len(issues)} issue(s) processada(s).")


if __name__ == "__main__":
    main()
