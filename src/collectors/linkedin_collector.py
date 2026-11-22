from datetime import datetime, timedelta
import re
import time

LINKEDIN_STAGES = [
    ("https://www.linkedin.com/jobs-tracker/?stage=in-progress", "Em Andamento"),
    ("https://www.linkedin.com/jobs-tracker/?stage=applied", "Em Andamento"),
]


def _parse_data_linkedin(texto: str) -> str:
    hoje = datetime.today()
    t = (texto or "").lower()

    m_cand = re.search(r"candidatou-se\s+(?:h[aá]\s+)?(\d+)\s*d", t)
    if m_cand:
        return (hoje - timedelta(days=int(m_cand.group(1)))).strftime("%Y-%m-%d")

    m_iso = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m_iso:
        return m_iso.group(1)

    m_br = re.search(r"(\d{2}/\d{2}/\d{4})", t)
    if m_br:
        try:
            return datetime.strptime(m_br.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    if "hoje" in t or "today" in t or "just now" in t or "agora" in t:
        return hoje.strftime("%Y-%m-%d")
    if "ontem" in t or "yesterday" in t:
        return (hoje - timedelta(days=1)).strftime("%Y-%m-%d")

    m_dias = re.search(r"(?:h[aá]\s+)?(\d+)\s*d(?:ia|ias)?", t)
    if m_dias:
        return (hoje - timedelta(days=int(m_dias.group(1)))).strftime("%Y-%m-%d")

    m_sem = re.search(r"(?:h[aá]\s+)?(\d+)\s*sem(?:ana|anas)?", t)
    if m_sem:
        return (hoje - timedelta(weeks=int(m_sem.group(1)))).strftime("%Y-%m-%d")

    m_mes = re.search(r"(?:h[aá]\s+)?(\d+)\s*m[eê]s(?:es)?", t)
    if m_mes:
        return (hoje - timedelta(days=int(m_mes.group(1)) * 30)).strftime("%Y-%m-%d")

    return hoje.strftime("%Y-%m-%d")


def _normalizar_status_linkedin(texto: str, aba_padrao: str = "Em Andamento") -> str:
    t = (texto or "").lower()
    if any(
        k in t
        for k in [
            "não selecionada",
            "nao selecionada",
            "not selected",
            "no longer accepting",
            "encerrada",
            "não está mais disponível",
            "nao esta mais disponivel",
        ]
    ):
        return "Não Avançou"
    if any(k in t for k in ["entrevista", "interview", "avanç", "avanc", "selecionado para a próxima"]):
        return "Avançou de Etapa"
    return aba_padrao


def _classificar_area_linkedin(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(
        k in c
        for k in [
            "dado",
            "data",
            "bi",
            "analytics",
            "cientista",
            "scientist",
            "sql",
            "etl",
            "power bi",
            "looker",
        ]
    ):
        return "Dados / BI"
    if any(
        k in c
        for k in [
            "automação",
            "automacao",
            "inteligência artificial",
            "inteligencia artificial",
            "ia",
            "desenvolvedor",
            "rpa",
            "python",
            "devops",
            "suporte",
            "sistema",
            "ti ",
        ]
    ):
        return "TI / Automação"
    if any(
        k in c
        for k in [
            "engenh",
            "processo",
            "projeto",
            "transformação",
            "transformacao",
            "qualidade",
            "produção",
            "producao",
            "oee",
            "lean",
            "six sigma",
        ]
    ):
        return "Engenharia / Processos"
    if any(k in c for k in ["financ", "control", "contab", "faturamento"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def _colapsar_repeticao_titulo(texto: str) -> tuple[str, str]:
    """
    Detecta padrões como '<cargo> <cargo> <empresa>' ou '<cargo> - Remoto<cargo> - Remoto <empresa>'.
    Retorna (cargo_limpo, empresa_detectada_ou_vazia).
    """
    s = re.sub(r"\s+", " ", texto or "").strip()
    n = len(s)
    # Procura substring repetida com pequena distância (até 12 chars entre as ocorrências)
    for tamanho in range(min(110, n // 2), 10, -1):
        for i in range(0, n - tamanho * 2 + 12):
            trecho = s[i : i + tamanho].strip(" -|·,")
            if len(trecho) < 10:
                continue
            prox = s.find(trecho, i + len(trecho))
            if prox != -1 and prox - (i + len(trecho)) <= 15:
                resto_depois = s[prox + len(trecho) :].strip(" -|·,")
                # Remove localidade isolada se vier sozinha após a empresa
                if "·" in resto_depois:
                    resto_depois = resto_depois.split("·", 1)[0].strip()
                if resto_depois and len(resto_depois) >= 2:
                    return trecho[:140], resto_depois[:120]
                return trecho[:140], ""
    return s[:140], ""


def _separar_cargo_empresa(texto_bloco: str) -> tuple[str, str, str]:
    antes_cand = re.split(r"candidatou-se|applied", texto_bloco, maxsplit=1, flags=re.I)[0].strip()
    antes_cand = re.sub(r"\s*\(vaga verificada\)\s*", " ", antes_cand, flags=re.I).strip()

    local = ""
    base = antes_cand
    if "·" in antes_cand:
        esq, dir_parte = antes_cand.split("·", 1)
        base = esq.strip()
        local = re.split(r"candidatou-se|\(", dir_parte, maxsplit=1, flags=re.I)[0].strip()

    cargo_colapsado, empresa_colapsada = _colapsar_repeticao_titulo(base)
    if empresa_colapsada:
        return cargo_colapsado, empresa_colapsada, local[:100]

    # Separa quando há modalidade/senioridade colada com a empresa (ex.: 'RemotoLanlink...')
    m_colado = re.search(
        r"(?:remoto|remote|híbrido|hibrido|hybrid|presencial|on-site|júnior|junior|pleno|sênior|senior|jr|pl|sr)\s*([A-ZÀ-Ú][A-Za-zÀ-Ú0-9&./ -]{1,60})$",
        cargo_colapsado,
    )
    if m_colado and len(cargo_colapsado[: m_colado.start(1)].strip()) >= 4:
        cargo = cargo_colapsado[: m_colado.start(1)].strip(" -|")
        empresa = m_colado.group(1).strip()
        return cargo[:140], empresa[:120], local[:100]

    # Separa transição de letra minúscula para maiúscula colada (ex.: 'DadosFantástico Alimentos')
    m_camel = re.search(r"([a-zà-ú0-9\)\]-])([A-ZÀ-Ú][A-Za-zÀ-Ú0-9&./ -]{1,60})$", cargo_colapsado)
    if m_camel and len(cargo_colapsado[: m_camel.start(1) + 1].strip()) >= 4:
        corte = m_camel.start(1) + 1
        cargo = cargo_colapsado[:corte].strip(" -|")
        empresa = cargo_colapsado[corte:].strip()
        return cargo[:140], empresa[:120], local[:100]

    return cargo_colapsado[:140], "LinkedIn", local[:100]


def _rolar_lista(page, passos: int = 12) -> None:
    for _ in range(passos):
        page.mouse.wheel(0, 1200)
        time.sleep(0.7)
        try:
            page.evaluate(
                """() => {
                    for (const el of document.querySelectorAll('main, section, div, ul')) {
                        if (el.scrollHeight > el.clientHeight + 200) {
                            el.scrollTop = el.scrollHeight;
                        }
                    }
                }"""
            )
        except Exception:
            pass
        time.sleep(0.4)


def _extrair_da_url(page, url: str, status_padrao: str, vistos: set[str]) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=35000)
    time.sleep(5)
    _rolar_lista(page, passos=12)

    registros: list[dict] = []
    for el in page.locator("div, a, li").all():
        try:
            txt = re.sub(r"\s+", " ", (el.inner_text(timeout=250) or "")).strip()
            if not txt or len(txt) < 25 or len(txt) > 550:
                continue
            low = txt.lower()
            if ("candidatou-se" not in low and "applied" not in low) or "·" not in txt:
                continue
            if low.count("candidatou-se") > 1 or low.count("applied") > 1:
                continue

            cargo, empresa, local = _separar_cargo_empresa(txt)
            if not cargo or len(cargo) < 4:
                continue

            data_insc = _parse_data_linkedin(txt)
            status = _normalizar_status_linkedin(txt, aba_padrao=status_padrao)
            chave = f"{empresa.lower()}|{cargo.lower()}"
            if chave in vistos:
                continue
            vistos.add(chave)

            obs_local = f"{local} | " if local else ""
            registros.append(
                {
                    "empresa": empresa,
                    "cargo": cargo,
                    "area": _classificar_area_linkedin(cargo),
                    "plataforma": "LinkedIn",
                    "data_inscricao": data_insc,
                    "data_retorno": data_insc if status != "Em Andamento" else "",
                    "status": status,
                    "obs": f"{obs_local}Rastreador LinkedIn | linkedin.com"[:240],
                }
            )
        except Exception:
            continue

    return registros


def extrair_linkedin(context, captcha_mgr=None) -> list[dict]:
    if context is None:
        print("[LinkedIn] Contexto do Playwright não fornecido.")
        return []

    page = context.new_page()
    try:
        page.goto(LINKEDIN_STAGES[0][0], wait_until="domcontentloaded", timeout=35000)
        time.sleep(4)

        if captcha_mgr and hasattr(captcha_mgr, "resolver_se_necessario"):
            captcha_mgr.resolver_se_necessario(page)

        url_atual = page.url.lower()
        body_txt = page.locator("body").inner_text(timeout=2500).lower()
        if (
            ("login" in url_atual or "checkpoint" in url_atual)
            and "rastreador de vagas" not in body_txt
            and "candidaturas enviadas" not in body_txt
            and "em andamento" not in body_txt
        ):
            print("[LinkedIn] Sessão não autenticada ou em checkpoint. Atualize o auth_state.json.")
            return []

        vistos: set[str] = set()
        registros: list[dict] = []

        for url, status_padrao in LINKEDIN_STAGES:
            registros.extend(_extrair_da_url(page, url, status_padrao, vistos))

        print(f"[LinkedIn] {len(registros)} registros capturados.")
        return registros
    finally:
        page.close()