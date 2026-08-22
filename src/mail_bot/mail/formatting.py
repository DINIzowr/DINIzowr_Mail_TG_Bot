from html import escape

from mail_bot.mail.gmail_client import MailMessage


def telegram_text(account_email: str, message: MailMessage) -> str:
    body = message.body.strip() or "(empty message)"
    return (
        f"<b>{escape(message.subject)}</b>\n"
        f"From: {escape(message.sender)}\n"
        f"Account: {escape(account_email)}\n"
        f"Received: {escape(message.received_at)}\n\n"
        f"{escape(body)}"
    )
