import unittest

from localization import localize_text, translate_label


class QuarterHourLocalizationTests(unittest.TestCase):
    def test_translates_quarter_hour_settings_summary(self):
        source = (
            "🔔 <b>Уведомления о фандинге</b>\n\n"
            "Статус: ✅ включены\n"
            "Частота: каждые 15 мин.\n"
            "Следующая проверка: в ближайшую четверть часа\n\n"
            "Общий снимок всех бирж обновляется каждые 15 минут. "
            "В базе остаются только три последних снимка."
        )

        translated = localize_text(source, "en", "detailed")

        self.assertIn("Funding alerts", translated)
        self.assertIn("Frequency: every 15 min", translated)
        self.assertIn("Next check: at the next quarter hour", translated)
        self.assertIn("refreshed every 15 minutes", translated)
        self.assertIn("three latest snapshots", translated)

    def test_translates_quarter_hour_input_prompt_and_validation(self):
        prompt = (
            "Введите частоту уведомлений от 15 до 2880 минут.\n"
            "Шаг — 15 минут. Примеры: 15, 30, 45, 60 или 1,5ч."
        )
        validation = "Частота должна быть от 15 минут до 48 часов с шагом 15 минут."

        self.assertIn("15 to 2880 minutes", localize_text(prompt, "en"))
        self.assertIn("15-minute step", localize_text(prompt, "en"))
        self.assertIn("15-minute steps", localize_text(validation, "en"))

    def test_translates_interval_button(self):
        self.assertEqual(translate_label("⏱ 1 ч. 30 мин.", "en"), "⏱ 1 h 30 min")

    def test_compact_funding_alert_remains_bounded(self):
        source = (
            "🔔 <b>Фандинг пересёк заданный порог</b>\n"
            "Порог: 0.3%\n"
            "Направление: положительный\n"
            "Биржи: Bitunix\n\n"
            "🟢 <b>Bitunix</b> <code>BTCUSDT</code>: +0.5000%"
        )

        translated = localize_text(source, "en", "compact")

        self.assertEqual(
            translated,
            "🔔 Funding alert · threshold 0.3%\n"
            "🟢 <b>Bitunix</b> <code>BTCUSDT</code>: +0.5000%",
        )


if __name__ == "__main__":
    unittest.main()
