"""
Script de ingestão automatizada de questões — Caderneta de Estudos.

Lê todo arquivo .json dentro de questions_batch/ (cada um contendo uma
lista de questões), valida os campos obrigatórios e registra cada
questão na tabela `question_bank` do Supabase, com tentativas de
reenvio (retry) em caso de falha de rede ou instabilidade do servidor.

Uso local:
    export SUPABASE_URL="https://SEU-PROJETO.supabase.co"
    export SUPABASE_SERVICE_ROLE_KEY="sua-service-role-key"
    pip install -r requirements.txt
    python ingest_questions.py

No GitHub Actions, as mesmas variáveis vêm de Settings > Secrets and
variables > Actions (veja .github/workflows/ingest.yml).

IMPORTANTE: a service_role key ignora as políticas de RLS — nunca a
coloque no front-end (index.html). Ela deve existir só aqui, como
secret do repositório.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BATCH_DIR = Path(__file__).parent / "questions_batch"
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2
REQUIRED_FIELDS = ["discipline", "topic", "statement", "options", "correct_answer"]


def check_env() -> None:
    """Garante que as credenciais do Supabase foram configuradas antes de continuar."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print(
            "ERRO: defina as variáveis de ambiente SUPABASE_URL e "
            "SUPABASE_SERVICE_ROLE_KEY antes de rodar este script."
        )
        sys.exit(1)


def check_connection() -> bool:
    """Faz um ping simples na API REST do Supabase antes de iniciar o lote,
    usando `requests` diretamente (falha rápido se a rede/projeto estiver fora)."""
    attempt = 0
    while attempt < MAX_RETRIES:
        attempt += 1
        try:
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/",
                headers={"apikey": SUPABASE_SERVICE_ROLE_KEY},
                timeout=10,
            )
            if resp.status_code < 500:
                return True
            print(f"  ping retornou status {resp.status_code}, tentando de novo...")
        except requests.RequestException as exc:
            print(f"  falha de conexão ({exc}), tentativa {attempt}/{MAX_RETRIES}...")
        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    return False


def load_batches() -> list:
    """Lê cada arquivo .json de questions_batch/ e junta tudo em uma lista única."""
    if not BATCH_DIR.exists():
        print(f"Pasta não encontrada: {BATCH_DIR}")
        return []

    all_questions = []
    for file_path in sorted(BATCH_DIR.glob("*.json")):
        try:
            with open(file_path, encoding="utf-8") as f:
                items = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Erro ao ler {file_path.name}: {exc}")
            continue

        if not isinstance(items, list):
            print(f"Aviso: {file_path.name} não contém uma lista de questões, ignorando.")
            continue

        for item in items:
            item["_source_file"] = file_path.name
        all_questions.extend(items)
        print(f"Lidas {len(items)} questões de {file_path.name}")

    return all_questions


def validate_question(question: dict) -> list:
    """Retorna a lista de campos obrigatórios que estão faltando (vazia = válida)."""
    return [field for field in REQUIRED_FIELDS if not question.get(field)]


def insert_with_retry(client: Client, question: dict) -> bool:
    """Insere uma questão no Supabase, tentando de novo em caso de erro de
    rede/servidor, com espera crescente entre as tentativas."""
    payload = {
        "discipline": question["discipline"],
        "topic": question["topic"],
        "statement": question["statement"],
        "options": question["options"],
        "correct_answer": question["correct_answer"],
        "explanation": question.get("explanation", ""),
    }

    attempt = 0
    while attempt < MAX_RETRIES:
        attempt += 1
        try:
            client.table("question_bank").insert(payload).execute()
            return True
        except Exception as exc:  # captura falha de rede, timeout, erro do servidor etc.
            wait_seconds = RETRY_BACKOFF_SECONDS * attempt
            print(f"    tentativa {attempt}/{MAX_RETRIES} falhou ({exc}); aguardando {wait_seconds}s...")
            time.sleep(wait_seconds)

    print(f"    FALHOU após {MAX_RETRIES} tentativas: {question.get('statement', '')[:60]}...")
    return False


def main() -> None:
    check_env()

    print("Verificando conexão com o Supabase...")
    if not check_connection():
        print("ERRO: não foi possível conectar ao Supabase após várias tentativas.")
        sys.exit(1)
    print("Conexão OK.\n")

    client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    questions = load_batches()
    if not questions:
        print("Nenhuma questão encontrada em questions_batch/. Nada a fazer.")
        return

    ok_count = 0
    fail_count = 0
    skipped_count = 0

    for i, question in enumerate(questions, start=1):
        missing = validate_question(question)
        if missing:
            print(f"[{i}/{len(questions)}] pulando questão inválida (faltando: {missing})")
            skipped_count += 1
            continue

        print(f"[{i}/{len(questions)}] inserindo: {question['statement'][:60]}...")
        if insert_with_retry(client, question):
            ok_count += 1
        else:
            fail_count += 1

    print("\n--- Resumo da ingestão ---")
    print(f"Inseridas com sucesso: {ok_count}")
    print(f"Falharam:              {fail_count}")
    print(f"Puladas (inválidas):   {skipped_count}")

    if fail_count > 0:
        sys.exit(1)  # sinaliza falha para o GitHub Actions marcar o job como vermelho


if __name__ == "__main__":
    main()
