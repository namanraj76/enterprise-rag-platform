import pytest
from fastapi import HTTPException

from app import auth
from app.core.database import EmailVerification, SessionLocal, User


def test_development_app_base_url_matches_loopback_browser_origin(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    assert auth._app_base_url() == "http://127.0.0.1:8000"


def test_frontend_auth_routes_are_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/auth/register",
        "/auth/verify-email",
        "/auth/verification/resend",
        "/auth/login",
        "/auth/session",
        "/auth/logout",
        "/auth/google",
        "/auth/google/login",
        "/auth/google/callback",
    }.issubset(paths)


def test_verified_google_email_links_and_verifies_existing_password_account(client, monkeypatch):
    monkeypatch.setattr(auth, "send_verification_email", lambda *_: None)
    registered = client.post(
        "/auth/register",
        json={
            "email": "claim-target@example.com",
            "password": "attacker-known-password",
        },
    )
    assert registered.status_code == 201
    google_user = auth.provision_google_user(
        {
            "sub": "verified-google-subject",
            "email": "claim-target@example.com",
            "email_verified": True,
            "name": "Verified Google User",
        }
    )
    assert google_user.id == registered.json()["user_id"]
    with SessionLocal() as db:
        user = db.get(User, registered.json()["user_id"])
        assert user.email_verified is True
        assert user.google_sub == "verified-google-subject"
        assert user.password_hash is not None


def test_registration_verification_and_password_login_persist(client, monkeypatch):
    sent = {}

    def capture_verification(email, token):
        sent.update(email=email, token=token)

    monkeypatch.setattr(auth, "send_verification_email", capture_verification)
    registered = client.post(
        "/auth/register",
        json={
            "email": " New.User@Example.com ",
            "password": "correct horse battery staple",
            "name": "New User",
        },
    )
    assert registered.status_code == 201
    user_id = registered.json()["user_id"]
    assert sent["email"] == "new.user@example.com"
    assert client.post(
        "/auth/login",
        json={"email": sent["email"], "password": "correct horse battery staple"},
    ).status_code == 403

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.email_verified is False
        assert user.password_hash.startswith("scrypt$")
        assert user.password_hash != "correct horse battery staple"
        assert db.query(EmailVerification).filter_by(user_id=user_id).count() == 1

    verified = client.post("/auth/verify-email", json={"token": sent["token"]})
    assert verified.status_code == 200
    assert client.post("/auth/verify-email", json={"token": sent["token"]}).status_code == 400

    with SessionLocal() as db:
        assert db.get(User, user_id).email_verified is True
        assert db.query(EmailVerification).filter_by(user_id=user_id).count() == 0

    bad_password = client.post(
        "/auth/login", json={"email": sent["email"], "password": "incorrect password"}
    )
    assert bad_password.status_code == 401
    logged_in = client.post(
        "/auth/login",
        json={"email": sent["email"], "password": "correct horse battery staple"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user"] == {
        "id": user_id,
        "email": sent["email"],
        "name": "New User",
    }
    assert "httponly" in logged_in.headers["set-cookie"].lower()
    assert client.get("/auth/session").json()["user"]["email"] == sent["email"]


def test_registration_validates_email_and_password_and_prevents_duplicates(client, monkeypatch):
    monkeypatch.setattr(auth, "send_verification_email", lambda *_: None)
    invalid = client.post(
        "/auth/register", json={"email": "not-an-email", "password": "long enough password"}
    )
    assert invalid.status_code == 422
    weak_password = client.post(
        "/auth/register", json={"email": "new@example.com", "password": "short"}
    )
    assert weak_password.status_code == 422
    payload = {"email": "new@example.com", "password": "long enough password"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409


def test_verification_requires_same_origin_and_unknown_resend_does_not_disclose(client):
    rejected = client.post(
        "/auth/verify-email",
        json={"token": "random"},
        headers={"Origin": "https://attacker.example"},
    )
    assert rejected.status_code == 403
    unknown = client.post("/auth/verification/resend", json={"email": "unknown@example.com"})
    assert unknown.status_code == 202
    assert "If the account needs verification" in unknown.json()["message"]


def test_development_email_fallback_logs_token_but_does_not_return_it(client, monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    response = client.post(
        "/auth/register",
        json={"email": "dev@example.com", "password": "long enough password"},
    )
    assert response.status_code == 201
    assert "token=" in caplog.text
    assert "token" not in response.json()


def test_production_auth_requires_https_and_email_delivery_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_BASE_URL", "http://aurelia.example")
    monkeypatch.setenv("SESSION_SECRET", "production-secret-long-enough-to-pass-32")
    with pytest.raises(HTTPException) as error:
        auth._session_secret()
    assert error.value.status_code == 503

    monkeypatch.setenv("APP_BASE_URL", "https://aurelia.example")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    with pytest.raises(HTTPException) as email_error:
        auth.register_email_user("production@example.com", "long enough password")
    assert email_error.value.status_code == 503
