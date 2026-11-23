from datetime import datetime
import re
import time

INDEED_APPLIED_URL = "https://myjobs.indeed.com/applied"


def _normalizar_status_indeed(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["aprovad", "contratad", "selecionad", "hired", "offer"]):
        return "Contratado / Aprovado"
    if any(k in t for k in ["não avanç", "nao avanc", "encerrad", "reprovad", "not selected", "closed"]):
        return "Não Avançou"
    if "cancelad" in t or "canceled" in t:
        return "Vaga Cancelada"
    if any(k in t for k in ["entrevista", "teste", "etapa", "visualiz", "interview", "viewed"]):
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


def _eh_ruido_linha(linha: str) -> bool:
    l = linha.strip().lower()
    if not l or len(l) < 2:
        return True
    ruidos = [
        "currículo enviado",
        "curriculo enviado",
        "a descrição da vaga abre em uma nova janela",
        "a descricao da vaga abre em uma nova janela",
        "candidatou-se em",
        "ver detalhes",
        "atualizar status",
        "arquivar",
        "remoto",
        "híbrido",
        "hibrido",
        "presencial",
    ]
    if any(r in l for r in ruidos):
        return True
    if re.match(r"^[a-zà-ú\s]+,\s*[a-z]{2}$", l):
        return True
    return False


def _parse_card_indeed(linhas: list[str]) -> tuple[str, str, str]:
    """Retorna (empresa, cargo, obs) a partir das linhas de texto de um card/bloco."""
    linhas_limpas = [re.sub(r"\s+", " ", x).strip() for x in linhas if x and x.strip()]
    if not linhas_limpas:
        return "", "", ""

    candidatos = [x for x in linhas_limpas if not _eh_ruido_linha(x)]
    if len(candidatos) >= 2:
        cargo = candidatos[0]
        empresa = candidatos[1]
    elif len(candidatos) == 1:
        cargo = candidatos[0]
        empresa = "Empresa Indeed"
    else:
        return "", "", ""

    # Se a primeira linha for exatamente "Currículo enviado" e a segunda tiver o cargo, inverte
    if cargo.lower() in ("currículo enviado", "curriculo enviado") and len(candidatos) >= 2:
        cargo = candidatos[1]
        empresa = candidatos[2] if len(candidatos) >= 3 else "Empresa Indeed"

    obs = " | ".join(linhas_limpas[:6])[:240]
    return empresa[:120], cargo[:140], obs


def extrair_indeed(context, captcha_mgr=None) -> list[dict]:
    if context is None:
        print("[Indeed] Contexto do Playwright não fornecido.")
        return []

    page = context.new_page()
    try:
        page.goto(INDEED_APPLIED_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        if captcha_mgr and hasattr(captcha_mgr, "resolver_se_necessario"):
            captcha_mgr.resolver_se_necessario(page)

        url_atual = page.url.lower()
        if "login" in url_atual or "signin" in url_atual or "auth" in url_atual:
            print("[Indeed] Coleta direta via navegador ignorada (bloqueio anti-bot); retornos capturados via Gmail.")
            return []

        for _ in range(5):
            page.mouse.wheel(0, 1800)
            time.sleep(0.9)

        seletores = [
            "[data-testid*='applied']",
            "main li",
            "main article",
            "main [class*='card']",
            "main [class*='job']",
        ]

        blocos_texto = []
        for sel in seletores:
            locators = page.locator(sel).all()
            if locators:
                for el in locators:
                    try:
                        txt = el.inner_text(timeout=1500).strip()
                        if txt and ("candidatou-se" in txt.lower() or "currículo enviado" in txt.lower() or "curriculo enviado" in txt.lower() or len(txt.splitlines()) >= 2):
                            blocos_texto.append(txt.splitlines())
                    except Exception:
                        continue
                if blocos_texto:
                    break

        registros = []
        vistos = set()
        hoje = datetime.today().strftime("%Y-%m-%d")

        for linhas in blocos_texto:
            empresa, cargo, obs = _parse_card_indeed(linhas)
            if not cargo or cargo.lower() in ("currículo enviado", "curriculo enviado"):
                continue

            chave = f"{empresa.lower()}|{cargo.lower()}"
            if chave in vistos:
                continue
            vistos.add(chave)

            status = _normalizar_status_indeed(" ".join(linhas))
            registros.append({
                "empresa": empresa,
                "cargo": cargo,
                "area": _classificar_area(cargo),
                "plataforma": "Indeed",
                "data_inscricao": hoje,
                "data_retorno": hoje if status != "Em Andamento" else "",
                "status": status,
                "obs": obs,
            })

        print(f"[Indeed] {len(registros)} registros capturados.")
        return registros
    finally:
        page.close()
