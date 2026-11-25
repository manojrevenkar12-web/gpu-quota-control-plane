"""The control plane sees only what a real one would: it never imports the world, the simulation or the lab."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "gqc"


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add("." * node.level + node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_platform_and_service_never_import_the_world() -> None:
    for pkg in ("platform", "service"):
        for f in (SRC / pkg).rglob("*.py"):
            bad = [m for m in _imports(f) if any(x in m for x in ("world", "sim", "lab"))]
            assert not bad, f"{f}: {bad}"


def test_world_never_reads_platform_settings() -> None:
    for f in (SRC / "world").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "config.platform" not in text and "platform.yml" not in text and "designs" not in text, f
        assert not [m for m in _imports(f) if "platform" in m or "sim" in m or "lab" in m], f
