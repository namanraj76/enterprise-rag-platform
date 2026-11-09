"""Email and Google authentication with signed, revocable database sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
import time
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select

from app.core.database import EmailVerification, OAuthState, SessionLocal, User, UserSession
from app.utils.logging import logger

SESSION_COOKIE = "aurelia_session"
OAUTH_STATE_COOKIE = "aurelia_oauth_state"
SESSION_MAX_AGE = 30 * 24 * 60 * 60
OAUTH_STATE_MAX_AGE = 10 * 60
VERIFICATION_MAX_AGE = 24 * 60 * 60
LOCAL_SESSION_SECRET = "aurelia-local-development-session-secret-only"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _setting(name: str) -> str:
    return os.getenv(name, "").strip()


def _app_base_url() -> str:
    configured = _setting("APP_BASE_URL")
    if configured:
        return configured.rstrip("/")
    if _setting("APP_ENV").lower() != "production":
        return "http://127.0.0.1:8000"
    return ""


def _session_secret() -> bytes:
    secret = _setting("SESSION_SECRET")
    production = _setting("APP_ENV").lower() == "production"
    if production and not _app_base_url().lower().startswith("https://"):
        raise HTTPException(
            status_code=503,
            detail="Production authentication requires an HTTPS APP_BASE_URL.",
        )
    if not secret and not production:
        secret = LOCAL_SESSION_SECRET
    if len(secret) < 32:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured: SESSION_SECRET must be at least 32 characters.",
        )
    return secret.encode("utf-8")


def _secure_cookies() -> bool:
    return _app_base_url().lower().startswith("https://")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _url_origin(value: str, *, origin_header: bool = False) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (origin_header and parsed.path not in {"", "/"})
            or parsed.query
            or parsed.fragment
        ):
            return None
        scheme = parsed.scheme.lower()
        port = parsed.port or (443 if scheme == "https" else 80)
        return scheme, parsed.hostname.encode("idna").decode("ascii").lower(), port
    except (ValueError, UnicodeError):
        return None


def csrf_origin_is_valid(request: Request) -> bool:
    """Require same-origin Origin or Referer for state-changing cookie requests."""
    configured_origin = _url_origin(_app_base_url())
    if configured_origin is None:
        return False
    origin = request.headers.get("origin")
    if origin is not None:
        request_origin = _url_origin(origin, origin_header=True)
    else:
        referer = request.headers.get("referer")
        request_origin = _url_origin(referer) if referer else None
    return request_origin == configured_origin


def require_same_origin(request: Request) -> None:
    """Protect anonymous authentication POSTs from cross-site request forgery too."""
    if not csrf_origin_is_valid(request):
        raise HTTPException(status_code=403, detail="CSRF origin validation failed")


def csrf_protected_method(method: str) -> bool:
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def _signed_session_value(session_id: str) -> str:
    signature = hmac.new(_session_secret(), session_id.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{session_id}.{signature}"


def _verified_session_id(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    session_id, signature = value.rsplit(".", 1)
    if len(session_id) != 64 or any(char not in "0123456789abcdef" for char in session_id):
        return None
    expected = hmac.new(
        _session_secret(), session_id.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return session_id if hmac.compare_digest(signature, expected) else None


@dataclass(frozen=True)
class UserView:
    """Minimal current-user shape independent of a closed SQLAlchemy session."""

    id: str
    email: str
    name: str
    picture: str | None


def current_user(request: Request) -> UserView:
    """Resolve only a valid, non-expired server-side session."""
    session_id = _verified_session_id(request.cookies.get(SESSION_COOKIE))
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    with SessionLocal() as db:
        session_row = db.get(UserSession, _hash(session_id))
        if session_row is None or session_row.expires_at <= int(time.time()):
            if session_row is not None:
                db.delete(session_row)
                db.commit()
            raise HTTPException(status_code=401, detail="Authentication required")
        user = db.get(User, session_row.user_id)
        if user is None or not user.email_verified:
            raise HTTPException(status_code=401, detail="Authentication required")
        if csrf_protected_method(request.method) and not csrf_origin_is_valid(request):
            raise HTTPException(status_code=403, detail="CSRF origin validation failed")
        # Return a detached value object, not a live ORM entity from a closed session.
        return UserView(user.id, user.email, user.name, user.picture)


def create_user_session(user_id: str) -> str:
    """Create an opaque random session ID and persist only its hash."""
    session_id = secrets.token_hex(32)
    cookie_value = _signed_session_value(session_id)
    with SessionLocal() as db:
        db.add(
            UserSession(
                token_hash=_hash(session_id),
                user_id=user_id,
                expires_at=int(time.time()) + SESSION_MAX_AGE,
            )
        )
        db.commit()
    return cookie_value


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    )
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def _password_matches(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "scrypt" or (n, r, p) != ("16384", "8", "1"):
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


_DUMMY_PASSWORD_HASH = _password_hash("invalid-account-placeholder")


def create_email_verification(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.execute(delete(EmailVerification).where(EmailVerification.user_id == user_id))
        db.add(
            EmailVerification(
                token_hash=_hash(token),
                user_id=user_id,
                expires_at=int(time.time()) + VERIFICATION_MAX_AGE,
            )
        )
        db.commit()
    return token


def send_verification_email(email: str, token: str) -> None:
    """Deliver a one-time token; local development prints it, production requires SMTP."""
    host = _setting("SMTP_HOST")
    if not host:
        if _setting("APP_ENV").lower() == "production":
            raise RuntimeError("Email delivery is unavailable; configure SMTP_HOST and SMTP_FROM.")
        logger.warning(
            "Development email verification for %s: POST /auth/verify-email with token=%s",
            email,
            token,
        )
        return

    implicit_tls = _setting("SMTP_USE_SSL").lower() in {"1", "true", "yes"}
    starttls_enabled = _setting("SMTP_STARTTLS").lower() != "false"
    if _setting("APP_ENV").lower() == "production" and not (implicit_tls or starttls_enabled):
        raise RuntimeError("Production SMTP must use TLS.")
    sender = _setting("SMTP_FROM")
    if not sender:
        raise RuntimeError("SMTP_FROM is required when SMTP_HOST is configured.")
    message = EmailMessage()
    message["Subject"] = "Verify your Aurelia email address"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Use this one-time token to verify your Aurelia account within 24 hours:\n\n"
        f"{token}\n\n"
        "Submit it to POST /auth/verify-email as JSON: {\"token\": \"...\"}."
    )
    port = int(_setting("SMTP_PORT") or "587")
    timeout = 15
    context = ssl.create_default_context()
    if implicit_tls:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            _smtp_login_and_send(smtp, message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if starttls_enabled:
                smtp.starttls(context=context)
                smtp.ehlo()
            _smtp_login_and_send(smtp, message)


def _smtp_login_and_send(smtp, message: EmailMessage) -> None:
    username = _setting("SMTP_USERNAME")
    password = _setting("SMTP_PASSWORD")
    if username:
        smtp.login(username, password)
    smtp.send_message(message)


def register_email_user(email: str, password: str, name: str = "") -> str:
    if _setting("APP_ENV").lower() == "production" and (
        not _setting("SMTP_HOST") or not _setting("SMTP_FROM")
    ):
        raise HTTPException(
            status_code=503,
            detail="Email registration is unavailable until SMTP_HOST and SMTP_FROM are configured.",
        )
    if (
        _setting("APP_ENV").lower() == "production"
        and _setting("SMTP_USE_SSL").lower() not in {"1", "true", "yes"}
        and _setting("SMTP_STARTTLS").lower() == "false"
    ):
        raise HTTPException(status_code=503, detail="Production SMTP must use TLS.")
    normalized_email = email.strip().casefold()
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == normalized_email)):
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        user = User(
            id=str(uuid.uuid4()),
            email=normalized_email,
            name=name.strip()[:255],
            password_hash=_password_hash(password),
            email_verified=False,
        )
        db.add(user)
        db.commit()
        user_id = user.id
    token = create_email_verification(user_id)
    try:
        send_verification_email(normalized_email, token)
    except Exception as exc:
        logger.error("Verification email delivery failed for %s: %s", normalized_email, exc)
        raise HTTPException(
            status_code=503,
            detail="Verification email could not be sent. You can request another email.",
        ) from exc
    return user_id


def verify_email_token(token: str) -> bool:
    if not token or len(token) > 256:
        return False
    now = int(time.time())
    with SessionLocal() as db:
        user_id = db.execute(
            delete(EmailVerification)
            .where(
                EmailVerification.token_hash == _hash(token),
                EmailVerification.expires_at > now,
            )
            .returning(EmailVerification.user_id)
        ).scalar_one_or_none()
        if user_id is None:
            return False
        user = db.get(User, user_id)
        if user is None:
            db.commit()
            return False
        user.email_verified = True
        db.commit()
        return True


def authenticate_email_user(email: str, password: str) -> UserView | None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().casefold()))
        if user is None:
            # Run the same fixed-cost hash check for unknown addresses.
            _password_matches(password, _DUMMY_PASSWORD_HASH)
            return None
        if not _password_matches(password, user.password_hash):
            return None
        if not user.email_verified:
            raise HTTPException(status_code=403, detail="Verify your email before signing in.")
        return UserView(user.id, user.email, user.name, user.picture)


def invalidate_session(cookie_value: str | None) -> None:
    session_id = _verified_session_id(cookie_value)
    if session_id:
        with SessionLocal() as db:
            db.execute(delete(UserSession).where(UserSession.token_hash == _hash(session_id)))
            db.commit()


def google_configuration() -> tuple[str, str, str]:
    client_id = _setting("GOOGLE_CLIENT_ID")
    client_secret = _setting("GOOGLE_CLIENT_SECRET")
    base_url = _app_base_url()
    if not client_id or not client_secret or not base_url:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured: set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and APP_BASE_URL.",
        )
    return client_id, client_secret, f"{base_url}/auth/google/callback"


def create_oauth_state() -> str:
    state = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.execute(delete(OAuthState).where(OAuthState.expires_at <= int(time.time())))
        db.add(
            OAuthState(
                state_hash=_hash(state),
                expires_at=int(time.time()) + OAUTH_STATE_MAX_AGE,
            )
        )
        db.commit()
    return state


def consume_oauth_state(state: str) -> bool:
    with SessionLocal() as db:
        result = db.execute(
            delete(OAuthState).where(
                OAuthState.state_hash == _hash(state),
                OAuthState.expires_at > int(time.time()),
            )
        )
        db.commit()
        return result.rowcount == 1


def exchange_google_code(code: str, redirect_uri: str) -> dict:
    client_id, client_secret, _ = google_configuration()
    try:
        token_response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Missing Google access token")
        user_response = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": "Bearer " + access_token},
            timeout=10,
        )
        user_response.raise_for_status()
        return user_response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Google sign-in could not be verified.") from exc


def provision_google_user(profile: dict) -> UserView:
    subject = profile.get("sub")
    email = profile.get("email")
    verified = profile.get("email_verified")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or verified not in (True, "true")
    ):
        raise HTTPException(status_code=403, detail="Google must provide a verified email address.")
    normalized_email = email.strip().casefold()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.google_sub == subject))
        email_owner = db.scalar(select(User).where(User.email == normalized_email))
        if user is None:
            user = email_owner
            if user is not None and user.google_sub not in (None, subject):
                raise HTTPException(status_code=403, detail="This email is linked to another account.")
        elif email_owner is not None and email_owner.id != user.id:
            raise HTTPException(status_code=403, detail="This email is linked to another account.")
        if user is None:
            user = User(
                id=str(uuid.uuid4()),
                google_sub=subject,
                email=normalized_email,
                name=str(profile.get("name") or "")[:255],
                picture=profile.get("picture") if isinstance(profile.get("picture"), str) else None,
                email_verified=True,
            )
            db.add(user)
        else:
            # Google's authenticated subject and verified email can safely bind methods.
            user.google_sub = subject
            user.email = normalized_email
            user.name = str(profile.get("name") or "")[:255]
            user.picture = profile.get("picture") if isinstance(profile.get("picture"), str) else None
            user.email_verified = True
        db.commit()
        db.refresh(user)
        return UserView(user.id, user.email, user.name, user.picture)


def google_authorization_url(state: str) -> str:
    client_id, _, redirect_uri = google_configuration()
    return GOOGLE_AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
