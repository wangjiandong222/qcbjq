from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Optional

from app.core.config import settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _sign(payload: str) -> str:
    return hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_token(user_id: int) -> str:
    exp = int(time.time() + settings.token_expire_minutes * 60)
    payload = f"{user_id}.{exp}"
    token = f"{payload}.{_sign(payload)}"
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("utf-8")


def parse_token(token: str) -> Optional[int]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        user_id, exp, sig = decoded.split(".", 2)
        payload = f"{user_id}.{exp}"
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if int(exp) < int(time.time()):
            return None
        return int(user_id)
    except Exception:
        return None
