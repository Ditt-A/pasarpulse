"""Central credential loader for PasarPulse-MM.

The user's private ``setup_credentials.py`` lives in the project root. It may
expose module-level constants and/or a ``setup_credentials()`` function. Secret
values are never printed by this module.
"""
from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

SUPPORTED_KEYS: Final[tuple[str, ...]] = (
    "CDS_API_URL",
    "CDS_API_KEY",
    "CDSE_S3_ENDPOINT",
    "CDSE_S3_ACCESS_KEY",
    "CDSE_S3_SECRET_KEY",
    "CHROME_MAJOR_VERSION",
)

_loaded_roots: set[Path] = set()


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.upper().replace(" ", "_")
    markers = (
        "PASTE_", "YOUR_", "ISI_", "MASUKKAN_", "GANTI_", "CHANGE_ME",
        "<TOKEN>", "<KEY>", "TOKEN_KAMU", "ACCESS_KEY_KAMU", "SECRET_KEY_KAMU",
    )
    return not value or any(marker in normalized for marker in markers)


def _apply_mapping(values: Mapping[object, object]) -> None:
    for raw_key, raw_value in values.items():
        key, value = _clean(raw_key), _clean(raw_value)
        if key in SUPPORTED_KEYS and value and not _looks_like_placeholder(value):
            os.environ[key] = value


def load_project_credentials(
    required: Iterable[str] = (),
    *,
    project_root: str | Path | None = None,
    allow_missing_setup_file: bool = False,
    force_reload: bool = False,
) -> dict[str, str]:
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    if force_reload:
        _loaded_roots.discard(root)
        sys.modules.pop("setup_credentials", None)

    if root not in _loaded_roots:
        try:
            module = importlib.import_module("setup_credentials")
        except ModuleNotFoundError as exc:
            if allow_missing_setup_file:
                module = None
            else:
                raise RuntimeError(
                    "setup_credentials.py tidak ditemukan. Taruh file tersebut di folder utama "
                    "project, sejajar dengan config.yaml dan main_data_pipeline.ipynb."
                ) from exc

        if module is not None:
            setup = getattr(module, "setup_credentials", None)
            if callable(setup):
                returned = setup()
                if isinstance(returned, Mapping):
                    _apply_mapping(returned)
            _apply_mapping({key: getattr(module, key, None) for key in SUPPORTED_KEYS})
            for key in SUPPORTED_KEYS:
                current = _clean(os.getenv(key))
                if current and _looks_like_placeholder(current):
                    os.environ.pop(key, None)
        _loaded_roots.add(root)

    required_names = tuple(dict.fromkeys(str(name) for name in required))
    missing = [name for name in required_names if _looks_like_placeholder(_clean(os.getenv(name)))]
    if missing:
        raise RuntimeError(
            "Kredensial belum terisi atau masih placeholder: " + ", ".join(missing) +
            ". Periksa setup_credentials.py."
        )
    return {key: _clean(os.getenv(key)) for key in SUPPORTED_KEYS}


def credential_status(project_root: str | Path | None = None) -> dict[str, bool]:
    values = load_project_credentials(project_root=project_root, allow_missing_setup_file=True)
    return {
        "CDS_API_KEY": bool(values.get("CDS_API_KEY")),
        "CDSE_S3_ACCESS_KEY": bool(values.get("CDSE_S3_ACCESS_KEY")),
        "CDSE_S3_SECRET_KEY": bool(values.get("CDSE_S3_SECRET_KEY")),
        "CHROME_MAJOR_VERSION": bool(values.get("CHROME_MAJOR_VERSION")),
    }
