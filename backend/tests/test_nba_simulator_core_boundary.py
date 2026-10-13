"""Keep the simulator core free of I/O and app dependencies (see core/__init__.py)."""

import ast
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).parent.parent / "src" / "nba_wins_pool"
_CORE = _SRC / "services" / "nba_simulator" / "core"
_CORE_MODULE = "nba_wins_pool.services.nba_simulator.core"
_ALLOWED_THIRD_PARTY = {"numpy", "pandas", "scipy"}


def _imported_modules(path: Path) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _allowed(module: str) -> bool:
    top = module.split(".")[0]
    if top == "nba_wins_pool":
        return module == _CORE_MODULE or module.startswith(_CORE_MODULE + ".")
    return top in _ALLOWED_THIRD_PARTY or top in sys.stdlib_module_names or top == "__future__"


@pytest.mark.parametrize("path", sorted(_CORE.glob("*.py")), ids=lambda p: p.name)
def test_core_imports_only_core_and_numeric_libs(path):
    disallowed = [m for m in _imported_modules(path) if not _allowed(m)]
    assert not disallowed, f"{path.name} imports {disallowed}; the simulator core must not depend on the app or I/O"


def test_core_team_metadata_matches_app_team_data():
    core = json.loads((_CORE / "nba_teams.json").read_text())
    app = {
        t["abbreviation"]: {"conference": t["conference"], "division": t["division"]}
        for t in json.loads((_SRC / "scripts" / "data" / "nba_teams.json").read_text())
    }
    assert core == app
