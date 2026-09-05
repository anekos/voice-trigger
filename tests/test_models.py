from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from voice_trigger import models


def _model_zip(top_level_dir: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{top_level_dir}/conf", "fake model data")
    return buffer.getvalue()


def _fake_download(payload: bytes):
    def download(url: str, destination: Path) -> None:
        destination.write_bytes(payload)

    return download


def _fail_download(url: str, destination: Path) -> None:
    raise AssertionError("download should not have been attempted")


def test_ensure_model_returns_existing_dir_without_downloading(tmp_path, monkeypatch):
    model_name = models.LANGUAGE_MODELS["ja"]
    target = tmp_path / model_name
    target.mkdir()
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "_download", _fail_download)
    assert models.ensure_model("ja") == target


def test_ensure_model_downloads_and_extracts_when_missing(
    tmp_path, monkeypatch, capsys
):
    model_name = models.LANGUAGE_MODELS["en"]
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "_download", _fake_download(_model_zip(model_name)))
    result = models.ensure_model("en")
    assert result == tmp_path / model_name
    assert (result / "conf").read_text() == "fake model data"


def test_ensure_model_rejects_unexpected_archive_layout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(
        models, "_download", _fake_download(_model_zip("something-else"))
    )
    with pytest.raises(RuntimeError):
        models.ensure_model("en")
    # a failed download/extract must not leave a partial model directory behind
    assert not (tmp_path / models.LANGUAGE_MODELS["en"]).exists()
