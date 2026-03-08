"""Unit tests for credential_store module."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to sys.path so we can import credential_store
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_scripts_dir))

import credential_store  # noqa: E402


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch) -> Path:
    """Isolate the credential directory under a temporary HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _save_sample_identity(*, handle: str | None = None, name: str = "default") -> Path:
    """Save a minimal credential_store identity for testing."""
    return credential_store.save_identity(
        did="did:wba:awiki.ai:user:test",
        unique_id="user:test",
        user_id="user-1",
        private_key_pem=b"private-key",
        public_key_pem=b"public-key",
        jwt_token="jwt-token",
        display_name="Test User",
        handle=handle,
        name=name,
        did_document={"id": "did:wba:awiki.ai:user:test"},
    )


def test_save_identity_with_handle_persists_handle(isolated_home) -> None:
    """Handle-registered credentials should persist the handle field."""
    path = _save_sample_identity(handle="alice")

    raw_data = json.loads(path.read_text(encoding="utf-8"))
    loaded_data = credential_store.load_identity("default")
    identities = credential_store.list_identities()

    assert raw_data["handle"] == "alice"
    assert loaded_data is not None
    assert loaded_data["handle"] == "alice"
    assert identities[0]["handle"] == "alice"


def test_save_identity_without_handle_omits_handle_field(isolated_home) -> None:
    """Credentials without a handle should not store an empty handle field."""
    path = _save_sample_identity(handle=None)

    raw_data = json.loads(path.read_text(encoding="utf-8"))
    loaded_data = credential_store.load_identity("default")

    assert "handle" not in raw_data
    assert loaded_data is not None
    assert "handle" not in loaded_data
