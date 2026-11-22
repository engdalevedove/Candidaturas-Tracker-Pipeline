from datetime import datetime
import re
import time

WORKDAY_URL = "https://accenture.wd103.myworkdayjobs.com/pt-BR/AccentureCareers/userHome"

MESES_PT = {
    "janeiro": "01",
    "fevereiro": "02",
    "março": "03",
    "marco": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}


def _parse_data_pt(texto: str) -> str:
    m_num = re.search(r"(\d{2}/\d{2}/\d{4})", texto or "")
    if m_num:
        try:
            return datetime.strptime(m_num.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    m_ext = re.search(
        r"(\d{1,2})\s+de\s+([a-zçã]+)\s+de\s+(\d{4})",
        (texto or "").lower(),
    )
    if m_ext:
        dia = m_ext.group(1).zfill(2)
        mes = MESES_PT.get(m_ext.group(2))
        ano = m_ext.group(3)
        if mes:
            return f"{ano}-{mes}-{dia}"

    return datetime.today().strftime("%Y-%m-%d")


def _normalizar_status_workday(texto: str, aba_inativa: bool = False) -> str:
    if aba_inativa:
        return "Não Avançou"
    t = (texto or "").lower()
    if any(k in t for k in ["aprovad", "contratad", "selecionad", "offer", "hired"]):
        return "Contratado / Aprovado"
    if any(k in t for k in ["cancelad", "retirad", "withdrawn"]):
        return "Vaga Cancelada"
    if any(k in t for k in ["não avanç", "nao avanc", "encerrad", "no longer", "not selected"]):
        return "Não Avançou"
    if any(k in t for k in ["entrevista", "etapa", "avanç", "avanc", "interview", "assessment"]):
        return "Avançou de Etapa"
    return "Em Andamento"


def _classificar_area(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(k in c for k in [
        "dado", "data", "bi", "analytics", "cientista", "scientist",
        "sql", "etl", "power bi", "looker", "inteligência operacional"
    ]):
        return "Dados / BI"
    if any(k in c for k in [
        "automação", "automacao", "inteligência artificial", "ia",
        "rpa", "python", "suporte", "infra", "sistema", "ti ", "tecnologia"
    ]):
        return "TI / Automação"
    if any(k in c for k in ["engenh", "processo", "projeto", "qualidade", "produção", "producao"]):
        return "Engenharia / Processos"
    if any(k in c for k in ["financ", "control", "contab", "faturamento"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def _aguardar_carregamento_workday(page, timeout_seg: int = 25) -> None:
    try:
        btn_cookies = page.get_by_role("button", name=re.compile(r"aceitar cookies|recusar", re.I))
        if btn_cookies.count() > 0 and btn_cookies.first.is_visible():
            btn_cookies.first.click(timeout=2000)
            time.sleep(0.5)
    except Exception:
        pass

    inicio = time.time()
    while (time.time() - inicio) < timeout_seg:
        try:
            body_txt = page.locator("body").inner_text(timeout=1500)
            tem_req = bool(re.search(r"\bR\d{5,}\b", body_txt))
            tem_cargo = "cientista de dados" in body_txt.lower() or "candidatura recebida" in body_txt.lower()
            ainda_carregando = "loading" in body_txt.lower() and not (tem_req or tem_cargo)
            if (tem_req or tem_cargo) and not ainda_carregando:
                break
        except Exception:
            pass
        page.mouse.wheel(0, 600)
        time.sleep(1.0)


def _extrair_candidaturas_da_pagina(page, aba_inativa: bool, vistos: set[str]) -> list[dict]:
    registros = []
    hoje = datetime.today().strftime("%Y-%m-%d")

    # 1. Tenta linhas de tabela primeiro
    linhas_loc = page.locator("table tbody tr, [role='row']").all()
    for row in linhas_loc:
        try:
            txt = row.inner_text(timeout=1200).strip()
            if not txt or "loading" in txt.lower():
                continue
            partes = [re.sub(r"\s+", " ", c).strip() for c in re.split(r"\t|\n", txt) if c.strip()]
            if len(partes) < 2:
                continue
            if any(h in " ".join(partes).lower() for h in ["título do cargo", "requisição de recrutamento", "status de minhas candidaturas"]):
                continue

            cargo = partes[0][:140]
            req_id = ""
            for p in partes[1:]:
                if re.fullmatch(r"R?\d{5,}", p.strip()):
                    req_id = p.strip()
                    break

            data_insc = _parse_data_pt(" ".join(partes))
            status = _normalizar_status_workday(" ".join(partes), aba_inativa=aba_inativa)
            chave = f"accenture|{req_id.lower()}|{cargo.lower()}|{data_insc}"
            if chave in vistos:
                continue
            vistos.add(chave)

            obs = f"Req {req_id} | " + " | ".join(partes[1:4]) if req_id else " | ".join(partes[1:4])
            registros.append({
                "empresa": "Accenture",
                "cargo": cargo,
                "area": _classificar_area(cargo),
                "plataforma": "Workday",
                "data_inscricao": data_insc,
                "data_retorno": hoje if status != "Em Andamento" else "",
                "status": status,
                "obs": f"accenture.wd103.myworkdayjobs.com | {obs}"[:240],
            })
        except Exception:
            continue

    if registros:
        return registros

    # 2. Fallback por blocos contendo requisição (ex.: R00316703)
    for el in page.locator("li, div, article").all():
        try:
            txt = el.inner_text(timeout=800).strip()
            if not txt or len(txt) > 500 or "loading" in txt.lower():
                continue
            reqs = re.findall(r"\b(R\d{5,})\b", txt)
            if len(reqs) != 1:
                continue
            req_id = reqs[0]
            linhas = [re.sub(r"\s+", " ", x).strip() for x in txt.splitlines() if x.strip()]
            cargo = ""
            for l in linhas:
                if req_id in l or "candidatura" in l.lower() or re.search(r"\d{1,2}\s+de\s+[a-zçã]+\s+de\s+\d{4}", l.lower()):
                    continue
                if len(l) >= 4 and l.lower() not in ("ativas", "inativas", "ação", "acao"):
                    cargo = l
                    break
            if not cargo:
                continue

            data_insc = _parse_data_pt(" ".join(linhas))
            status = _normalizar_status_workday(" ".join(linhas), aba_inativa=aba_inativa)
            chave = f"accenture|{req_id.lower()}|{cargo.lower()}|{data_insc}"
            if chave in vistos:
                continue
            vistos.add(chave)

            registros.append({
                "empresa": "Accenture",
                "cargo": cargo[:140],
                "area": _classificar_area(cargo),
                "plataforma": "Workday",
                "data_inscricao": data_insc,
                "data_retorno": hoje if status != "Em Andamento" else "",
                "status": status,
                "obs": f"accenture.wd103.myworkdayjobs.com | Req {req_id} | {' | '.join(linhas[:3])}"[:240],
            })
        except Exception:
            continue

    return registros


def extrair_workday(context, captcha_mgr=None) -> list[dict]:
    if context is None:
        print("[Workday] Contexto do Playwright não fornecido.")
        return []

    page = context.new_page()
    try:
        page.goto(WORKDAY_URL, wait_until="domcontentloaded", timeout=35000)

        if captcha_mgr and hasattr(captcha_mgr, "resolver_se_necessario"):
            captcha_mgr.resolver_se_necessario(page)

        url_atual = page.url.lower()
        if "login" in url_atual or "signin" in url_atual or "auth" in url_atual:
            print("[Workday] Sessão não autenticada ou redirecionada para login. Rode setup_session.py.")
            return []

        _aguardar_carregamento_workday(page, timeout_seg=25)

        vistos: set[str] = set()
        registros: list[dict] = []

        # Aba Ativas
        registros.extend(_extrair_candidaturas_da_pagina(page, aba_inativa=False, vistos=vistos))

        # Aba Inativas
        try:
            aba_inativas = page.get_by_role("button", name=re.compile(r"inativas", re.I))
            if aba_inativas.count() == 0:
                aba_inativas = page.get_by_text(re.compile(r"^inativas\s*\(\d+\)", re.I))
            if aba_inativas.count() > 0 and aba_inativas.first.is_visible():
                aba_inativas.first.click(timeout=3000)
                time.sleep(2.5)
                registros.extend(_extrair_candidaturas_da_pagina(page, aba_inativa=True, vistos=vistos))
        except Exception:
            pass

        print(f"[Workday] {len(registros)} registros capturados.")
        return registros
    finally:
        page.close()