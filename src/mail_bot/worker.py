import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from mail_bot.bot.handlers import message_keyboard
from mail_bot.config import Settings
from mail_bot.db.store import Store
from mail_bot.mail.formatting import telegram_text
from mail_bot.mail.gmail_client import GmailClient
from mail_bot.security import TokenCipher

logger = logging.getLogger(__name__)


async def sync_once(bot: Bot, store: Store, gmail: GmailClient, cipher: TokenCipher) -> None:
    for account in await store.active_accounts():
        try:
            messages, history_id = await gmail.list_messages(
                cipher.decrypt(account.encrypted_refresh_token), account.last_history_id
            )
            for mail in messages:
                if not await store.mark_delivered(account.id, mail.id):
                    continue
                await bot.send_message(
                    account.telegram_user_id,
                    telegram_text(account.email, mail),
                    reply_markup=message_keyboard(account, mail.id, mail.gmail_url),
                )
                for attachment in mail.attachments:
                    await bot.send_document(
                        account.telegram_user_id,
                        (attachment.filename, attachment.data),
                        caption=f"Attachment from {mail.subject}",
                    )
            await store.update_history(account.id, history_id)
        except TelegramBadRequest:
            logger.exception("Telegram delivery failed for account %s", account.id)
        except Exception:
            logger.exception("Gmail sync failed for account %s", account.id)
            await store.mark_needs_reauth(account.id)


async def run_worker(bot: Bot, store: Store, gmail: GmailClient, cipher: TokenCipher, settings: Settings) -> None:
    while True:
        await sync_once(bot, store, gmail, cipher)
        await asyncio.sleep(settings.poll_interval_seconds)
