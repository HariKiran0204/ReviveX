from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from recoverai_eval.errors import InferenceError, ModelQualityError


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def models_dir() -> Path:
    override = os.environ.get("RECOVERAI_ML_DIR")
    path = Path(override) if override else repo_root() / "data" / "ml" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def next_model_version(prefix: str = "recovery-v") -> str:
    existing: list[int] = []
    for child in models_dir().iterdir():
        name = child.name
        if not name.startswith(prefix):
            continue
        suffix = name.removeprefix(prefix)
        if suffix.isdigit():
            existing.append(int(suffix))
    nxt = (max(existing) + 1) if existing else 1
    return f"{prefix}{nxt}"


def version_dir(version: str) -> Path:
    path = models_dir() / version
    return path


def save_bundle(
    *,
    version: str,
    pipeline: Any,
    metadata: dict[str, Any],
    overwrite: bool = False,
) -> Path:
    target = version_dir(version)
    if target.exists() and not overwrite:
        raise ModelQualityError(
            "VERSION_EXISTS",
            f"Model version {version} already exists at {target}. Refusing to overwrite.",
        )
    target.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(pipeline, target / "model.joblib")
    meta_path = target / "metadata.json"
    metadata = dict(metadata)
    metadata["model_version"] = version
    metadata["saved_at"] = datetime.now(UTC).isoformat()
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return target


def load_bundle(version: str | None = None) -> tuple[Any, dict[str, Any]]:
    chosen = version or read_production_pointer()
    if chosen is None:
        raise InferenceError("MODEL_UNAVAILABLE", "No trained recovery model is available")
    target = version_dir(chosen)
    artifact = target / "model.joblib"
    meta_path = target / "metadata.json"
    if not artifact.exists():
        raise InferenceError("MODEL_UNAVAILABLE", f"Missing artifact for {chosen}")
    try:
        import joblib

        pipeline = joblib.load(artifact)
    except Exception as exc:
        raise InferenceError("MODEL_LOAD_FAILED", f"Failed to load {chosen}: {exc}") from exc
    metadata: dict[str, Any] = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    return pipeline, metadata


def write_production_pointer(version: str) -> None:
    pointer = models_dir() / "PRODUCTION"
    pointer.write_text(version, encoding="utf-8")


def read_production_pointer() -> str | None:
    pointer = models_dir() / "PRODUCTION"
    if not pointer.exists():
        return None
    text = pointer.read_text(encoding="utf-8").strip()
    return text or None
