from __future__ import annotations

import json

from voice_trigger.recognizer import (
    CommandRecognizer,
    Recognition,
    Vocabulary,
    build_grammar,
    normalize,
)


class _FakeSpeechRecognizer:
    """Yields one canned result per chunk; None means the utterance continues."""

    def __init__(self, results: list[str | None]) -> None:
        self._results = iter(results)
        self._current: str | None = None

    def AcceptWaveform(self, data: bytes) -> bool:
        self._current = next(self._results)
        return self._current is not None

    def Result(self) -> str:
        assert self._current is not None
        return json.dumps({"text": self._current})


def test_normalize_drops_all_whitespace():
    assert normalize("ブラウザ ひらいて") == "ブラウザひらいて"
    assert normalize(" open  browser ") == "openbrowser"


def test_process_returns_none_mid_utterance():
    recognizer = CommandRecognizer(_FakeSpeechRecognizer([None]), ["open browser"])
    assert recognizer.process(b"") is None


def test_process_returns_none_for_empty_text():
    recognizer = CommandRecognizer(_FakeSpeechRecognizer([""]), ["open browser"])
    assert recognizer.process(b"") is None


def test_process_matches_phrase_ignoring_spacing():
    recognizer = CommandRecognizer(
        _FakeSpeechRecognizer(["ブラウザ ひらいて"]), ["ブラウザひらいて"]
    )
    assert recognizer.process(b"") == Recognition(
        text="ブラウザ ひらいて", phrase="ブラウザひらいて"
    )


def test_process_reports_unmatched_text_with_no_phrase():
    recognizer = CommandRecognizer(_FakeSpeechRecognizer(["[unk]"]), ["open browser"])
    assert recognizer.process(b"") == Recognition(text="[unk]", phrase=None)


def test_configured_unk_catches_any_unmatched_utterance():
    recognizer = CommandRecognizer(
        _FakeSpeechRecognizer(["[unk]", "[unk] [unk]", "open browser"]),
        ["open browser", "[unk]"],
    )
    assert recognizer.process(b"") == Recognition(text="[unk]", phrase="[unk]")
    assert recognizer.process(b"") == Recognition(text="[unk] [unk]", phrase="[unk]")
    # a real phrase still wins over the catch-all
    assert recognizer.process(b"") == Recognition(
        text="open browser", phrase="open browser"
    )


def test_configured_unk_does_not_fire_on_silence():
    recognizer = CommandRecognizer(_FakeSpeechRecognizer([""]), ["[unk]"])
    assert recognizer.process(b"") is None


class _FakeModel:
    def vosk_model_find_word(self, word: str) -> int:
        return 42 if word == "known" else -1


def test_vocabulary_membership():
    vocabulary = Vocabulary(_FakeModel())
    assert "known" in vocabulary
    assert "unknown" not in vocabulary


def test_build_grammar_appends_unk_without_duplicating_it():
    assert build_grammar(["open browser"]) == '["open browser", "[unk]"]'
    assert build_grammar(["[unk]", "つぎ"]) == '["[unk]", "つぎ"]'
