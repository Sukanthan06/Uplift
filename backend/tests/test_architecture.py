"""Architecture guards: cheap, static checks on properties that matter more
than any single unit test -- who's allowed to make real network calls, and
who's allowed to see the simulator's hidden ground truth."""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).parent.parent / "app"

ALLOWED_HTTPX_FILES = {"app/services/action_razorpay.py"}
ALLOWED_GROUND_TRUTH_FILES = {"app/services/reconciler.py"}


def _imports(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_only_action_razorpay_imports_httpx() -> None:
    for path in APP_ROOT.rglob("*.py"):
        rel = "app/" + str(path.relative_to(APP_ROOT)).replace("\\", "/")
        if rel in ALLOWED_HTTPX_FILES:
            continue
        tree = ast.parse(path.read_text())
        assert "httpx" not in _imports(tree), f"{rel} imports httpx -- only action_razorpay.py may"


def test_only_reconciler_references_ground_truth_path() -> None:
    for path in APP_ROOT.rglob("*.py"):
        rel = "app/" + str(path.relative_to(APP_ROOT)).replace("\\", "/")
        if rel in ALLOWED_GROUND_TRUTH_FILES:
            continue
        source = path.read_text()
        assert "ground_truth" not in source, (
            f"{rel} references ground_truth -- only reconciler.py may read the "
            "simulator's hidden ground truth file (CLAUDE.md non-negotiable #6)"
        )
