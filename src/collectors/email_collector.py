from datetime import datetime, timedelta
import email
from email.header import decode_header
import imaplib
import os
import re


def _decodificar_header(valor: str | None) -> str:
    if not valor:
        return ""
    partes = decode_header(valor)
    resultado = []
    for texto, charset in partes:
        if isinstance(texto, bytes):
            enc = charset or "utf-8"
            try:
                resultado.append(texto.decode(enc, errors="replace"))
            except LookupError:
                resultado.append(texto.decode("utf-8", errors="replace"))
        else:
            resultado.append(str(texto))
    return "".join(resultado).strip()


def _extrair_corpo_texto(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except LookupError:
                        return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    return ""


def _eh_irrelevante(remetente: str, assunto: str, corpo: str) -> bool:
    rem = remetente.lower()
    ass = assunto.lower()
    texto = f"{rem} {ass} {corpo[:600]}".lower()

    remetentes_bloqueados = [
        "adobe",
        "workspace-noreply",
        "google workspace",
        "ingresso.com",
        "alert@indeed.com",
        "jobalert",
        "newsletter",
        "marketing",
        "promo",
    ]
    if any(r in rem for r in remetentes_bloqueados):
        return True

    # No Indeed, só aceita confirmação explícita de candidatura ("Inscrição via Indeed:" ou "Indeed Application:")
    if "indeed" in rem and not any(k in ass for k in ["inscrição via indeed", "inscricao via indeed", "indeed application"]):
        return True

    bloqueios = [
        "cartório",
        "cartorio",
        "certidão",
        "certidao",
        "cidadania",
        "bootcamp",
        "matrícula",
        "matricula",
        "nota fiscal",
        "fatura",
        "black friday",
        "desconto",
        "economize",
        "promoção",
        "promocao",
        "oferta",
        "assinatura",
        "mais vagas de",
        "novas vagas",
        "vagas semelhantes",
        "alerta de vagas",
    ]
    return any(b in texto for b in bloqueios)


def _eh_email_vaga(assunto: str, corpo: str) -> bool:
    # Analisa assunto e início do corpo (evita falsos positivos em rodapé)
    texto = f"{assunto} {corpo[:700]}".lower()
    gatilhos = [
        "sua candidatura",
        "candidatura enviada",
        "candidatura recebida",
        "inscrição confirmada",
        "inscricao confirmada",
        "inscrição via indeed",
        "inscricao via indeed",
        "indeed application",
        "processo seletivo",
        "feedback sobre o processo",
        "notícia sobre a sua candidatura",
        "noticia sobre a sua candidatura",
        "entrevista",
        "interview",
        "invitation to solve",
        "application received",
        "application update",
        "your application",
        "retorno da vaga",
        "retorno do processo",
    ]
    return any(g in texto for g in gatilhos)


def _normalizar_status_email(assunto: str, corpo: str) -> str:
    texto = f"{assunto} {corpo}".lower()
    negativas = [
        "não avançamos",
        "nao avancamos",
        "não avançar",
        "nao avancar",
        "seguir com outros candidatos",
        "outros candidatos",
        "encerrado",
        "não selecionado",
        "nao selecionado",
        "não foi aprovado",
        "nao foi aprovado",
        "diante dos requisitos",
        "declined",
        "not moving forward",
        "not to move forward",
        "move forward with other",
        "other candidates",
        "unfortunately",
        "regret to inform",
        "not selected",
        "position has been filled",
    ]
    if any(k in texto for k in negativas):
        return "Não Avançou"

    positivas = [
        "aprovado nos testes",
        "convite para entrevista",
        "agendar entrevista",
        "entrevista",
        "interview",
        "invitation to solve",
        "próxima etapa",
        "proxima etapa",
        "avançou",
        "avancou",
    ]
    if any(k in texto for k in positivas):
        return "Avançou de Etapa"

    return "Em Andamento"


def _classificar_area_email(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["data", "dados", "analytics", "bi", "cientista", "sql", "power bi", "looker"]):
        return "Dados / BI"
    if any(k in t for k in ["ia", "inteligência artificial", "inteligencia artificial", "automação", "automacao", "rpa", "python", "banco de dados", "engenheiro(a) de ia"]):
        return "TI / Automação"
    if any(k in t for k in ["engenharia", "processos", "projeto", "qualidade", "produção", "producao", "faixa de domínio"]):
        return "Engenharia / Processos"
    if any(k in t for k in ["financeiro", "controladoria", "contábil", "contabil"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def _extrair_empresa_e_cargo(remetente: str, assunto: str) -> tuple[str, str]:
    remetente_limpo = re.sub(r"<.*?>", "", remetente or "").strip().strip('"')
    empresa = remetente_limpo or "E-mail"
    if "@" in empresa and " " not in empresa:
        empresa = empresa.split("@")[1].split(".")[0].upper()

    cargo = assunto.strip()[:140] or "Candidatura via E-mail"
    if " - " in assunto:
        partes = [p.strip() for p in assunto.split(" - ") if p.strip()]
        if len(partes) >= 2:
            cargo = partes[-1][:140]
            if len(empresa) > 45:
                empresa = partes[0][:100]

    return empresa[:120], cargo[:140]


def _parse_data_email(msg) -> str:
    data_hdr = msg.get("Date")
    if data_hdr:
        try:
            dt = email.utils.parsedate_to_datetime(data_hdr)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.today().strftime("%Y-%m-%d")


def extrair_emails(dias_retroativos: int = 30, limite_mensagens: int = 80) -> list[dict]:
    usuario = (
        os.getenv("GMAIL_USER")
        or os.getenv("EMAIL_USER")
        or os.getenv("IMAP_USER")
        or ""
    ).strip()
    senha = (
        os.getenv("GMAIL_APP_PASSWORD")
        or os.getenv("EMAIL_PASSWORD")
        or os.getenv("IMAP_PASSWORD")
        or ""
    ).strip()

    if not usuario or not senha:
        print("[E-mail] GMAIL_USER ou GMAIL_APP_PASSWORD não configurados no .env.")
        return []

    registros: list[dict] = []
    vistos: set[str] = set()
    data_corte = (datetime.today() - timedelta(days=dias_retroativos)).strftime("%d-%b-%Y")

    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        mail.login(usuario, senha)
        mail.select("INBOX")

        status, mensagens = mail.search(None, f'(SINCE "{data_corte}")')
        if status != "OK" or not mensagens or not mensagens[0]:
            return []

        ids = mensagens[0].split()[-limite_mensagens:]
        for msg_id in reversed(ids):
            try:
                res, dados = mail.fetch(msg_id, "(RFC822)")
                if res != "OK" or not dados or not dados[0]:
                    continue
                raw_email = dados[0][1]
                if not isinstance(raw_email, bytes):
                    continue

                msg = email.message_from_bytes(raw_email)
                remetente = _decodificar_header(msg.get("From"))
                assunto = _decodificar_header(msg.get("Subject"))
                corpo = _extrair_corpo_texto(msg)[:1500]

                if _eh_irrelevante(remetente, assunto, corpo) or not _eh_email_vaga(assunto, corpo):
                    continue

                empresa, cargo = _extrair_empresa_e_cargo(remetente, assunto)
                data_insc = _parse_data_email(msg)
                status_vaga = _normalizar_status_email(assunto, corpo)
                chave = f"{empresa.lower()}|{cargo.lower()}"
                if chave in vistos:
                    continue
                vistos.add(chave)

                registros.append({
                    "empresa": empresa,
                    "cargo": cargo,
                    "area": _classificar_area_email(f"{assunto} {corpo}"),
                    "plataforma": "E-mail",
                    "data_inscricao": data_insc,
                    "data_retorno": data_insc if status_vaga != "Em Andamento" else "",
                    "status": status_vaga,
                    "obs": f"Assunto: {assunto[:160]} | De: {remetente[:60]}"[:240],
                })
            except Exception:
                continue

        print(f"[E-mail] {len(registros)} registros capturados via Gmail IMAP.")
        return registros
    finally:
        try:
            mail.logout()
        except Exception:
            pass
