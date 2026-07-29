"""User-facing boundary and button entrypoint for FVG instruments."""

from handlers.fvg_alert import fvg_symbol as _legacy_fvg_symbol
from handlers.fvg_instruments import show_fvg_instruments


async def fvg_symbol(update, context):
    """Open the new UI, while retaining legacy add/remove command arguments."""
    if not context.args:
        return await show_fvg_instruments(
            update.effective_message,
            update.effective_chat.id,
        )
    try:
        return await _legacy_fvg_symbol(update, context)
    except ValueError as error:
        message = update.effective_message
        if message is not None:
            await message.reply_text(str(error))
        return None
