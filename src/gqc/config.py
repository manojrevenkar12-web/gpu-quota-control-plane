"""Loads the YAML files in config/. Each package reads only the files it owns (AGENTS.md)."""

from __future__ import annotations

import copy
import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_SRC_ROOT = Path(__file__).resolve().parents[2]
# the repository root in a checkout; GQC_ROOT (or the working directory) when installed as a package
ROOT = Path(os.environ.get("GQC_ROOT", _SRC_ROOT if (_SRC_ROOT / "config").is_dir() else Path.cwd()))
CONFIG = ROOT / "config"
REPORTS = ROOT / "reports"


@cache
def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((CONFIG / f"{name}.yml").read_text(encoding="utf-8"))
    assert isinstance(data, dict), name
    return data


def platform() -> dict[str, Any]:
    return copy.deepcopy(_load("platform"))


def designs() -> dict[str, Any]:
    return copy.deepcopy(_load("designs"))


def seeds() -> dict[str, Any]:
    return copy.deepcopy(_load("seeds"))


def gates() -> dict[str, Any]:
    return copy.deepcopy(_load("gates"))


def merged(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out
