from datetime import datetime
import json
import os
import requests

SOLIDES_API_URL = "https://apigw.solides.com.br/applicants-v2/jobs/v4/applicants/my-applications"


def _normalizar_status(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["aprovad", "contratad", "selecionad", "hired", "approved"]):
        return "Contratado / Aprovado"
    if any(k in t for k in ["encerrad", "não avanç", "nao avanc", "reprovad", "finalizad", "closed", "rejected", "declinad"]):
        return "Não Avançou"
    if "cancelad" in t or "canceled" in t:
        return "Vaga Cancelada"
    if any(k in t for k in ["entrevista", "teste", "etapa", "avanç", "avanc", "dinâmica", "triagem", "interview"]):
        return "Avançou de Etapa"
    return "Em Andamento"


def _classificar_area(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(k in c for k in ["dado", "data", "bi", "analytics", "cientista", "scientist", "sql", "etl", "power bi", "looker"]):
        return "Dados / BI"
    if any(k in c for k in ["engenh", "processo", "projeto", "qualidade", "produção", "producao", "oee", "lean", "six sigma"]):
        return "Engenharia / Processos"
    if any(k in c for k in ["suporte", "infra", "sistema", "ti ", "tecnologia", "desenvolvedor", "python", "automação", "automacao", "rpa"]):
        return "TI / Automação"
    if any(k in c for k in ["financ", "control", "contab", "faturamento"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def _encontrar_lista_candidaturas(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for chave in ["data", "items", "applications", "content", "results", "vacancies"]:
            valor = payload.get(chave)
            if isinstance(valor, list):
                return [x for x in valor if isinstance(x, dict)]
            if isinstance(valor, dict):
                sub = _encontrar_lista_candidaturas(valor)
                if sub:
                    return sub
    return []


def extrair_solides(*_args) -> list[dict]:
    token = os.getenv("SOLIDES_BEARER_TOKEN", "").strip()
    if not token:
        print("[Sólides API] SOLIDES_BEARER_TOKEN não configurado no .env.")
        return []

    auth_header = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {
        "authorization": auth_header,
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://perfil.vagas.solides.com.br",
        "referer": "https://perfil.vagas.solides.com.br/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36"
        ),
    }

    todas_paginas = []
    pagina = 1
    limite = 20

    while True:
        params = {
            "limit": limite,
            "page": pagina,
            "status": "applied",
            "textFilter": "",
            "type": "vacancies",
            "orderBy": "date",
        }
        resp = requests.get(SOLIDES_API_URL, headers=headers, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"[Sólides API] Falha HTTP {resp.status_code} na página {pagina} (token expirado ou inválido).")
            break

        payload = resp.json()
        itens = _encontrar_lista_candidaturas(payload)
        if not itens:
            break

        todas_paginas.extend(itens)
        if len(itens) < limite:
            break

        pagina += 1

    os.makedirs("data", exist_ok=True)
    with open("data/solides_raw_debug.json", "w", encoding="utf-8") as f:
        json.dump(todas_paginas, f, ensure_ascii=False, indent=2)

    registros = []
    for item in todas_paginas:
        vaga_raw = item.get("vacancy")
        empresa_raw = item.get("company")

        vaga = vaga_raw if isinstance(vaga_raw, dict) else {}
        empresa_obj = empresa_raw if isinstance(empresa_raw, dict) else {}
        vaga_emp = vaga.get("company") if isinstance(vaga.get("company"), dict) else {}

        empresa = (
            empresa_raw.strip() if isinstance(empresa_raw, str) and empresa_raw.strip()
            else item.get("companyName")
            or empresa_obj.get("name")
            or vaga_emp.get("name")
            or vaga.get("companyName")
            or ""
        )
        cargo = (
            vaga_raw.strip() if isinstance(vaga_raw, str) and vaga_raw.strip()
            else item.get("vacancyTitle")
            or item.get("jobTitle")
            or item.get("title")
            or vaga.get("title")
            or vaga.get("name")
            or ""
        )

        empresa_str = str(empresa).strip()
        cargo_str = str(cargo).strip()

        if not cargo_str or not empresa_str:
            continue
        if empresa_str.lower() == "empresa sólides" or cargo_str.lower() == "vaga sólides":
            continue

        etapa = str(
            item.get("currentStepName")
            or item.get("stepName")
            or item.get("stageName")
            or item.get("status")
            or ""
        ).strip()
        data_insc = str(
            item.get("appliedAt")
            or item.get("createdAt")
            or item.get("applicationDate")
            or ""
        )[:10] or datetime.today().strftime("%Y-%m-%d")

        status = _normalizar_status(f"{etapa} {item.get('status', '')}")
        vaga_id = item.get("vacancyId") or item.get("id") or vaga.get("id") or ""
        obs = f"ID {vaga_id} | {etapa}".strip(" |") if (vaga_id or etapa) else "Extraído via API Sólides"

        registros.append({
            "empresa": empresa_str,
            "cargo": cargo_str,
            "area": _classificar_area(cargo_str),
            "plataforma": "Sólides",
            "data_inscricao": data_insc,
            "data_retorno": datetime.today().strftime("%Y-%m-%d") if status != "Em Andamento" else "",
            "status": status,
            "obs": obs,
        })

    print(f"[Sólides API] {len(registros)} candidaturas mapeadas com sucesso!")
    return registros