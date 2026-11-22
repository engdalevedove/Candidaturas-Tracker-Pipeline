import os
import json
import requests
from datetime import datetime

GUPY_API_URL = "https://private-api.gupy.io/selection-process/candidate/applications"

def _normalizar_status(app_status: str, job_status: str, step_cur: int, step_tot: int) -> str:
    app = (app_status or "").lower()
    job = (job_status or "").lower()

    if app == "hired":
        return "Contratado / Aprovado"
    if app in ["rejected", "reproved", "disqualified", "declined", "withdrawn"]:
        return "Não Avançou"
    if job in ["canceled", "cancelled"]:
        return "Vaga Cancelada"
    if job == "closed" and app not in ["hired", "in_progress"]:
        return "Não Avançou"
    if step_cur and step_cur > 1:
        return "Avançou de Etapa"
    return "Em Andamento"

def _classificar_area(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(k in c for k in ["dado", "data", "bi", "analytics", "cientista", "scientist", "sql", "etl", "power bi"]):
        return "Dados / BI"
    if any(k in c for k in ["engenh", "processo", "projeto", "qualidade", "produção", "producao", "oee"]):
        return "Engenharia / Processos"
    if any(k in c for k in ["suporte", "infra", "sistema", "ti ", "tecnologia", "desenvolvedor", "python", "automação", "automacao"]):
        return "TI / Automação"
    if any(k in c for k in ["financ", "control", "contab", "faturamento"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"

def _encontrar_lista_vagas(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for chave in ["data", "items", "applications", "results", "content"]:
            valor = payload.get(chave)
            if isinstance(valor, list):
                return [x for x in valor if isinstance(x, dict)]
            if isinstance(valor, dict):
                sub = _encontrar_lista_vagas(valor)
                if sub:
                    return sub
    return []

def extrair_gupy() -> list[dict]:
    cookie = os.getenv("GUPY_COOKIE", "").strip()
    if not cookie:
        print("[Gupy API] GUPY_COOKIE não configurado no .env.")
        return []

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://portal.gupy.io",
        "Referer": "https://portal.gupy.io/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36"
    }

    resp = requests.get(GUPY_API_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        print(f"[Gupy API] Falha HTTP {resp.status_code} (cookie expirado — atualize GUPY_COOKIE no .env).")
        return []

    payload = resp.json()
    os.makedirs("data", exist_ok=True)
    with open("data/gupy_raw_debug.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    itens = _encontrar_lista_vagas(payload)
    registros = []

    for item in itens:
        app_id = item.get("applicationId", "")
        empresa = str(item.get("careerPageName") or "Empresa Gupy").strip()
        cargo = str(item.get("jobName") or "Vaga Gupy").strip()
        app_status = str(item.get("applicationStatus") or "")
        job_status = str(item.get("jobStatus") or "")
        step_cur = int(item.get("jobStepCurrent") or 1)
        step_tot = int(item.get("jobStepCount") or 1)

        cidade = item.get("addressCity") or ""
        uf = item.get("addressStateShortName") or ""
        local = f"{cidade}/{uf}" if cidade and uf else (cidade or item.get("workplaceType") or "")

        status = _normalizar_status(app_status, job_status, step_cur, step_tot)
        obs = f"ID {app_id} | Etapa {step_cur}/{step_tot} | {local} ({app_status}/{job_status})".strip()

        registros.append({
            "empresa": empresa,
            "cargo": cargo,
            "area": _classificar_area(cargo),
            "plataforma": "Gupy",
            "data_inscricao": datetime.today().strftime("%Y-%m-%d"),
            "data_retorno": datetime.today().strftime("%Y-%m-%d") if status != "Em Andamento" else "",
            "status": status,
            "obs": obs
        })

    print(f"[Gupy API] {len(registros)} candidaturas mapeadas com sucesso!")
    return registros