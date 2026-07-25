"""User-facing error boundary for the FVG symbol command."""

from handlers.fvg_alert import fvg_symbol as _fvg_symbol


async def fvg_symbol(update, context):
    """Convert settings quota errors into a Telegram response."""
    try:
        return await _fvg_symbol(update, context)
    except ValueError as error:
        message = update.effective_message
        if message is not None:
            await message.reply_text(str(error))
        return None
