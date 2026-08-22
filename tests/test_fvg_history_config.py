import unittest

from database import fvg_history_config as config


class FvgHistoryConfigTests(unittest.TestCase):
    def test_archive_retention_is_enabled_and_bounded_by_default(self):
        self.assertTrue(config.FVG_HISTORY_ARCHIVE_ENABLED)
        self.assertEqual(
            config.FVG_HISTORY_ARCHIVE_PATH,
            "data/archive/fvg_history.sqlite3",
        )
        self.assertEqual(config.FVG_HISTORY_RETENTION_DAYS, 90)
        self.assertEqual(config.FVG_HISTORY_ARCHIVE_BATCH_SIZE, 500)
        self.assertEqual(config.FVG_HISTORY_ARCHIVE_MAX_BATCHES, 10)


if __name__ == "__main__":
    unittest.main()
