import unittest

from config import USER_BLOCK_STATUS_ENABLED, parse_ratio


class OutboxConfigTests(unittest.TestCase):
    def test_blocked_user_suppression_is_mandatory(self):
        self.assertTrue(USER_BLOCK_STATUS_ENABLED)

    def test_parse_ratio_accepts_jitter_bounds(self):
        self.assertEqual(parse_ratio(None, 0.2, "JITTER"), 0.2)
        self.assertEqual(parse_ratio("0", 0.2, "JITTER"), 0.0)
        self.assertEqual(parse_ratio("0.35", 0.2, "JITTER"), 0.35)
        self.assertEqual(parse_ratio("1", 0.2, "JITTER"), 1.0)

    def test_parse_ratio_rejects_values_outside_zero_to_one(self):
        for value in ("-0.01", "1.01", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_ratio(value, 0.2, "JITTER")


if __name__ == "__main__":
    unittest.main()
