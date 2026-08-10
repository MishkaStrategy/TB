import unittest

from telegram.ext import Application

from alerts.scheduler import schedule_fvg_alerts


class SchedulerWiringTests(unittest.TestCase):
    def test_registers_only_confirmed_fifteen_minute_fvg_job(self):
        application = Application.builder().token("123456:TEST_TOKEN").build()

        schedule_fvg_alerts(application)

        confirmed = application.job_queue.get_jobs_by_name("fvg-confirmed-control")
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0].data["fvg_service"].__class__.__name__, "FvgAlertService")
        self.assertNotIn("mode", confirmed[0].data)
        self.assertEqual(
            len(application.job_queue.get_jobs_by_name("fvg-pre-control-t-minus-3")),
            0,
        )
        self.assertEqual(
            len(application.job_queue.get_jobs_by_name("fvg-rest-recovery")),
            1,
        )


if __name__ == "__main__":
    unittest.main()
