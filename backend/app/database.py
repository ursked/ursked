from contextvars import ContextVar
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG,
)


# The session serving the current request (or scheduler job), so code that
# queues an email without being handed a session (EmailService.fire_and_forget)
# can put it in the same transaction as the change it announces.
current_session: ContextVar[Optional[AsyncSession]] = ContextVar("current_session", default=None)

# session.info key holding email factories queued since the last commit.
PENDING_EMAILS = "pending_emails"


class AppSession(AsyncSession):
    """AsyncSession that writes queued emails into the transaction it commits.

    `EmailService.fire_and_forget` cannot await, so it parks its factory in
    `info[PENDING_EMAILS]`. Just before each commit the factories run against
    this session and add their email_outbox rows, so the email exists exactly
    when the change it describes does: a rollback discards both.
    """

    async def commit(self) -> None:
        pending = self.info.pop(PENDING_EMAILS, None)
        if pending:
            from app.services.email_service import EmailService

            await EmailService.drain_pending(self, pending)
        await super().commit()

    async def rollback(self) -> None:
        self.info.pop(PENDING_EMAILS, None)
        await super().rollback()

    async def close(self) -> None:
        # Anything still parked was never committed, so it never happened.
        self.info.pop(PENDING_EMAILS, None)
        # A task that outlives its request (and inherited its context) must not
        # park an email here any more: nothing would ever commit it.
        self.info["closed"] = True
        await super().close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AppSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        token = current_session.set(session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            try:
                current_session.reset(token)
            except ValueError:  # teardown ran in another context; just clear it
                current_session.set(None)
            await session.close()
