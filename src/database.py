import os
import sqlite3
import hashlib
from datetime import datetime
import pandas as pd

DB_PATH = os.path.join("data", "applications.db")

def get_connection():
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candidaturas (
                hash_id TEXT PRIMARY KEY,
                empresa TEXT NOT NULL,
                cargo TEXT NOT NULL,
                area TEXT,
                plataforma TEXT,
                data_inscricao TEXT,
                data_retorno TEXT,
                status TEXT,
                obs TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()

def gerar_hash(empresa: str, cargo: str, plataforma: str) -> str:
    chave = f"{empresa.strip().lower()}|{cargo.strip().lower()}|{plataforma.strip().lower()}"
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()

def upsert_candidatura(item: dict) -> tuple[str, dict | None]:
    """
    Retorna ('NOVO', item), ('ATUALIZADO', item) ou ('IGUAL', None)
    """
    hash_id = gerar_hash(item["empresa"], item["cargo"], item["plataforma"])
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cur = conn.execute(
            "SELECT status, obs FROM candidaturas WHERE hash_id = ?",
            (hash_id,)
        )
        row = cur.fetchone()

        if row is None:
            conn.execute("""
                INSERT INTO candidaturas
                (hash_id, empresa, cargo, area, plataforma, data_inscricao, data_retorno, status, obs, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hash_id,
                item["empresa"],
                item["cargo"],
                item.get("area", "Dados / BI"),
                item["plataforma"],
                item.get("data_inscricao", datetime.today().strftime("%Y-%m-%d")),
                item.get("data_retorno", ""),
                item.get("status", "Em Andamento"),
                item.get("obs", ""),
                agora
            ))
            conn.commit()
            return "NOVO", item

        status_antigo, _ = row
        status_novo = item.get("status", status_antigo)

        if status_novo != status_antigo:
            data_retorno = item.get("data_retorno") or datetime.today().strftime("%Y-%m-%d")
            conn.execute("""
                UPDATE candidaturas
                SET status = ?, data_retorno = ?, obs = ?, updated_at = ?
                WHERE hash_id = ?
            """, (status_novo, data_retorno, item.get("obs", ""), agora, hash_id))
            conn.commit()
            item["status_anterior"] = status_antigo
            item["data_retorno"] = data_retorno
            return "ATUALIZADO", item

        return "IGUAL", None

def exportar_para_bi(csv_path: str = "exports/candidaturas_bi.csv"):
    os.makedirs("exports", exist_ok=True)
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT empresa, cargo, area, plataforma, data_inscricao, data_retorno, status, obs
            FROM candidaturas
            ORDER BY data_inscricao DESC
        """, conn)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return len(df)