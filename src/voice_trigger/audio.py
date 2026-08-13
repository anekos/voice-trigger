"""Subprocess-based PCM capture via `parec`."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from types import TracebackType
from typing import IO, Self

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_FORMAT = "s16le"
BYTES_PER_SAMPLE = 2
CHUNK_DURATION_MS = 20
CHUNK_SIZE = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE * CHUNK_DURATION_MS // 1000


def build_parec_command(source: str | None) -> list[str]:
    command = [
        "parec",
        "--raw",
        f"--format={SAMPLE_FORMAT}",
        f"--rate={SAMPLE_RATE}",
        f"--channels={CHANNELS}",
    ]
    if source is not None:
        command.append(f"--device={source}")
    return command


def _read_exact(stream: IO[bytes], size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        piece = stream.read(size - len(buf))
        if not piece:
            break
        buf.extend(piece)
    return bytes(buf)


class AudioCapture:
    def __init__(self, source: str | None) -> None:
        self._source = source
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> Self:
        self._process = subprocess.Popen(
            build_parec_command(self._source),
            stdout=subprocess.PIPE,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process.wait()

    def chunks(self) -> Iterator[bytes]:
        assert self._process is not None
        assert self._process.stdout is not None
        stream = self._process.stdout
        while True:
            chunk = _read_exact(stream, CHUNK_SIZE)
            if len(chunk) < CHUNK_SIZE:
                break
            yield chunk
        self._process.wait()
        if self._process.returncode not in (0, None, -15):
            raise RuntimeError(
                f"parec exited unexpectedly with code {self._process.returncode}"
            )
