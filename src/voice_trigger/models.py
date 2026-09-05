"""Locate Vosk speech models by language, downloading them on first use."""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

import httpx
from app_paths import get_paths

LANGUAGE_MODELS = {
    "ja": "vosk-model-small-ja-0.22",
    "en": "vosk-model-small-en-us-0.15",
}
MODEL_BASE_URL = "https://alphacephei.com/vosk/models"


def models_dir() -> Path:
    return get_paths("voice-trigger").user_data / "models"


def ensure_model(language: str) -> Path:
    """Return the model directory for `language`, downloading it if missing."""
    model_name = LANGUAGE_MODELS[language]
    target = models_dir() / model_name
    if target.is_dir():
        return target
    _download_and_extract(model_name, target)
    return target


def _download_and_extract(model_name: str, target: Path) -> None:
    url = f"{MODEL_BASE_URL}/{model_name}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Work in a sibling temp dir so the final rename is atomic: an interrupted
    # download or extraction never leaves a partial model at `target`.
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        tmp_dir = Path(tmp)
        zip_path = tmp_dir / f"{model_name}.zip"
        _download(url, zip_path)
        print(f"extracting {model_name}...", file=sys.stderr)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp_dir)
        extracted = tmp_dir / model_name
        if not extracted.is_dir():
            raise RuntimeError(f"unexpected archive layout: no {model_name}/ in {url}")
        extracted.rename(target)


def _download(url: str, destination: Path) -> None:
    print(f"downloading {url}", file=sys.stderr)
    try:
        with httpx.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0"))
            received = 0
            with destination.open("wb") as file:
                for data in response.iter_bytes():
                    file.write(data)
                    received += len(data)
                    _print_progress(received, total)
    except httpx.HTTPError as error:
        raise RuntimeError(f"failed to download {url}: {error}") from error
    print(file=sys.stderr)


def _print_progress(received: int, total: int) -> None:
    of_total = f" / {total // 1024 // 1024}MB" if total else ""
    print(
        f"\r{received // 1024 // 1024}MB{of_total}",
        end="",
        file=sys.stderr,
        flush=True,
    )
