"""Runtime configuration for the RPA tools.

All values can be overridden with environment variables so that tests,
demos and production-like runs can use isolated directories and databases.
Defaults keep the original project behaviour (project-root relative paths).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw:
        return Path(raw).expanduser().resolve()
    return default.resolve()


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    upload_dir: Path
    demo_data_dir: Path
    output_dir: Path
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES

    def allowed_file_roots(self) -> tuple[Path, Path]:
        return (self.upload_dir, self.demo_data_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = _env_path("RPA_BASE_DIR", PROJECT_ROOT)
    return Settings(
        base_dir=base_dir,
        upload_dir=_env_path("RPA_UPLOAD_DIR", base_dir / "uploads"),
        demo_data_dir=_env_path("RPA_DEMO_DATA_DIR", base_dir / "demo_data"),
        output_dir=_env_path("RPA_OUTPUT_DIR", base_dir / "outputs"),
        max_upload_bytes=int(
            os.getenv("RPA_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
        ),
    )
