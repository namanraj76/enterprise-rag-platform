from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.api.main import app
from app.core.database import SessionLocal, User


def _another_user_client():
    with SessionLocal() as db:
        db.add(
            User(
                id="second-user",
                google_sub="second-google-subject",
                email="second@example.com",
                name="Second User",
                email_verified=True,
            )
        )
        db.commit()
    other = TestClient(app, headers={"Origin": "http://testserver"})
    other.cookies.set(auth.SESSION_COOKIE, auth.create_user_session("second-user"))
    return other


def test_protected_routes_reject_anonymous_requests():
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get("/auth/me").status_code == 401
    assert anonymous.post("/chat", json={"message": "hello"}).status_code == 401
    assert anonymous.get("/documents").status_code == 401
    assert anonymous.post(
        "/documents", files={"file": ("x.txt", b"data", "text/plain")}
    ).status_code == 401
    assert anonymous.delete("/documents/missing").status_code == 401
    assert anonymous.get("/conversations").status_code == 401
    assert anonymous.post("/conversations", json={"title": "private"}).status_code == 401
    assert anonymous.get("/health").status_code == 200
    anonymous.close()


def test_oauth_start_sets_http_only_state_cookie_and_callback_requires_matching_state(
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("APP_BASE_URL", "https://aurelia.example")
    anonymous = TestClient(app, base_url="https://testserver")

    started = anonymous.get("/auth/google", follow_redirects=False)
    assert started.status_code == 302
    query = parse_qs(urlparse(started.headers["location"]).query)
    state = query["state"][0]
    cookie = started.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert query["redirect_uri"] == ["https://aurelia.example/auth/google/callback"]

    exchange_called = False

    def unexpected_exchange(*_args, **_kwargs):
        nonlocal exchange_called
        exchange_called = True

    monkeypatch.setattr(auth, "exchange_google_code", unexpected_exchange)
    rejected = anonymous.get(
        "/auth/callback", params={"code": "code", "state": "attacker-state"}
    )
    assert rejected.status_code == 400
    assert "state" in rejected.json()["detail"].lower()
    assert not exchange_called

    # State is browser-bound and one-use; a valid callback can now consume it.
    monkeypatch.setattr(
        auth,
        "exchange_google_code",
        lambda *_args, **_kwargs: {
            "sub": "google-subject",
            "email": "oauth@example.com",
            "email_verified": True,
            "name": "Invited Person",
        },
    )
    accepted = anonymous.get(
        "/auth/callback", params={"code": "valid-code", "state": state}, follow_redirects=False
    )
    assert accepted.status_code == 303
    session_cookie = accepted.headers["set-cookie"].lower()
    assert auth.SESSION_COOKIE in session_cookie
    assert "httponly" in session_cookie and "secure" in session_cookie
    assert "samesite=lax" in session_cookie

    replay = anonymous.get(
        "/auth/callback", params={"code": "replay", "state": state}, follow_redirects=False
    )
    assert replay.status_code == 400
    anonymous.close()


def test_google_accounts_with_verified_emails_can_self_register():
    user = auth.provision_google_user(
        {"sub": "self-registered-google-user", "email": "intruder@example.com", "email_verified": True}
    )
    assert user.email == "intruder@example.com"


def test_unverified_google_accounts_are_rejected():
    with pytest.raises(HTTPException) as not_verified:
        auth.provision_google_user(
            {"sub": "not-verified", "email": "person@example.com", "email_verified": False}
        )
    assert not_verified.value.status_code == 403


def test_google_email_matching_is_case_and_whitespace_normalized():
    user = auth.provision_google_user(
        {
            "sub": "normalized-email-subject",
            "email": " Person@Example.com ",
            "email_verified": True,
            "name": "Normalized",
        }
    )
    assert user.email == "person@example.com"


def test_state_challenge_is_cryptographically_random_and_single_use():
    state = auth.create_oauth_state()
    other_state = auth.create_oauth_state()
    assert len(state) >= 40
    assert state != other_state
    assert auth.consume_oauth_state(state) is True
    assert auth.consume_oauth_state(state) is False
    assert auth.consume_oauth_state(other_state) is True


def test_cookie_authenticated_mutations_require_same_origin(client):
    rejected_chat = client.post(
        "/chat",
        json={"message": "hello"},
        headers={"Origin": "https://attacker.example"},
    )
    assert rejected_chat.status_code == 403
    assert "CSRF" in rejected_chat.json()["detail"]

    rejected_logout = client.post(
        "/auth/logout",
        headers={"Origin": "https://attacker.example"},
    )
    assert rejected_logout.status_code == 403
    assert client.get("/auth/me").status_code == 200

    rejected_upload = client.post(
        "/documents",
        files={"file": ("note.txt", b"private", "text/plain")},
        headers={"Origin": "null"},
    )
    assert rejected_upload.status_code == 403


def test_cookie_authenticated_mutation_accepts_matching_referer_without_origin(client):
    client.headers.pop("origin")
    response = client.post(
        "/conversations",
        json={"title": "same-origin", "messages": [], "history": []},
        headers={"Referer": "http://testserver/some/page"},
    )
    assert response.status_code == 201

    rejected = client.post(
        "/conversations",
        json={"title": "cross-origin", "messages": [], "history": []},
        headers={"Referer": "https://attacker.example/some/page"},
    )
    assert rejected.status_code == 403


def test_session_is_signed_revocable_and_logout_clears_cookie(client):
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": "person@example.com", "name": "Test User"}
    original = client.cookies.get(auth.SESSION_COOKIE)
    session_id, signature = original.rsplit(".", 1)
    replacement = "0" if signature[-1] != "0" else "1"
    client.cookies.set(auth.SESSION_COOKIE, f"{session_id}.{signature[:-1]}{replacement}")
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, original)
    logged_out = client.post("/auth/logout")
    assert logged_out.status_code == 204
    assert client.get("/auth/me").status_code == 401
    assert auth.SESSION_COOKIE in logged_out.headers["set-cookie"]


def test_documents_and_conversations_are_persisted_and_owner_scoped(client):
    upload = client.post(
        "/documents",
        files={"file": ("private.txt", b"Alpha user's private retrieval phrase.", "text/plain")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["document_id"]
    created = client.post(
        "/conversations",
        json={
            "title": "Private chat",
            "messages": [{"role": "user", "content": "keep this private"}],
            "history": [{"role": "user", "content": "keep this private"}],
        },
    )
    assert created.status_code == 201
    created_json = created.json()
    assert set(created_json) == {"id", "title", "messages", "history", "updatedAt"}
    assert created_json["title"] == "Private chat"
    assert created_json["messages"] == [{"role": "user", "content": "keep this private"}]
    assert created_json["history"] == [{"role": "user", "content": "keep this private"}]
    assert isinstance(created_json["updatedAt"], int)
    conversation_id = created.json()["id"]
    listed = client.get("/conversations").json()
    assert set(listed) == {"conversations"}
    assert listed["conversations"][0] == created_json
    assert client.get(f"/conversations/{conversation_id}").json() == created_json

    other = _another_user_client()
    assert other.get("/documents").json() == {"documents": []}
    assert other.get("/conversations").json() == {"conversations": []}
    assert other.get(f"/conversations/{conversation_id}").status_code == 404
    assert other.put(
        f"/conversations/{conversation_id}", json={"title": "steal"}
    ).status_code == 404
    assert other.delete(f"/conversations/{conversation_id}").status_code == 404
    assert other.delete(f"/documents/{document_id}").status_code == 404

    updated = client.put(
        f"/conversations/{conversation_id}",
        json={
            "title": "Updated",
            "messages": [{"role": "assistant", "content": "stored"}],
            "history": [],
        },
    )
    assert updated.status_code == 200
    assert set(updated.json()) == {"id", "title", "messages", "history", "updatedAt"}
    assert updated.json()["id"] == conversation_id
    assert updated.json()["title"] == "Updated"
    assert updated.json()["messages"] == [{"role": "assistant", "content": "stored"}]
    assert updated.json()["history"] == []
    assert client.delete(f"/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/conversations/{conversation_id}").status_code == 404
    other.close()


def test_chat_retrieval_only_uses_the_current_users_documents(client, monkeypatch):
    upload = client.post(
        "/documents",
        files={
            "file": (
                "private.txt",
                b"Quasar access phrase is exclusively in the first account's document.",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 201
    observed = {}

    def generate(self, message, history=None):
        observed["history"] = history
        return "No personal source used."

    import app.generation.conversational_generator as generator_module

    monkeypatch.setattr(generator_module.ConversationalGenerator, "generate", generate)
    other = _another_user_client()
    response = other.post("/chat", json={"message": "What is the Quasar access phrase?"})
    assert response.status_code == 200
    assert response.json()["citations"] == []
    assert response.json()["answer"] == "No personal source used."

    owned_chat = client.post("/chat", json={"message": "private conversation"})
    conversation_id = owned_chat.json()["conversation_id"]
    assert other.get(f"/conversations/{conversation_id}").status_code == 404
    assert other.post(
        "/chat",
        json={"message": "hello", "conversation_id": conversation_id},
    ).status_code == 404
    other.close()


def test_google_login_fails_closed_without_oauth_or_session_configuration(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "short")
    anonymous = TestClient(app)
    assert anonymous.get("/auth/google").status_code == 503
    assert anonymous.get("/auth/me").status_code == 401
    anonymous.close()
