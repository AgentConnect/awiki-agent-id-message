"""Send a verification code for Handle registration or recovery.

Usage:
    # Send a phone verification code
    python scripts/send_verification_code.py --phone +8613800138000

    # Next step: register a Handle with the received code
    python scripts/register_handle.py --handle alice --phone +8613800138000 --otp-code 123456

    # Next step: recover a Handle with the received code
    python scripts/recover_handle.py --handle alice --phone +8613800138000 --otp-code 123456

[INPUT]: SDK (verification code delivery), logging_config, phone number
[OUTPUT]: Verification-code delivery side effect and CLI guidance for the next step
[POS]: Non-interactive CLI for sending Handle verification codes; currently phone-only
       and designed for future delivery-channel expansion

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from utils import SDKConfig, create_user_service_client, normalize_phone, send_otp
from utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _require_phone(phone: str | None) -> str:
    """Return a normalized phone number or raise a usage error."""
    if phone is None or not phone.strip():
        raise ValueError(
            "A phone number is required. This script currently supports phone "
            "verification only."
        )
    return normalize_phone(phone)


async def send_verification_code(*, phone: str | None) -> None:
    """Send a verification code to a phone number."""
    normalized_phone = _require_phone(phone)
    logger.info("Sending verification code channel=phone target=%s", normalized_phone)

    config = SDKConfig()
    print("Service configuration:")
    print(f"  user-service: {config.user_service_url}")
    print(f"  DID domain  : {config.did_domain}")
    print(f"\nSending verification code to {normalized_phone}...")

    async with create_user_service_client(config) as client:
        await send_otp(client, normalized_phone)

    print("Verification code sent successfully.")
    print("Channel     : phone")
    print(f"Target      : {normalized_phone}")
    print("Next step   : Run register_handle.py or recover_handle.py with --otp-code <code>.")


def main() -> None:
    """CLI entry point."""
    configure_logging(console_level=None, mirror_stdio=True)

    parser = argparse.ArgumentParser(
        description=(
            "Send a verification code for Handle registration or recovery. "
            "Currently only phone delivery is supported."
        )
    )
    recipient_group = parser.add_mutually_exclusive_group(required=True)
    recipient_group.add_argument(
        "--phone",
        type=str,
        help=(
            "Phone number in international format with country code "
            "(e.g., +8613800138000 for China, +14155552671 for US). "
            "China local 11-digit numbers are auto-prefixed with +86."
        ),
    )
    args = parser.parse_args()

    try:
        asyncio.run(send_verification_code(phone=args.phone))
    except ValueError as exc:
        parser.exit(status=2, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
