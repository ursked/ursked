import base64
import hashlib
import hmac
import secrets
from io import BytesIO
from typing import List

import pyotp
import qrcode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.middleware.auth import verify_password
from app.models.user import User, UserTwoFactor

BACKUP_CODE_COUNT = 5
# 8 bytes = 64 bits of entropy. At that strength a plain SHA-256 digest is not
# brute-forceable, so we avoid paying for 5 sequential bcrypt comparisons on
# every backup-code check.
BACKUP_CODE_BYTES = 8


def _generate_backup_code() -> str:
    raw = secrets.token_hex(BACKUP_CODE_BYTES).upper()
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def _hash_backup_code(code: str) -> str:
    normalised = code.strip().upper().replace("-", "")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class AuthService:
    @staticmethod
    async def authenticate_user(db: AsyncSession, tenant_id, username: str, password: str):
        stmt = select(User).where(
            User.tenant_id == tenant_id,
            (User.username == username) | (User.email == username),
            User.is_active == True,
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user and verify_password(password, user.password_hash):
            return user
        return None

    @staticmethod
    async def setup_2fa(db: AsyncSession, user: User) -> dict:
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user.email,
            issuer_name=settings.TOTP_ISSUER,
        )

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Plaintext codes are returned to the user exactly once here; only
        # their digests are persisted, so a database compromise does not hand
        # an attacker a working 2FA bypass.
        backup_codes = [_generate_backup_code() for _ in range(BACKUP_CODE_COUNT)]
        hashed_codes = [_hash_backup_code(c) for c in backup_codes]

        if user.two_factor:
            user.two_factor.totp_secret = secret
            user.two_factor.backup_codes = hashed_codes
            user.two_factor.status = "pending_setup"
            user.two_factor.totp_verified = False
        else:
            two_factor = UserTwoFactor(
                user_id=user.id,
                status="pending_setup",
                method="totp",
                totp_secret=secret,
                backup_codes=hashed_codes,
                totp_verified=False,
            )
            db.add(two_factor)

        await db.flush()

        return {
            "secret": secret,
            "qr_code_uri": provisioning_uri,
            "qr_code_base64": f"data:image/png;base64,{qr_base64}",
            "backup_codes": backup_codes,
        }

    @staticmethod
    async def verify_2fa_code(db: AsyncSession, user: User, code: str) -> bool:
        if not user.two_factor or not user.two_factor.totp_secret:
            return False

        totp = pyotp.TOTP(user.two_factor.totp_secret)
        if totp.verify(code, valid_window=1):
            if user.two_factor.status == "pending_setup":
                user.two_factor.status = "enabled"
                user.two_factor.totp_verified = True
                await db.flush()
            return True

        if user.two_factor.backup_codes:
            candidate = _hash_backup_code(code)
            remaining: List[str] = []
            matched = False
            for stored in user.two_factor.backup_codes:
                if not matched and hmac.compare_digest(stored, candidate):
                    matched = True  # consume this code, single use
                    continue
                remaining.append(stored)

            if matched:
                user.two_factor.backup_codes = remaining
                await db.flush()
                return True

        return False

    @staticmethod
    async def disable_2fa(db: AsyncSession, user: User) -> bool:
        if user.two_factor:
            user.two_factor.status = "disabled"
            user.two_factor.totp_secret = None
            user.two_factor.totp_verified = False
            user.two_factor.backup_codes = None
            await db.flush()
            return True
        return False
