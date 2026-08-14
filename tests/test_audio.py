import io

import pytest

from voice_trigger import audio
from voice_trigger.audio import (
    CHUNK_SIZE,
    AudioCapture,
    _read_exact,
    build_parec_command,
)


def test_chunk_size_is_20ms_at_16khz_mono_16bit():
    assert CHUNK_SIZE == 640


def test_build_parec_command_without_source():
    assert build_parec_command(None) == [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
        "--latency-msec=20",
    ]


def test_build_parec_command_with_source():
    command = build_parec_command("alsa_input.example")
    assert command == [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
        "--latency-msec=20",
        "--device=alsa_input.example",
    ]


def test_read_exact_returns_full_size_from_stream():
    stream = io.BytesIO(b"x" * 100)
    assert _read_exact(stream, 50) == b"x" * 50


def test_read_exact_returns_short_read_on_eof():
    stream = io.BytesIO(b"x" * 10)
    assert _read_exact(stream, 50) == b"x" * 10


class _PartialReader:
    def __init__(self, pieces: list[bytes]) -> None:
        self._pieces = pieces

    def read(self, size: int) -> bytes:
        if not self._pieces:
            return b""
        return self._pieces.pop(0)


def test_read_exact_assembles_multiple_partial_reads():
    stream = _PartialReader([b"ab", b"cd", b"ef"])
    assert _read_exact(stream, 6) == b"abcdef"


def _use_fake_subprocess(monkeypatch: pytest.MonkeyPatch, shell_script: str) -> None:
    """Make AudioCapture spawn `sh -c shell_script` instead of `parec`."""
    monkeypatch.setattr(
        audio, "build_parec_command", lambda source: ["sh", "-c", shell_script]
    )


def test_audio_capture_chunks_yields_full_chunk_then_stops(
    monkeypatch: pytest.MonkeyPatch,
):
    data = b"x" * CHUNK_SIZE
    script = f"printf '%b' '{data.decode('latin-1')}'; exit 0"
    _use_fake_subprocess(monkeypatch, script)

    with AudioCapture(None) as capture:
        chunks = list(capture.chunks())

    assert chunks == [data]


def test_audio_capture_chunks_raises_on_nonzero_exit_with_partial_chunk(
    monkeypatch: pytest.MonkeyPatch,
):
    _use_fake_subprocess(monkeypatch, "printf 'short'; exit 2")

    with AudioCapture(None) as capture, pytest.raises(RuntimeError):
        list(capture.chunks())


def test_audio_capture_chunks_does_not_raise_on_clean_eof_with_partial_chunk(
    monkeypatch: pytest.MonkeyPatch,
):
    _use_fake_subprocess(monkeypatch, "printf 'short'; exit 0")

    with AudioCapture(None) as capture:
        chunks = list(capture.chunks())

    assert chunks == []


def test_audio_capture_exit_terminates_still_running_process(
    monkeypatch: pytest.MonkeyPatch,
):
    _use_fake_subprocess(monkeypatch, "sleep 5")

    with AudioCapture(None) as capture:
        process = capture._process
        assert process is not None
        assert process.poll() is None

    assert process.poll() is not None
