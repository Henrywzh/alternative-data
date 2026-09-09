"""Asia Markets Streamlit terminal — internal modules.

Submodules are exposed lazily for compatibility with callers using
``am.crypto`` or ``am.regime`` without forcing every renderer to import at
application startup.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_SUBMODULES = {
    "aerospace",
    "artifacts",
    "config",
    "core",
    "crypto",
    "explorer",
    "labour",
    "market",
    "market_page",
    "market_us",
    "overview",
    "page_registry",
    "population",
    "realestate",
    "regime",
    "regime_evidence",
    "regime_labels",
    "sidebar",
    "signals",
    "transport",
}


def __getattr__(name: str) -> Any:
    if name not in _SUBMODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
