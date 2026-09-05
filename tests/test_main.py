from __future__ import annotations

import signal

import pytest

from voice_trigger.main import main


def test_main_invokes_the_cli(monkeypatch):
    calls = []
    monkeypatch.setattr("voice_trigger.main.cli_main", lambda: calls.append(True))
    main()
    assert calls == [True]


def test_main_registers_sigterm_handler_that_raises_keyboard_interrupt(monkeypatch):
    original_handler = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr("voice_trigger.main.cli_main", lambda: None)
    try:
        main()
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, original_handler)
