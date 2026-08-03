import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.runtime_lifecycle import RuntimeLifecycleStore


UTC = timezone.utc


class RuntimeLifecycleStoreTests(unittest.TestCase):
    def test_records_start_running_and_clean_stop(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            instance_id = store.begin_start(
                instance_id="instance-1",
                pid=123,
                now=started,
                details={"release": "abc"},
            )

            self.assertEqual(instance_id, "instance-1")
            self.assertTrue(
                store.transition(
                    instance_id,
                    "running",
                    phase="post_init",
                    now=started + timedelta(seconds=1),
                )
            )
            deadline = started + timedelta(seconds=30)
            self.assertTrue(
                store.transition(
                    instance_id,
                    "stopping",
                    phase="post_stop",
                    now=started + timedelta(seconds=2),
                    deadline=deadline,
                )
            )
            self.assertTrue(
                store.transition(
                    instance_id,
                    "stopped",
                    phase="post_stop",
                    now=started + timedelta(seconds=3),
                    outcome="clean",
                    details={"drained": True},
                )
            )

            state = store.current()
            self.assertEqual(state["instance_id"], instance_id)
            self.assertEqual(state["pid"], 123)
            self.assertEqual(state["status"], "stopped")
            self.assertEqual(state["shutdown_outcome"], "clean")
            self.assertEqual(state["details"], {"drained": True})
            self.assertEqual(state["shutdown_deadline_at"], deadline.isoformat())
            events = store.events(instance_id=instance_id, limit=10)
            self.assertEqual(
                [event["status"] for event in events],
                ["stopped", "stopping", "running", "starting"],
            )

    def test_new_start_marks_previous_active_instance_interrupted(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            store.begin_start(instance_id="old", pid=1, now=started)
            store.transition(
                "old",
                "running",
                phase="post_init",
                now=started + timedelta(seconds=1),
            )

            store.begin_start(
                instance_id="new",
                pid=2,
                now=started + timedelta(seconds=10),
            )

            self.assertEqual(store.current()["instance_id"], "new")
            previous_events = store.events(instance_id="old", limit=10)
            interrupted = [
                event for event in previous_events if event["status"] == "interrupted"
            ]
            self.assertEqual(len(interrupted), 1)
            self.assertEqual(interrupted[0]["phase"], "previous_instance")
            self.assertEqual(
                interrupted[0]["details"]["replacement_instance_id"],
                "new",
            )

    def test_terminal_previous_instance_is_not_marked_interrupted(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            store.begin_start(instance_id="old", pid=1, now=started)
            store.transition(
                "old",
                "stopped",
                phase="post_stop",
                now=started + timedelta(seconds=1),
                outcome="clean",
            )
            store.begin_start(
                instance_id="new",
                pid=2,
                now=started + timedelta(seconds=2),
            )

            statuses = {
                event["status"] for event in store.events(instance_id="old", limit=10)
            }
            self.assertNotIn("interrupted", statuses)

    def test_transition_rejects_stale_instance_and_prune_is_bounded(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            started = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
            store.begin_start(instance_id="old", pid=1, now=started)
            store.transition(
                "old",
                "running",
                phase="post_init",
                now=started + timedelta(seconds=1),
            )
            store.begin_start(
                instance_id="current",
                pid=2,
                now=started + timedelta(days=3),
            )

            self.assertFalse(
                store.transition(
                    "old",
                    "failed",
                    phase="late_writer",
                    now=started + timedelta(days=3, seconds=1),
                )
            )
            before = len(store.events(limit=20))
            deleted = store.prune(
                retention_days=1,
                batch_size=1,
                now=started + timedelta(days=3),
            )
            after = len(store.events(limit=20))
            self.assertEqual(deleted, 1)
            self.assertEqual(after, before - 1)


if __name__ == "__main__":
    unittest.main()
