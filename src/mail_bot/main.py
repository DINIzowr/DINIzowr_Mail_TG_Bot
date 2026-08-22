import asyncio
import logging
import time

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from mail_bot.bot.handlers import OAuthRequest, create_router
from mail_bot.config import get_settings
from mail_bot.db.models import GmailAccount
from mail_bot.db.store import Store
from mail_bot.mail.gmail_client import GmailClient
from mail_bot.security import TokenCipher
from mail_bot.worker import run_worker


async def oauth_callback(request: web.Request) -> web.Response:
    state = request.query.get("state", "")
    code = request.query.get("code", "")
    states: dict[str, OAuthRequest] = request.app["oauth_states"]
    oauth_request = states.pop(state, None)
    if not oauth_request or time.time() - oauth_request.created_at > request.app["settings"].oauth_state_ttl_seconds:
        return web.Response(status=400, text="Invalid or expired OAuth state")
    if not code:
        return web.Response(status=400, text="Google did not return an authorization code")
    try:
        email, history_id, token_json = await asyncio.to_thread(
            request.app["gmail"].exchange_code,
            code,
            state,
            oauth_request.code_verifier,
        )
        import json

        token_data = json.loads(token_json)
        google_user_id = email
        account = GmailAccount(
            telegram_user_id=oauth_request.telegram_user_id,
            google_user_id=google_user_id,
            email=email,
            encrypted_refresh_token=request.app["cipher"].encrypt(token_data["refresh_token"]),
            last_history_id=history_id,
        )
        await request.app["store"].save_account(account)
    except Exception:
        logging.getLogger(__name__).exception("OAuth callback failed")
        return web.Response(status=500, text="Could not connect Gmail. Check application logs.")
    return web.Response(text="Gmail connected. You can close this page and return to Telegram.")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set")
    store = Store(settings.database_url)
    await store.init()
    cipher = TokenCipher(settings.encryption_key)
    gmail = GmailClient(settings.google_client_secrets_file, settings.google_redirect_uri, settings.max_attachment_bytes)
    states: dict[str, OAuthRequest] = {}
    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(store, gmail, cipher, states, settings))
    app = web.Application()
    app["oauth_states"] = states
    app["settings"] = settings
    app["gmail"] = gmail
    app["cipher"] = cipher
    app["store"] = store
    app.router.add_get("/oauth/callback", oauth_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    worker = asyncio.create_task(run_worker(bot, store, gmail, cipher, settings))
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        await bot.session.close()
        await runner.cleanup()
        await store.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
