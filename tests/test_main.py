from __future__ import annotations

import signal

import pytest

from voice_trigger.main import main


def test_main_exits_with_cli_return_code(monkeypatch):
    monkeypatch.setattr("voice_trigger.main.cli_main", lambda: 3)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 3


def test_main_registers_sigterm_handler_that_raises_keyboard_interrupt(monkeypatch):
    original_handler = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr("voice_trigger.main.cli_main", lambda: 0)
    try:
        with pytest.raises(SystemExit):
            main()
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, original_handler)
