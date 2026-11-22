from datetime import datetime
import re
import time

B2HR_APPLIED_URL = "https://b2hr.empregare.com/pt-br/candidato/candidaturas"


def _normalizar_status_b2hr(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["aprovad", "contratad", "selecionad", "hired", "approved"]):
        return "Contratado / Aprovado"
    if any(k in t for k in ["encerrad", "não avanç", "nao avanc", "reprovad", "finalizad", "closed", "rejected"]):
        return "Não Avançou"
    if "cancelad" in t or "desist" in t:
        return "Vaga Cancelada"
    if any(k in t for k in ["entrevista", "teste", "etapa", "avanç", "avanc", "dinâmica", "triagem"]):
        return "Avançou de Etapa"
    return "Em Andamento"


def _classificar_area(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(k in c for k in [
        "dado", "data", "bi", "analytics", "inteligência operacional", "inteligencia operacional",
        "cientista", "scientist", "sql", "etl", "power bi", "looker"
    ]):
        return "Dados / BI"
    if any(k in c for k in [
        "automação", "automacao", "inteligência artificial", "inteligencia artificial",
        "ia", "rpa", "python", "suporte", "infra", "sistema", "ti ", "tecnologia", "desenvolvedor"
    ]):
        return "TI / Automação"
    if any(k in c for k in ["engenh", "processo", "projeto", "qualidade", "produção", "producao", "oee", "lean", "six sigma"]):
        return "Engenharia / Processos"
    if any(k in c for k in ["financ", "control", "contab", "faturamento"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def _extrair_data_envio(texto: str) -> str:
    m = re.search(r"(\d{2}/\d{2}/\d{4})", texto or "")
    if m:
        try:
            return datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.today().strftime("%Y-%m-%d")


def _eh_ruido_b2hr(linha: str) -> bool:
    l = linha.strip().lower()
    if not l or len(l) < 2:
        return True
    ruidos = [
        "suas candidaturas",
        "candidaturas",
        "em andamento",
        "desistências",
        "desistencias",
        "encerradas",
        "vagas",
        "sou empresa",
        "ajuda",
        "notificações",
        "notificacoes",
        "currículo",
        "curriculo",
        "vagas salvas",
        "alerta de vagas",
        "mensagens",
        "painel",
        "100%",
    ]
    if l in ruidos or l.startswith("enviada em "):
        return True
    if re.fullmatch(r"\d+\s*candidaturas?", l):
        return True
    return False


def _parse_card_b2hr(linhas: list[str], status_padrao: str = "Em Andamento") -> tuple[str, str, str, str, str] | None:
    """
    Retorna (empresa, cargo, data_inscricao, status, obs) ou None se não for um card válido.
    Na B2HR, o card costuma ter:
      - Linha 1: Cargo (ex.: 'Analista de Automação e Inteligência Artificial – Pleno')
      - Linha 2: 'GRUPO JPDV · São Paulo · SP' ou 'EMBRAPII · Brasília · DF'
      - Linha 3: 'Enviada em 12/11/2026'
    """
    linhas_limpas = [re.sub(r"\s+", " ", x).strip() for x in linhas if x and x.strip()]
    if not linhas_limpas:
        return None

    texto_completo = " | ".join(linhas_limpas)
    if "enviada em" not in texto_completo.lower() and "candidatura" not in texto_completo.lower():
        return None

    data_insc = _extrair_data_envio(texto_completo)
    status = _normalizar_status_b2hr(f"{status_padrao} {texto_completo}")

    cargo = ""
    empresa = ""
    local = ""

    for linha in linhas_limpas:
        if _eh_ruido_b2hr(linha):
            continue
        if "·" in linha or "•" in linha:
            partes = [p.strip() for p in re.split(r"[·•]", linha) if p.strip()]
            if partes and not empresa:
                empresa = partes[0]
            if len(partes) > 1:
                local = " - ".join(partes[1:])
        elif not cargo:
            cargo = linha

    if not cargo or not empresa:
        return None

    obs_partes = [p for p in [local, f"Enviada em {data_insc}", "b2hr.empregare.com"] if p]
    obs = " | ".join(obs_partes)[:240]
    return empresa[:120], cargo[:140], data_insc, status, obs


def extrair_b2hr(context, captcha_mgr=None) -> list[dict]:
    if context is None:
        print("[B2HR] Contexto do Playwright não fornecido.")
        return []

    page = context.new_page()
    try:
        page.goto(B2HR_APPLIED_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        if captcha_mgr and hasattr(captcha_mgr, "resolver_se_necessario"):
            captcha_mgr.resolver_se_necessario(page)

        url_atual = page.url.lower()
        if "login" in url_atual or "entrar" in url_atual or "auth" in url_atual:
            print("[B2HR] Sessão não autenticada ou redirecionada para login. Rode setup_session.py se necessário.")
            return []

        for _ in range(3):
            page.mouse.wheel(0, 1200)
            time.sleep(0.7)

        registros = []
        vistos = set()

        # Tenta varrer abas se existirem (ex.: Em andamento, Desistências, Encerradas)
        abas = [
            ("Em Andamento", None),
            ("Não Avançou", page.get_by_role("tab", name=re.compile("encerradas", re.I))),
            ("Vaga Cancelada", page.get_by_role("tab", name=re.compile("desist", re.I))),
        ]

        for status_aba, aba_locator in abas:
            if aba_locator is not None:
                try:
                    if aba_locator.count() > 0 and aba_locator.first.is_visible():
                        aba_locator.first.click(timeout=3000)
                        time.sleep(1.5)
                except Exception:
                    continue

            candidatos_locators = page.locator("main div, main li, main article, section div").all()
            for el in candidatos_locators:
                try:
                    txt = el.inner_text(timeout=1000).strip()
                    if not txt or "enviada em" not in txt.lower():
                        continue
                    # Evita containers grandes que englobam várias candidaturas juntas
                    if txt.lower().count("enviada em") > 1:
                        continue

                    parsed = _parse_card_b2hr(txt.splitlines(), status_padrao=status_aba)
                    if not parsed:
                        continue

                    empresa, cargo, data_insc, status, obs = parsed
                    chave = f"{empresa.lower()}|{cargo.lower()}|{data_insc}"
                    if chave in vistos:
                        continue
                    vistos.add(chave)

                    registros.append({
                        "empresa": empresa,
                        "cargo": cargo,
                        "area": _classificar_area(cargo),
                        "plataforma": "B2HR",
                        "data_inscricao": data_insc,
                        "data_retorno": datetime.today().strftime("%Y-%m-%d") if status != "Em Andamento" else "",
                        "status": status,
                        "obs": obs,
                    })
                except Exception:
                    continue

        print(f"[B2HR] {len(registros)} registros capturados.")
        return registros
    finally:
        page.close()