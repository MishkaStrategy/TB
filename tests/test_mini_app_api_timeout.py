import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "telegram-mini-app" / "src" / "api.ts"
APP = ROOT / "telegram-mini-app" / "src" / "App.tsx"


class MiniAppApiTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.api = API.read_text(encoding="utf-8")
        self.app = APP.read_text(encoding="utf-8")

    def test_requests_are_bounded_and_abort_the_fetch(self):
        self.assertIn("const REQUEST_TIMEOUT_MS = 10_000", self.api)
        self.assertIn("const controller = new AbortController()", self.api)
        self.assertIn("controller.abort()", self.api)
        self.assertIn("signal: controller.signal", self.api)
        self.assertIn("window.clearTimeout(timeout)", self.api)

    def test_timeout_and_network_failures_become_visible_errors(self):
        self.assertIn('error.name === "AbortError"', self.api)
        self.assertIn("Сервер настроек не отвечает", self.api)
        self.assertIn("Не удалось подключиться к серверу настроек", self.api)
        self.assertIn(".catch((loadError: unknown)", self.app)
        self.assertIn(".finally(() => active && setLoading(false))", self.app)

    def test_settings_get_is_not_cacheable_by_the_browser(self):
        self.assertIn('cache: "no-store"', self.api)
        self.assertIn('"/api/mini-app/settings"', self.api)


if __name__ == "__main__":
    unittest.main()
