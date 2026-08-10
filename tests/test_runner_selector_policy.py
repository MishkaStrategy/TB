import subprocess
import sys
import unittest


class RunnerSelectorPolicyTests(unittest.TestCase):
    def test_repository_workflows_use_allowed_selectors(self):
        result = subprocess.run(
            [sys.executable, ".github/scripts/check_runner_selectors.py"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
