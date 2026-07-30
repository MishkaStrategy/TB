import unittest

from alerts.fvg_limited_service import FvgAlertService as LimitedFvgAlertService
from alerts.fvg_service_v2 import OutboxV2FvgAlertService


class OutboxV2FvgPolicyTests(unittest.TestCase):
    def test_outbox_v2_preserves_limited_recovery_policy(self):
        self.assertTrue(
            issubclass(OutboxV2FvgAlertService, LimitedFvgAlertService)
        )


if __name__ == "__main__":
    unittest.main()
