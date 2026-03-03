"""SDK configuration.

[INPUT]: None (pure data class)
[OUTPUT]: SDKConfig dataclass
[POS]: Centralized management of service URLs and domain configuration

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updates
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SDKConfig:
    """awiki system service configuration."""

    user_service_url: str = field(
        default_factory=lambda: os.environ.get(
            "E2E_USER_SERVICE_URL", "https://awiki.ai"
        )
    )
    molt_message_url: str = field(
        default_factory=lambda: os.environ.get(
            "E2E_MOLT_MESSAGE_URL", "https://awiki.ai"
        )
    )
    did_domain: str = field(
        default_factory=lambda: os.environ.get("E2E_DID_DOMAIN", "awiki.ai")
    )


__all__ = ["SDKConfig"]
