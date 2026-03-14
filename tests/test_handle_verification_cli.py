"""Unit tests for verification-code CLI flows.

[INPUT]: send_verification_code/register_handle/recover_handle CLI modules,
         monkeypatched async SDK calls, and CLI argv
[OUTPUT]: Regression coverage for non-interactive verification-code workflows
[POS]: Handle CLI unit tests for send-first verification and OTP enforcement

[PROTOCOL]:
1. Update this header when logic changes
2. Check the containing folder's CLAUDE.md after updates
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import recover_handle as recover_cli  # noqa: E402
import register_handle as register_cli  # noqa: E402
import send_verification_code as verification_cli  # noqa: E402


class _AsyncClientContext:
    """Minimal async client context manager for CLI tests."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False


def test_send_verification_code_sends_phone_otp(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The verification CLI should normalize phone numbers and send OTPs."""
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        verification_cli,
        "create_user_service_client",
        lambda config: _AsyncClientContext(),
    )

    async def fake_send_otp(client: object, phone: str) -> dict[str, str]:
        del client
        captured["phone"] = phone
        return {"status": "ok"}

    monkeypatch.setattr(verification_cli, "send_otp", fake_send_otp)

    asyncio.run(verification_cli.send_verification_code(phone="13800138000"))

    assert captured["phone"] == "+8613800138000"
    output = capsys.readouterr().out
    assert "Verification code sent successfully." in output
    assert "Next step" in output


def test_register_handle_main_requires_preissued_otp(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """register_handle CLI should reject missing OTPs with send-first guidance."""
    monkeypatch.setattr(register_cli, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(
        register_cli,
        "create_user_service_client",
        lambda config: pytest.fail(f"Unexpected client creation: {config}"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_handle.py",
            "--handle",
            "alice",
            "--phone",
            "+8613800138000",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        register_cli.main()

    assert exc_info.value.code == 2
    assert "send_verification_code.py" in capsys.readouterr().err


def test_recover_handle_main_requires_preissued_otp(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """recover_handle CLI should reject missing OTPs with send-first guidance."""
    monkeypatch.setattr(recover_cli, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(
        recover_cli,
        "create_user_service_client",
        lambda config: pytest.fail(f"Unexpected client creation: {config}"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recover_handle.py",
            "--handle",
            "alice",
            "--phone",
            "+8613800138000",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        recover_cli.main()

    assert exc_info.value.code == 2
    assert "send_verification_code.py" in capsys.readouterr().err
