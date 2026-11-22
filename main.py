import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from src.database import init_db, upsert_candidatura, exportar_para_bi
from src.notifier import enviar_alerta_telegram
from src.collectors.gupy_collector import extrair_gupy
from src.collectors.solides_collector import extrair_solides
from src.collectors.indeed_collector import extrair_indeed
from src.collectors.b2hr_collector import extrair_b2hr
from src.collectors.workday_collector import extrair_workday
from src.collectors.cornerstone_collector import extrair_cornerstone
from src.collectors.linkedin_collector import extrair_linkedin
from src.collectors.email_collector import extrair_emails

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
            context.close()
            browser.close()
    else:
        print("[Playwright] 'auth_state.json' não encontrado — pulando portais com sessão salva.")

    # 3. Coletores de e-mail (rodam sempre, com ou sem Playwright)
    coletados.extend(_coletar_com_seguranca("E-mail (Gmail)", extrair_emails))

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

    exportar_para_bi(str(csv_path))
    enviar_alerta_telegram(novos_itens, atualizados_itens, db_path=str(db_path))

    total_banco = _contar_total_banco(db_path)
    print(
        f"Pipeline finalizado | Total no banco: {total_banco} | "
        f"Novos: {novos} | Atualizados: {atualizados}"
    )


if __name__ == "__main__":
    main()


