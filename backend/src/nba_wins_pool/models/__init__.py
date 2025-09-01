"""Domain models for the NBA Wins Pool application."""

import os
from pathlib import Path

# Auto-import all model files in this directory
_current_dir = Path(__file__).parent
_model_files = [f.stem for f in _current_dir.glob("*.py") if f.is_file() and f.stem != "__init__"]

# Dynamically import all model modules
for _module_name in _model_files:
    exec(f"from .{_module_name} import *")  # noqa: F403
