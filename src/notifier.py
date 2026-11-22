import os
import requests

def enviar_alerta_telegram(novos: list[dict], atualizados: list[dict]):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[Telegram] Credenciais ausentes; pulando notificação.")
        return

    if not novos and not atualizados:
        print("[Telegram] Nenhuma novidade para notificar.")
        return

    linhas = ["📊 *Candidaturas-Tracker-Pipeline — Atualização*"]

    if atualizados:
        linhas.append("\n🔄 *Mudanças de Status / Devolutivas:*")
        for v in atualizados:
            linhas.append(
                f"• *{v['empresa']}* — {v['cargo']}\n"
                f"  `{v.get('status_anterior')}` ➡️ *{v['status']}* ({v['plataforma']})"
            )

    if novos:
        linhas.append(f"\n🆕 *Novas Inscrições Registradas ({len(novos)}):*")
        for v in novos[:15]:
            linhas.append(f"• *{v['empresa']}* — {v['cargo']} ({v['plataforma']})")

    texto = "\n".join(linhas)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}, timeout=15)