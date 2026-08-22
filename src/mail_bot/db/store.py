from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mail_bot.db.models import Base, DeliveredMessage, GmailAccount, User


class Store:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def upsert_user(self, telegram_user_id: int, private_chat_id: int) -> User:
        async with self.sessions() as session:
            user = await session.get(User, telegram_user_id)
            if user is None:
                user = User(telegram_user_id=telegram_user_id, private_chat_id=private_chat_id)
                session.add(user)
            else:
                user.private_chat_id = private_chat_id
            await session.commit()
            return user

    async def accounts_for_user(self, telegram_user_id: int) -> Sequence[GmailAccount]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(GmailAccount)
                .where(GmailAccount.telegram_user_id == telegram_user_id)
                .order_by(GmailAccount.email)
            )
            return result.all()

    async def active_accounts(self) -> Sequence[GmailAccount]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(GmailAccount).where(GmailAccount.active.is_(True))
            )
            return result.all()

    async def save_account(self, account: GmailAccount) -> GmailAccount:
        async with self.sessions() as session:
            existing = await session.scalar(
                select(GmailAccount).where(
                    GmailAccount.telegram_user_id == account.telegram_user_id,
                    GmailAccount.google_user_id == account.google_user_id,
                )
            )
            if existing:
                existing.email = account.email
                existing.encrypted_refresh_token = account.encrypted_refresh_token
                existing.needs_reauth = False
                existing.active = True
                account = existing
            else:
                session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

    async def mark_delivered(self, account_id: int, message_id: str) -> bool:
        async with self.sessions() as session:
            existing = await session.scalar(
                select(DeliveredMessage).where(
                    DeliveredMessage.account_id == account_id,
                    DeliveredMessage.gmail_message_id == message_id,
                )
            )
            if existing:
                return False
            session.add(DeliveredMessage(account_id=account_id, gmail_message_id=message_id))
            await session.commit()
            return True

    async def update_history(self, account_id: int, history_id: str) -> None:
        async with self.sessions() as session:
            account = await session.get(GmailAccount, account_id)
            if account:
                account.last_history_id = history_id
                await session.commit()

    async def mark_needs_reauth(self, account_id: int) -> None:
        async with self.sessions() as session:
            account = await session.get(GmailAccount, account_id)
            if account:
                account.needs_reauth = True
                await session.commit()

    async def set_active(self, account_id: int, active: bool) -> None:
        async with self.sessions() as session:
            account = await session.get(GmailAccount, account_id)
            if account:
                account.active = active
                await session.commit()
