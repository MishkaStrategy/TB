from functools import wraps

from config import PUBLIC_ACCESS_ENABLED, is_authorized
from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings


_RUNTIME_SETTINGS = RuntimeSettings()


def public_access_enabled():
    """Return the live access mode with the environment as initial fallback."""
    return _RUNTIME_SETTINGS.public_access_enabled(default=PUBLIC_ACCESS_ENABLED)


def authorized(handler):
    @wraps(handler)
    async def wrapped(update, context):
        if public_access_enabled():
            return await handler(update, context)

        user = update.effective_user
        if user is None or not (
            is_authorized(user.id) or AccessRegistry().is_allowed(user.id)
        ):
            await update.effective_message.reply_text("Доступ к боту не разрешён.")
            return

        return await handler(update, context)

    return wrapped
