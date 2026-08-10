import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", ".venv-ci", "node_modules", "dist"}


def _is_sqlite_connect(call: ast.AST) -> bool:
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "connect"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "sqlite3"
    )


def _python_sources():
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
            continue
        yield path


class SQLiteConnectionHygieneTests(unittest.TestCase):
    def test_sqlite_contexts_close_connections_explicitly(self):
        offenders: list[str] = []
        for path in _python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.With, ast.AsyncWith)):
                    continue
                for item in node.items:
                    if _is_sqlite_connect(item.context_expr):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            msg=(
                "sqlite3.Connection context managers commit/rollback but do not close; "
                "wrap sqlite3.connect(...) in contextlib.closing(...) or use a "
                "store-specific closing connection factory:\n"
                + "\n".join(offenders)
            ),
        )


if __name__ == "__main__":
    unittest.main()
