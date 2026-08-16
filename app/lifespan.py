from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from adapters.telegram.handlers import register_handlers
from app.container import AppContainer
from config.settings import Settings
from webhooks.router import build_webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    container: AppContainer = app.state.container
    runner = container.runner
    await runner.recover_active_jobs()
    polling_task = getattr(app.state, "polling_task", None)
    try:
        yield
    finally:
        runner.cancel_watchers()
        for task in list(runner._watch_tasks.values()) + list(runner._watchdog_tasks.values()):
            task.cancel()
        if polling_task is not None:
            polling_task.cancel()
        await container.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None
    container = AppContainer(settings, bot=bot)
    app = FastAPI(title="AI Software Pipeline", lifespan=lifespan)
    app.state.container = container
    app.state.polling_task = None
    app.include_router(build_webhook_router(container))

    @app.get("/health")
    async def health():
        return {"ok": True}

    if bot is not None:
        dp = Dispatcher()
        register_handlers(dp, container.telegram_handlers)

        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan_with_polling(app: FastAPI):
            app.state.polling_task = asyncio.create_task(dp.start_polling(bot))
            async with original_lifespan(app):
                yield

        app.router.lifespan_context = lifespan_with_polling

    return app
