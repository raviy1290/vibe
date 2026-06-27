"""Runtime configuration: where Ollama lives, which model to use, safety toggles.

Resolution order (lowest priority first):
  1. built-in defaults below
  2. ~/.vibe/config.json   (if present)
  3. environment variables (OLLAMA_HOST, VIBE_MODEL)
  4. CLI flags (applied by __main__)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".vibe" / "config.json"

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"


@dataclass
class Config:
    ollama_host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    max_iterations: int = 25
    # When True, skip the y/n confirmation before write/edit/bash for the session.
    auto_approve: bool = False
    # Everything the agent touches must resolve inside this directory.
    project_root: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        # 2. file
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                for key in ("ollama_host", "model", "temperature", "max_iterations"):
                    if key in data:
                        setattr(cfg, key, data[key])
            except (json.JSONDecodeError, OSError):
                pass  # a broken config file should never block startup
        # 3. environment
        cfg.ollama_host = os.environ.get("OLLAMA_HOST", cfg.ollama_host)
        cfg.model = os.environ.get("VIBE_MODEL", cfg.model)
        cfg.project_root = Path.cwd()
        return cfg
