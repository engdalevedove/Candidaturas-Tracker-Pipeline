import os
import re
import sqlite3
import hashlib
from datetime import datetime
import pandas as pd

DB_PATH = os.path.join("data", "applications.db")
STATUS_TERMINAIS = {"Não Avançou", "Contratado / Aprovado", "Vaga Cancelada"}


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


def _normalizar_empresa(nome: str) -> str:
    n = re.sub(r"[^a-z0-9\s]", " ", (nome or "").lower())
    stopwords = {"ltda", "sa", "s", "a", "inc", "corp", "communications", "brasil", "brazil", "group", "grupo", "rh", "recruiting", "talent"}
    tokens = [t for t in n.split() if t and t not in stopwords]
    return " ".join(tokens).strip()


def _buscar_match_cruzado(conn: sqlite3.Connection, empresa: str, plataforma: str):
    """Se vier atualização via E-mail, tenta casar com candidatura ativa em algum portal."""
    if plataforma.strip().lower() != "e-mail":
        return None
    norm_alvo = _normalizar_empresa(empresa)
    if len(norm_alvo) < 4:
        return None

    cur = conn.execute("""
        SELECT hash_id, empresa, cargo, plataforma, status, obs
        FROM candidaturas
        WHERE status IN ('Em Andamento', 'Avançou de Etapa')
          AND LOWER(plataforma) != 'e-mail'
        ORDER BY data_inscricao DESC
    """)
    for row in cur.fetchall():
        norm_db = _normalizar_empresa(row[1])
        if norm_db and (norm_alvo in norm_db or norm_db in norm_alvo):
            return row
    return None


def upsert_candidatura(item: dict) -> tuple[str, dict | None]:
    """
    Retorna ('NOVO', item), ('ATUALIZADO', item) ou ('IGUAL', None)
    """
    empresa_limpa = (item.get("empresa") or "").strip().lower()
    if empresa_limpa in ("", "linkedin", "candidate-se via indeed", "indeed", "e-mail"):
        return "IGUAL", None

    hash_id = gerar_hash(item["empresa"], item["cargo"], item["plataforma"])
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_novo = item.get("status", "Em Andamento")

    with get_connection() as conn:
        cur = conn.execute(
            "SELECT status, obs FROM candidaturas WHERE hash_id = ?",
            (hash_id,)
        )
        row = cur.fetchone()

        # Reconciliação cruzada: retorno definitivo por e-mail atualiza vaga aberta no portal
        if row is None and status_novo in ("Não Avançou", "Avançou de Etapa", "Contratado / Aprovado", "Vaga Cancelada"):
            match = _buscar_match_cruzado(conn, item["empresa"], item["plataforma"])
            if match:
                m_hash, m_empresa, m_cargo, m_plat, m_status, m_obs = match
                if status_novo != m_status and m_status not in STATUS_TERMINAIS:
                    data_retorno = item.get("data_retorno") or datetime.today().strftime("%Y-%m-%d")
                    obs_atualizada = f"{m_obs} | Atualizado via E-mail ({data_retorno})" if m_obs else item.get("obs", "")
                    conn.execute("""
                        UPDATE candidaturas
                        SET status = ?, data_retorno = ?, obs = ?, updated_at = ?
                        WHERE hash_id = ?
                    """, (status_novo, data_retorno, obs_atualizada[:300], agora, m_hash))
                    conn.commit()
                    item_atualizado = dict(item)
                    item_atualizado["empresa"] = m_empresa
                    item_atualizado["cargo"] = m_cargo
                    item_atualizado["plataforma"] = m_plat
                    item_atualizado["status_anterior"] = m_status
                    item_atualizado["data_retorno"] = data_retorno
                    return "ATUALIZADO", item_atualizado
                return "IGUAL", None

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
                status_novo,
                item.get("obs", ""),
                agora
            ))
            conn.commit()
            return "NOVO", item

        status_antigo, _ = row

        # Não permite que portal desatualizado reabra candidatura já encerrada
        if status_antigo in STATUS_TERMINAIS and status_novo in ("Em Andamento", "Avançou de Etapa"):
            return "IGUAL", None

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
