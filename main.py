import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from src.database import init_db, upsert_candidatura, exportar_para_bi
from src.collectors.gupy_collector import extrair_gupy
from src.collectors.solides_collector import extrair_solides
from src.collectors.indeed_collector import extrair_indeed
from src.collectors.b2hr_collector import extrair_b2hr
from src.collectors.workday_collector import extrair_workday
from src.collectors.cornerstone_collector import extrair_cornerstone
from src.collectors.linkedin_collector import extrair_linkedin
from src.collectors.email_collector import extrair_emails
from src.collectors.hotmail_collector import extrair_hotmail

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)


def _coletar_com_seguranca(nome_fonte: str, funcao_coleta, *args, **kwargs) -> list[dict]:
    try:
        dados = funcao_coleta(*args, **kwargs) or []
        print(f"[{nome_fonte}] {len(dados)} registros retornados.")
        return dados
    except Exception as exc:
        print(f"[{nome_fonte}] Falha/bloqueio ignorado para não travar o pipeline: {exc}")
        return []


def _notificar_telegram(novos_itens: list[dict], atualizados_itens: list[dict]) -> None:
    if not novos_itens and not atualizados_itens:
        print("[Telegram] Nenhuma novidade para notificar.")
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[Telegram] Credenciais ausentes; pulando notificação.")
        return

    try:
        import src.notifier as notifier_mod
        for nome_func in ("notificar_novidades", "enviar_notificacao", "notificar_telegram", "enviar_telegram"):
            fn = getattr(notifier_mod, nome_func, None)
            if callable(fn):
                fn(novos_itens, atualizados_itens)
                return

        import requests
        linhas = ["📊 *Atualização de Candidaturas*"]
        if novos_itens:
            linhas.append(f"🆕 *Novas ({len(novos_itens)}):*")
            for item in novos_itens[:10]:
                linhas.append(f"• {item.get('empresa')} — {item.get('cargo')} ({item.get('plataforma')})")
        if atualizados_itens:
            linhas.append(f"🔄 *Atualizadas ({len(atualizados_itens)}):*")
            for item in atualizados_itens[:10]:
                linhas.append(f"• {item.get('empresa')} — {item.get('cargo')}: {item.get('status')}")

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n".join(linhas), "parse_mode": "Markdown"},
            timeout=15,
        )
    except Exception as exc:
        print(f"[Telegram] Falha ao enviar notificação (ignorada): {exc}")


def _contar_total_banco(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM candidaturas")
        row = cur.fetchone()
        return int(row[0]) if row else 0


def main() -> None:
    db_path = BASE_DIR / "data" / "applications.db"
    csv_path = BASE_DIR / "exports" / "candidaturas_bi.csv"
    auth_path = BASE_DIR / "auth_state.json"

    init_db()

    coletados: list[dict] = []

    # 1. APIs diretas
    coletados.extend(_coletar_com_seguranca("Gupy", extrair_gupy))
    coletados.extend(_coletar_com_seguranca("Sólides", extrair_solides))

    # 2. Playwright para portais sem API direta e coletores de e-mail isolados
    if auth_path.exists():
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(storage_state=str(auth_path))
            coletados.extend(_coletar_com_seguranca("Indeed", extrair_indeed, context))
            coletados.extend(_coletar_com_seguranca("B2HR", extrair_b2hr, context))
            coletados.extend(_coletar_com_seguranca("Workday", extrair_workday, context))
            coletados.extend(_coletar_com_seguranca("Cornerstone", extrair_cornerstone, context))
            coletados.extend(_coletar_com_seguranca("LinkedIn", extrair_linkedin, context))
            # coletados.extend(_coletar_com_seguranca("E-mail (Gmail)", extrair_emails))
            # coletados.extend(_coletar_com_seguranca("E-mail (Hotmail)", extrair_hotmail))
            context.close()
            browser.close()
    else:
        print("[Playwright] 'auth_state.json' não encontrado — pulando portais com sessão salva.")
        coletados.extend(_coletar_com_seguranca("E-mail (Gmail)", extrair_emails))
        coletados.extend(_coletar_com_seguranca("E-mail (Hotmail)", extrair_hotmail))

    novos = 0
    atualizados = 0
    novos_itens: list[dict] = []
    atualizados_itens: list[dict] = []

    for item in coletados:
        if not item.get("empresa") or not item.get("cargo") or not item.get("plataforma"):
            continue
        status_op, payload = upsert_candidatura(item)
        if status_op == "NOVO":
            novos += 1
            if payload:
                novos_itens.append(payload)
        elif status_op == "ATUALIZADO":
            atualizados += 1
            if payload:
                atualizados_itens.append(payload)

    _notificar_telegram(novos_itens, atualizados_itens)

    exportar_para_bi(str(csv_path))
    total_banco = _contar_total_banco(db_path)

    print(
        f"Pipeline finalizado | Total no banco: {total_banco} | "
        f"Novos: {novos} | Atualizados: {atualizados}"
    )


if __name__ == "__main__":
    main()