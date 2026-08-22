from mail_bot.mail.formatting import telegram_text
from mail_bot.mail.gmail_client import MailMessage


def test_telegram_text_escapes_html() -> None:
    message = MailMessage(
        id="1", thread_id="t", sender="a<b@example.com>", subject="<hello>",
        received_at="2026-08-22T12:00:00+00:00", body="2 < 3", attachments=(), gmail_url="https://gmail.test/1"
    )
    result = telegram_text("user@example.com", message)
    assert "&lt;hello&gt;" in result
    assert "2 &lt; 3" in result
    assert "a&lt;b@example.com&gt;" in result
