import os
import sqlite3
import requests

STATUS_ENCERRADOS = {
    "não avançou",
    "nao avancou",
    "reprovado",
    "vaga cancelada",
    "encerrada",
    "encerrado",
    "desistência",
    "desistencia",
    "finalizado",
    "finalizada",
    "contratado / aprovado",
    "aprovado",
}


def _eh_em_andamento(status: str | None) -> bool:
    s = (status or "").strip().lower()
    if not s:
        return True
    return s not in STATUS_ENCERRADOS


def obter_candidaturas_em_andamento(db_path: str = "data/applications.db") -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT empresa, cargo, area, plataforma, data_inscricao, status
            FROM candidaturas
            ORDER BY plataforma, empresa, cargo
        """)
        rows = [dict(r) for r in cur.fetchall()]
    return [r for r in rows if _eh_em_andamento(r.get("status"))]


def enviar_alerta_telegram(
    novos: list[dict] | None = None,
    atualizados: list[dict] | None = None,
    db_path: str = "data/applications.db",
) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("[Telegram] Credenciais ausentes; pulando notificação.")
        return

    em_andamento = obter_candidaturas_em_andamento(db_path)
    if not em_andamento:
        print("[Telegram] Nenhuma candidatura em andamento no momento.")
        return

    linhas = [
        f"📌 *Candidaturas em Andamento ({len(em_andamento)})*",
        "",
    ]
    for item in em_andamento:
        empresa = str(item.get("empresa") or "").strip()
        cargo = str(item.get("cargo") or "").strip()
        plataforma = str(item.get("plataforma") or "").strip()
        status = str(item.get("status") or "Em Andamento").strip()
        linhas.append(f"• *{empresa}* — {cargo} [{plataforma}] _{status}_")

    mensagem = "\n".join(linhas)
    # Limite seguro do Telegram por mensagem (4096 chars); divide apenas se passar disso
    pedacos = [mensagem[i : i + 4000] for i in range(0, len(mensagem), 4000)]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for parte in pedacos:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": parte, "parse_mode": "Markdown"},
            timeout=15,
        )
        if resp.status_code != 200:
            # Fallback sem Markdown caso algum caractere especial quebre o parse
            requests.post(
                url,
                json={"chat_id": chat_id, "text": parte.replace("*", "").replace("_", "")},
                timeout=15,
            )
    print(f"[Telegram] Mensagem única enviada com {len(em_andamento)} candidaturas em andamento.")
