import secrets
import time
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from mail_bot.config import Settings
from mail_bot.db.models import GmailAccount
from mail_bot.db.store import Store
from mail_bot.mail.gmail_client import GmailClient
from mail_bot.security import TokenCipher


@dataclass(frozen=True)
class OAuthRequest:
    telegram_user_id: int
    created_at: float
    code_verifier: str


def create_router(
    store: Store, gmail: GmailClient, cipher: TokenCipher, states: dict[str, OAuthRequest], settings: Settings
) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await store.upsert_user(message.from_user.id, message.chat.id)
        await message.answer("Mail bot is ready. Use /connect to add a Gmail account or /help for commands.")

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "/connect - connect Gmail\n/accounts - list connected accounts\n/disconnect <id> - disable an account\n"
            "New inbox messages are checked automatically."
        )

    @router.message(Command("connect"))
    async def connect(message: Message) -> None:
        await store.upsert_user(message.from_user.id, message.chat.id)
        state = secrets.token_urlsafe(32)
        try:
            url, code_verifier = gmail.authorization_url(state)
        except Exception:
            await message.answer("OAuth is not configured yet. Check GOOGLE_CLIENT_SECRETS_FILE.")
            return
        states[state] = OAuthRequest(message.from_user.id, time.time(), code_verifier)
        await message.answer(f"Open this link to connect Gmail:\n{url}")

    @router.message(Command("accounts"))
    async def accounts(message: Message) -> None:
        connected = await store.accounts_for_user(message.from_user.id)
        if not connected:
            await message.answer("No Gmail accounts connected.")
            return
        lines = [f"#{account.id} {account.email} ({'reauthorize' if account.needs_reauth else 'active'})" for account in connected]
        await message.answer("\n".join(lines))

    @router.message(Command("disconnect"))
    async def disconnect(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Usage: /disconnect <account id>")
            return
        account_id = int(parts[1])
        accounts_for_user = await store.accounts_for_user(message.from_user.id)
        account = next((item for item in accounts_for_user if item.id == account_id), None)
        if account is None:
            await message.answer("Account not found.")
            return
        await store.set_active(account.id, False)
        await message.answer(f"Disconnected {account.email}.")

    @router.callback_query(F.data.startswith("mail:"))
    async def mail_action(callback: CallbackQuery) -> None:
        _, action, account_id_text, message_id = (callback.data or "").split(":", 3)
        accounts_for_user = await store.accounts_for_user(callback.from_user.id)
        account = next((item for item in accounts_for_user if item.id == int(account_id_text)), None)
        if account is None or not account.active:
            await callback.answer("Account unavailable", show_alert=True)
            return
        try:
            await gmail.modify(cipher.decrypt(account.encrypted_refresh_token), message_id, action)
        except Exception:
            await callback.answer("Gmail action failed", show_alert=True)
            return
        await callback.answer("Done")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)

    return router


def message_keyboard(account: GmailAccount, message_id: str, gmail_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Read", callback_data=f"mail:read:{account.id}:{message_id}"),
             InlineKeyboardButton(text="Star", callback_data=f"mail:star:{account.id}:{message_id}"),
             InlineKeyboardButton(text="Trash", callback_data=f"mail:trash:{account.id}:{message_id}")],
            [InlineKeyboardButton(text="Open Gmail", url=gmail_url)],
        ]
    )
