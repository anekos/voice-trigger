import io

from voice_trigger.audio import CHUNK_SIZE, _read_exact, build_parec_command


def test_chunk_size_is_20ms_at_16khz_mono_16bit():
    assert CHUNK_SIZE == 640


def test_build_parec_command_without_source():
    assert build_parec_command(None) == [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
    ]


def test_build_parec_command_with_source():
    command = build_parec_command("alsa_input.example")
    assert command == [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
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
