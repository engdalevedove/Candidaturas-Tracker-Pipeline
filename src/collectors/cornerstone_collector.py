from datetime import datetime
import re
import time

CORNERSTONE_HOME_URL = "https://jacto.csod.com/"
CORNERSTONE_PROFILE_URL = (
    "https://jacto.csod.com/ATS/careersite/ds.aspx"
    "?routename=ATS/CareerSite/MyProfile&c=jacto&site=1&lang=pt-BR"
)


def _parse_data_br(texto: str) -> str:
    m = re.search(r"(\d{2}/\d{2}/\d{4})", texto or "")
    if m:
        try:
            return datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.today().strftime("%Y-%m-%d")


def _normalizar_status_csod(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["aprovad", "contratad", "selecionad", "hired"]):
        return "Contratado / Aprovado"
    if any(k in t for k in ["fechado", "encerrad", "não avanç", "nao avanc", "reprovad", "closed"]):
        return "Não Avançou"
    if "cancelad" in t:
        return "Vaga Cancelada"
    if any(k in t for k in ["entrevista", "etapa", "avanç", "avanc", "teste"]):
        return "Avançou de Etapa"
    if "em avaliação" in t or "em avaliacao" in t or "em andamento" in t:
        return "Em Andamento"
    return "Em Andamento"


def _classificar_area(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(k in c for k in [
        "dado", "data", "bi", "analytics", "cientista", "scientist",
        "sql", "etl", "power bi", "looker"
    ]):
        return "Dados / BI"
    if any(k in c for k in [
        "automação", "automacao", "inteligência artificial", "inteligencia artificial",
        "ia", "desenvolvedor", "rpa", "python", "suporte", "infra", "sistema", "ti ", "tecnologia"
    ]):
        return "TI / Automação"
    if any(k in c for k in [
        "engenh", "processo", "projeto", "transformação", "transformacao",
        "qualidade", "produção", "producao", "oee", "lean", "six sigma"
    ]):
        return "Engenharia / Processos"
    if any(k in c for k in ["financ", "control", "contab", "faturamento"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def _extrair_de_escopo(escopo, vistos: set[str]) -> list[dict]:
    registros = []
    try:
        for el in escopo.locator("div, li, tr, section").all():
            try:
                txt = el.inner_text(timeout=800).strip()
                if not txt or len(txt) > 600:
                    continue
                low_txt = txt.lower()
                if "id de sol." not in low_txt and "status da avaliação" not in low_txt and "status da avaliacao" not in low_txt:
                    continue
                if low_txt.count("id de sol.") > 1:
                    continue

                linhas = [re.sub(r"\s+", " ", l).strip() for l in txt.splitlines() if l.strip()]
                if not linhas:
                    continue

                req_match = re.search(r"ID de Sol\.\s*:\s*([A-Za-z0-9_-]+)", txt, re.I)
                req_id = req_match.group(1).strip() if req_match else ""

                cargo = ""
                for l in linhas:
                    low = l.lower()
                    if low in ("completo", "em avaliação", "em avaliacao", "fechado"):
                        continue
                    if (
                        low.startswith("id de sol.")
                        or low.startswith("última modificação")
                        or low.startswith("ultima modificacao")
                        or low.startswith("status da avaliação")
                        or low.startswith("status da avaliacao")
                    ):
                        continue
                    if len(l) >= 4:
                        cargo = l
                        break

                if not cargo:
                    continue

                data_insc = _parse_data_br(txt)
                status = _normalizar_status_csod(txt)
                chave = f"grupo jacto|{req_id.lower()}|{cargo.lower()}"
                if chave in vistos:
                    continue
                vistos.add(chave)

                obs_base = f"ID de Sol. {req_id} | " if req_id else ""
                obs = f"{obs_base}{txt.replace(chr(10), ' | ')} | jacto.csod.com"

                registros.append({
                    "empresa": "GRUPO JACTO",
                    "cargo": cargo[:140],
                    "area": _classificar_area(cargo),
                    "plataforma": "Cornerstone",
                    "data_inscricao": data_insc,
                    "data_retorno": data_insc if status != "Em Andamento" else "",
                    "status": status,
                    "obs": obs[:240],
                })
            except Exception:
                continue
    except Exception:
        pass
    return registros


def extrair_cornerstone(context, captcha_mgr=None) -> list[dict]:
    if context is None:
        print("[Cornerstone] Contexto do Playwright não fornecido.")
        return []

    page = context.new_page()
    try:
        page.goto(CORNERSTONE_PROFILE_URL, wait_until="domcontentloaded", timeout=35000)
        time.sleep(5)

        if "login.aspx" in page.url.lower():
            page.goto(CORNERSTONE_HOME_URL, wait_until="domcontentloaded", timeout=35000)
            time.sleep(4)

        if captcha_mgr and hasattr(captcha_mgr, "resolver_se_necessario"):
            captcha_mgr.resolver_se_necessario(page)

        for _ in range(4):
            page.mouse.wheel(0, 900)
            time.sleep(0.7)

        vistos: set[str] = set()
        registros: list[dict] = []

        # Varre a página principal e todos os frames (iframes do Cornerstone)
        escopos = [page] + [f for f in page.frames if f != page.main_frame]
        for escopo in escopos:
            registros.extend(_extrair_de_escopo(escopo, vistos))

        print(f"[Cornerstone] {len(registros)} registros capturados.")
        return registros
    finally:
        page.close()