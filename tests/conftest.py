import os

import pytest

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SESSION_SECRET"] = "test-only-secret-that-is-longer-than-32-characters"
os.environ["APP_BASE_URL"] = "http://testserver"
os.environ["APP_ENV"] = "development"


@pytest.fixture(autouse=True)
def prevent_real_model_calls(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    from app.ingestion.document_store import document_store
    from app.core.database import (
        Base,
        Conversation,
        EmailVerification,
        OAuthState,
        SessionLocal,
        StoredChunk,
        StoredDocument,
        User,
        UserSession,
        engine,
    )

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for model in (
            StoredChunk, StoredDocument, Conversation, EmailVerification, UserSession, OAuthState, User
        ):
            db.query(model).delete()
        db.commit()
    for document in document_store.list_documents():
        document_store.remove(document.document_id)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app import auth
    from app.api.main import app
    from app.core.database import (
        Base,
        Conversation,
        EmailVerification,
        OAuthState,
        SessionLocal,
        StoredChunk,
        StoredDocument,
        User,
        UserSession,
        engine,
    )

    with SessionLocal() as db:
        for model in (
            StoredChunk, StoredDocument, Conversation, EmailVerification, UserSession, OAuthState, User
        ):
            db.query(model).delete()
        db.add(
            User(
                id="test-user",
                google_sub="test-google-subject",
                email="person@example.com",
                name="Test User",
                email_verified=True,
            )
        )
        db.commit()
    # The authenticated test client models a same-origin browser request explicitly.
    test_client = TestClient(app, headers={"Origin": "http://testserver"})
    test_client.cookies.set(auth.SESSION_COOKIE, auth.create_user_session("test-user"))
    yield test_client
    test_client.close()
