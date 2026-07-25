from functools import wraps

from config import PUBLIC_ACCESS_ENABLED, is_authorized
from database.access_control import AccessRegistry


def authorized(handler):
    @wraps(handler)
    async def wrapped(update, context):
        if PUBLIC_ACCESS_ENABLED:
            return await handler(update, context)

        user = update.effective_user
        if user is None or not (
            is_authorized(user.id) or AccessRegistry().is_allowed(user.id)
        ):
            await update.effective_message.reply_text("Доступ к боту не разрешён.")
            return

        return await handler(update, context)

    return wrapped
