from datetime import datetime
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import imaplib
import os


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    partes = decode_header(valor)
    out = []
    for txt, enc in partes:
        if isinstance(txt, bytes):
            out.append(txt.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(str(txt))
    return "".join(out).strip()


def _eh_irrelevante(texto: str) -> bool:
    t = (texto or "").lower()
    bloqueios = [
        "cartório",
        "cartorio",
        "certidão",
        "certidao",
        "cidadania",
        "bootcamp",
        "matrícula",
        "matricula",
    ]
    return any(b in t for b in bloqueios)


def _classificar_area(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["data", "dados", "analytics", "bi", "cientista", "sql", "power bi", "looker"]):
        return "Dados / BI"
    if any(k in t for k in ["ia", "inteligência artificial", "inteligencia artificial", "automação", "automacao", "rpa", "python", "banco de dados", "engenheiro(a) de ia"]):
        return "TI / Automação"
    if any(k in t for k in ["engenharia", "processos", "projeto", "qualidade", "produção", "producao"]):
        return "Engenharia / Processos"
    if any(k in t for k in ["financeiro", "controladoria", "contábil", "contabil"]):
        return "Financeiro / Controladoria"
    return "Comercial / Operações"


def extrair_hotmail() -> list[dict]:
    contas = [
        (os.getenv("HOTMAIL_1_EMAIL"), os.getenv("HOTMAIL_1_PASS")),
        (os.getenv("HOTMAIL_2_EMAIL"), os.getenv("HOTMAIL_2_PASS")),
    ]
    registros: list[dict] = []
    vistos: set[str] = set()

    for usuario, senha in contas:
        if not usuario or not senha:
            continue
        try:
            mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
            mail.login(usuario.strip(), senha.strip())
            mail.select("INBOX")

            _, data = mail.search(
                None,
                '(OR (TEXT "gupy") (OR (TEXT "indeed") (OR (TEXT "solides") (OR (TEXT "candidatura") (OR (TEXT "processo seletivo") (TEXT "entrevista"))))))',
            )
            ids = data[0].split()[-80:] if data and data[0] else []

            for msg_id in ids:
                try:
                    _, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    assunto = _decodificar(msg.get("Subject"))
                    remetente = _decodificar(msg.get("From"))

                    if _eh_irrelevante(f"{assunto} {remetente}"):
                        continue

                    try:
                        dt = parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%d")
                    except Exception:
                        dt = datetime.today().strftime("%Y-%m-%d")

                    texto_busca = f"{assunto} {remetente}".lower()
                    plataforma = (
                        "Gupy"
                        if "gupy" in texto_busca
                        else (
                            "Indeed"
                            if "indeed" in texto_busca
                            else ("Sólides" if "solides" in texto_busca else "E-mail")
                        )
                    )

                    if any(k in texto_busca for k in ["aprovado nos testes", "entrevista", "interview", "invitation to solve"]):
                        status = "Avançou de Etapa"
                    elif any(k in texto_busca for k in ["não avanç", "nao avanc", "encerrad", "feedback"]):
                        status = "Não Avançou"
                    else:
                        status = "Em Andamento"

                    empresa = remetente.split("<")[0].strip().strip('"')[:50] or "E-mail"
                    cargo = assunto[:80] or "Candidatura via E-mail"
                    chave = f"{empresa.lower()}|{cargo.lower()}|{plataforma.lower()}"
                    if chave in vistos:
                        continue
                    vistos.add(chave)

                    registros.append({
                        "empresa": empresa,
                        "cargo": cargo,
                        "area": _classificar_area(f"{assunto} {remetente}"),
                        "plataforma": plataforma,
                        "data_inscricao": dt,
                        "data_retorno": dt if status != "Em Andamento" else "",
                        "status": status,
                        "obs": f"Hotmail ({usuario.strip()})",
                    })
                except Exception:
                    continue

            mail.logout()
            print(f"[Hotmail] Varredura concluída em {usuario}.")
        except Exception as e:
            print(f"[Hotmail] Erro em {usuario}: {e}")

    return registros