"""Telegram bot subclass that applies per-chat language and message mode."""

from __future__ import annotations

import re

from telegram.ext import ExtBot

from database.user_preferences import UserPreferences
from localization import CURRENT_CHAT_ID, localize_text, translate_label


def _localize_safely(text: str, language: str, mode: str) -> str:
    if language != "en":
        return localize_text(text, language, mode)
    protected = text.replace(
        "Поддерживаются Bitunix, Binance, Bybit, Bitget, Gate и BingX.",
        "Supported exchanges: Bitunix, Binance, Bybit, Bitget, Gate and BingX.",
    ).replace("Фандинг BingX", "BingX funding")
    protected = re.sub(r"\bиз\b", "__RU_OF__", protected)
    protected = protected.replace("из", "__RU_IZ__")
    translated = localize_text(protected, language, mode)
    return translated.replace("__RU_OF__", "of").replace("__RU_IZ__", "из")


class LocalizedExtBot(ExtBot):
    __slots__ = ("user_preferences",)

    def __init__(self, *args, preferences: UserPreferences | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "user_preferences", preferences or UserPreferences())

    def _chat_preferences(self, chat_id=None) -> dict:
        resolved = chat_id if chat_id is not None else CURRENT_CHAT_ID.get()
        if resolved is None:
            return {"language": "ru", "message_mode": "detailed"}
        try:
            return self.user_preferences.user(int(resolved))
        except (TypeError, ValueError):
            return {"language": "ru", "message_mode": "detailed"}

    def _localize_markup(self, reply_markup, language: str):
        if reply_markup is None or language != "en" or not hasattr(reply_markup, "to_dict"):
            return reply_markup
        data = reply_markup.to_dict()
        for key in ("inline_keyboard", "keyboard"):
            for row in data.get(key, []):
                for button in row:
                    if isinstance(button, dict) and isinstance(button.get("text"), str):
                        button["text"] = translate_label(button["text"], language)
        try:
            return type(reply_markup).de_json(data, self)
        except Exception:
            return reply_markup

    async def send_message(self, chat_id, text, *args, **kwargs):
        preferences = self._chat_preferences(chat_id)
        kwargs["reply_markup"] = self._localize_markup(
            kwargs.get("reply_markup"), preferences["language"]
        )
        return await super().send_message(
            chat_id,
            _localize_safely(text, preferences["language"], preferences["message_mode"]),
            *args,
            **kwargs,
        )

    async def edit_message_text(self, text, *args, **kwargs):
        preferences = self._chat_preferences(kwargs.get("chat_id"))
        kwargs["reply_markup"] = self._localize_markup(
            kwargs.get("reply_markup"), preferences["language"]
        )
        return await super().edit_message_text(
            _localize_safely(text, preferences["language"], preferences["message_mode"]),
            *args,
            **kwargs,
        )

    async def edit_message_reply_markup(self, *args, **kwargs):
        preferences = self._chat_preferences(kwargs.get("chat_id"))
        kwargs["reply_markup"] = self._localize_markup(
            kwargs.get("reply_markup"), preferences["language"]
        )
        return await super().edit_message_reply_markup(*args, **kwargs)

    async def answer_callback_query(self, callback_query_id, *args, text=None, **kwargs):
        if text is not None:
            preferences = self._chat_preferences()
            text = _localize_safely(
                text,
                preferences["language"],
                preferences["message_mode"],
            )
        return await super().answer_callback_query(
            callback_query_id,
            *args,
            text=text,
            **kwargs,
        )
