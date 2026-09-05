"""Grammar-constrained speech recognition for a fixed set of phrases."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

import vosk

UNKNOWN = "[unk]"  # Vosk's unknown-word token; usable as a catch-all keyword


class SpeechRecognizer(Protocol):
    def AcceptWaveform(self, data: bytes) -> bool: ...

    def Result(self) -> str: ...


def normalize(text: str) -> str:
    # Vosk returns tokenized text ("ブラウザ ひらいて"); dropping all whitespace
    # lets phrases match however the user spaced them in their JSON.
    return "".join(text.split())


@dataclass(frozen=True)
class Recognition:
    text: str
    phrase: str | None  # the configured phrase that matched, if any


def build_grammar(phrases: Sequence[str]) -> str:
    # [unk] must be in the grammar so unrelated speech isn't mapped onto the
    # nearest configured phrase; dedupe in case it is also a configured phrase.
    return json.dumps(list(dict.fromkeys([*phrases, UNKNOWN])), ensure_ascii=False)


class CommandRecognizer:
    def __init__(self, recognizer: SpeechRecognizer, phrases: Sequence[str]) -> None:
        self._recognizer = recognizer
        self._phrases = {normalize(phrase): phrase for phrase in phrases}

    @classmethod
    def create(cls, model_path: Path, phrases: Sequence[str], sample_rate: int) -> Self:
        vosk.SetLogLevel(-1)
        recognizer = vosk.KaldiRecognizer(
            vosk.Model(str(model_path)), sample_rate, build_grammar(phrases)
        )
        return cls(recognizer, phrases)

    def process(self, chunk: bytes) -> Recognition | None:
        """Feed one PCM chunk; return the finalized utterance, if any."""
        if not self._recognizer.AcceptWaveform(chunk):
            return None
        text = json.loads(self._recognizer.Result())["text"]
        if not text:
            return None
        phrase = self._phrases.get(normalize(text))
        if phrase is None:
            # A configured [unk] acts as a catch-all for utterances that
            # matched no other phrase (silence still returns None above).
            phrase = self._phrases.get(UNKNOWN)
        return Recognition(text=text, phrase=phrase)
