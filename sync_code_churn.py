#!/usr/bin/env python3
"""
Sincroniza estatísticas semanais de adições/remoções de código (churn) dos
repositórios do Bay Area 2026/2 para a aba "🛠 Desenvolvimento" no Google Sheets.

Usa o endpoint de estatísticas do próprio GitHub:
  GET /repos/{owner}/{repo}/stats/code_frequency
que devolve, por semana, [timestamp_unix, adições, remoções] (remoções vêm negativas).

Observação sobre a API: o GitHub computa essas estatísticas de forma assíncrona.
Na primeira chamada após um tempo sem uso, ela pode devolver 202 (processando) —
o script tenta novamente algumas vezes antes de desistir.

Churn (%) = remoções / (adições + remoções) na semana — calculado por fórmula
já existente na planilha (coluna G); este script só escreve as colunas de
adições e remoções.
"""

import os
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

REPO_PRODUCT_MAP = {
    "fabrica-bayarea/Chat-2026-2":        "Projeto Chat",
    "fabrica-bayarea/Prontuario":         "Projeto Prontuário",
    "fabrica-bayarea/TimeTracker-2026-2": "Projeto Time Tracker",
}

SHEET_TAB_NAME = "🛠 Desenvolvimento"
DATA_START_ROW = 52
DATA_END_ROW = 111
COL_SEMANA, COL_PRODUTO, COL_ADICOES, COL_REMOCOES = "C", "D", "E", "F"

GITHUB_TOKEN = os.environ["DEPENDABOT_PAT"]  # o mesmo token do fluxo de Segurança serve aqui
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GCP_SERVICE_ACCOUNT_JSON"]

GITHUB_API = "https://api.github.com"
MAX_RETRIES = 6
RETRY_WAIT_SECONDS = 10


def fetch_code_frequency(owner_repo: str):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{GITHUB_API}/repos/{owner_repo}/stats/code_frequency"
    for attempt in range(MAX_RETRIES):
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 202:
            print(f"  [info] GitHub ainda calculando estatísticas de {owner_repo}, "
                  f"tentando de novo em {RETRY_WAIT_SECONDS}s ({attempt+1}/{MAX_RETRIES})...")
            time.sleep(RETRY_WAIT_SECONDS)
            continue
        if resp.status_code == 404:
            print(f"  [aviso] Repositório {owner_repo} não encontrado ou sem permissão.")
            return []
        resp.raise_for_status()
        return resp.json()
    print(f"  [erro] Estatísticas de {owner_repo} não ficaram prontas a tempo. Rode de novo mais tarde.")
    return []


def main():
    creds_info = __import__("json").loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.worksheet(SHEET_TAB_NAME)

    # Lê linhas existentes para não duplicar (chave: data da semana + produto)
    existing = ws.get(f"{COL_SEMANA}{DATA_START_ROW}:{COL_PRODUTO}{DATA_END_ROW}")
    # A API do Sheets corta linhas em branco no final do intervalo pedido — sem
    # completar (pad) a lista, o script "acha" menos linhas livres do que existem.
    expected_len = DATA_END_ROW - DATA_START_ROW + 1
    existing += [[] for _ in range(expected_len - len(existing))]
    key_to_row = {}
    free_rows = []
    for i, row in enumerate(existing):
        rownum = DATA_START_ROW + i
        if len(row) >= 2 and row[0] and row[1]:
            key_to_row[(row[0], row[1])] = rownum
        else:
            free_rows.append(rownum)
    free_iter = iter(free_rows)

    updates = []
    total = 0
    for owner_repo, produto in REPO_PRODUCT_MAP.items():
        print(f"Buscando code_frequency de {owner_repo} ...")
        weeks = fetch_code_frequency(owner_repo)
        # Só as últimas 12 semanas, para não sobrecarregar a tabela
        for week_ts, additions, deletions in weeks[-12:]:
            week_date = datetime.fromtimestamp(week_ts, tz=timezone.utc).strftime("%d/%m/%Y")
            key = (week_date, produto)
            row_num = key_to_row.get(key)
            if row_num is None:
                try:
                    row_num = next(free_iter)
                except StopIteration:
                    print("  [erro] Tabela de churn sem linhas livres — expanda o intervalo na planilha.")
                    continue
                key_to_row[key] = row_num
            values = [week_date, produto, additions, abs(deletions)]
            updates.append({"range": f"{COL_SEMANA}{row_num}:{COL_REMOCOES}{row_num}", "values": [values]})
            total += 1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    print(f"\nSincronização concluída: {total} semana(s)/produto processado(s).")


if __name__ == "__main__":
    main()
