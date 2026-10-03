"""Password hashing.

Even for a demo, storing passwords in plain text is the kind of shortcut that
gets copied into something real. PBKDF2 is in the standard library, so hashing
them properly costs nothing.
"""

import hashlib
import hmac
import secrets

ITERATIONS = 120_000


def hash_password(password: str, salt: str | None = None) -> str:
    """Return "salt$hash". A new random salt is used unless one is supplied."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored "salt$hash"."""
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    # compare_digest rather than == so the comparison takes the same time
    # whether the first character is wrong or only the last one is.
    return hmac.compare_digest(hash_password(password, salt), stored)
