"""Generate a VAPID keypair for Web Push.

Run once during VPS bootstrap (idempotent: refuses to overwrite without --force).
Single key is shared between prod and staging — same pattern as Signaris Desk.

Output:
- <out>  (private key, PEM)        — keep secret, mode 600 root:signaris
- stdout (public key, base64url)   — put into both .env files as
                                     SIGNARIS_HUB_VAPID_PUBLIC_KEY
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )
except ImportError:
    sys.stderr.write(
        "ERROR: cryptography not installed. Run:\n"
        "  ./.venv/bin/pip install cryptography\n"
    )
    raise SystemExit(2) from None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out",
        type=Path,
        default=Path("/opt/signaris-hub/vapid_private.pem"),
        help="path to private key PEM",
    )
    p.add_argument("--force", action="store_true", help="overwrite existing key")
    args = p.parse_args()

    if args.out.exists() and not args.force:
        sys.stderr.write(f"{args.out} already exists; pass --force to overwrite\n")
        return 1

    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(pem)
    os.chmod(args.out, 0o600)

    pub_raw = priv.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    pub_b64url = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()

    print(f"VAPID private key written to: {args.out}")
    print()
    print("Set SIGNARIS_HUB_VAPID_PUBLIC_KEY in BOTH .env files to:")
    print(pub_b64url)
    print()
    print(
        "Also set SIGNARIS_HUB_VAPID_PRIVATE_KEY_PATH=" + str(args.out)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
