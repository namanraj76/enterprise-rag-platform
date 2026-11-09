from __future__ import annotations

from pathlib import Path
import secrets
import time
import uuid
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app import auth
from app.auth import UserView, current_user
from app.core.database import Conversation, SessionLocal, User
from app.generation.conversational_generator import (
    ChatModelError,
    ConversationalGenerator,
    get_model_status,
)
from app.ingestion.document_store import (
    MAX_UPLOAD_BYTES,
    DocumentIngestionError,
    DocumentInfo,
    persistent_document_store,
)
from app.utils.logging import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "app" / "static"

app = FastAPI(title="Aurelia")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

MAX_MULTIPART_OVERHEAD = 64 * 1024


class UploadSizeLimitMiddleware:
    """Bound multipart request bodies before Starlette spools upload data."""

    def __init__(self, app):
        self.application = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in {"/upload", "/documents"}
        ):
            await self.application(scope, receive, send)
            return

        body_limit = MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD
        content_length = next(
            (value for name, value in scope.get("headers", []) if name.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                too_large = int(content_length) > body_limit
            except ValueError:
                too_large = True
            if too_large:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "Upload request exceeds the 10 MiB file limit."},
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > body_limit:
                    raise HTTPException(
                        status_code=413,
                        detail="Upload request exceeds the 10 MiB file limit.",
                    )
            return message

        await self.application(scope, limited_receive, send)


app.add_middleware(UploadSizeLimitMiddleware)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ConversationMessage] = Field(default_factory=list, max_length=20)
    conversation_id: str | None = None


class SourceCitation(BaseModel):
    filename: str
    page: int | None = None
    quote: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[SourceCitation] = Field(default_factory=list)
    conversation_id: str | None = None


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    chunks: int


class ListedDocument(BaseModel):
    id: str
    filename: str


class DocumentListResponse(BaseModel):
    documents: list[ListedDocument]


class ConversationWrite(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    messages: list[dict[str, object]] = Field(default_factory=list)
    history: list[dict[str, object]] = Field(default_factory=list)


def _normalize_email_address(value: str) -> str:
    normalized = value.strip().casefold()
    local, separator, domain = normalized.rpartition("@")
    if (
        normalized.count("@") != 1
        or not separator
        or not local
        or not domain
        or "." not in domain
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("Enter a valid email address.")
    return normalized


class EmailRegistration(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=1024)
    name: str = Field(default="", max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email_address(value)


class EmailLogin(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email_address(value)


class VerificationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class ResendVerificationRequest(BaseModel):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email_address(value)


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.create_user_session(user_id),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        secure=auth._secure_cookies(),
        samesite="lax",
        path="/",
    )


def _conversation_payload(conversation: Conversation) -> dict[str, object]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "messages": conversation.messages,
        "history": conversation.history,
        "updatedAt": conversation.updated_at,
    }


def _document_response(info: DocumentInfo) -> DocumentResponse:
    return DocumentResponse(
        document_id=info.document_id,
        filename=info.filename,
        chunks=info.chunks,
    )


@app.get("/health")
def health() -> dict[str, str]:
    model_status = get_model_status()
    return {
        "status": "ok",
        "service": "aurelia",
        "model_status": model_status["status"],
        "model": model_status["model"],
    }


@app.get("/auth/google")
@app.get("/auth/google/login")
def google_login() -> RedirectResponse:
    # Fail closed if either the signing secret or Google OAuth configuration is absent.
    auth._session_secret()
    state = auth.create_oauth_state()
    response = RedirectResponse(auth.google_authorization_url(state), status_code=302)
    response.set_cookie(
        auth.OAUTH_STATE_COOKIE,
        state,
        max_age=auth.OAUTH_STATE_MAX_AGE,
        httponly=True,
        secure=auth._secure_cookies(),
        samesite="lax",
        path="/auth",
    )
    return response


@app.get("/auth/callback", include_in_schema=False)
@app.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    response = RedirectResponse("/", status_code=303)
    state_cookie = request.cookies.get(auth.OAUTH_STATE_COOKIE)
    if error or not code or not state or not state_cookie:
        raise HTTPException(status_code=400, detail="Google sign-in was cancelled or incomplete.")
    if not secrets.compare_digest(state, state_cookie) or not auth.consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="OAuth state validation failed.")
    _, _, redirect_uri = auth.google_configuration()
    profile = auth.exchange_google_code(code, redirect_uri)
    user = auth.provision_google_user(profile)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.create_user_session(user.id),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        secure=auth._secure_cookies(),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        auth.OAUTH_STATE_COOKIE,
        httponly=True,
        secure=auth._secure_cookies(),
        samesite="lax",
        path="/auth",
    )
    return response


@app.get("/auth/me")
def auth_me(user: UserView = Depends(current_user)) -> dict[str, str]:
    return {"email": user.email, "name": user.name}


@app.get("/auth/session")
def auth_session(user: UserView = Depends(current_user)) -> dict[str, object]:
    return {
        "authenticated": True,
        "user": {"id": user.id, "email": user.email, "name": user.name},
    }


@app.post("/auth/register", status_code=201)
def auth_register(
    payload: EmailRegistration,
    _origin: None = Depends(auth.require_same_origin),
) -> dict[str, str]:
    auth._session_secret()
    user_id = auth.register_email_user(payload.email, payload.password, payload.name)
    message = (
        "Account created. This local app is not configured to send email; "
        "the verification token was written to the Aurelia server log."
        if not auth._setting("SMTP_HOST")
        else "Account created. Check your email for a verification token."
    )
    return {
        "message": message,
        "user_id": user_id,
    }


@app.post("/auth/verify-email")
def auth_verify_email(
    payload: VerificationRequest,
    _origin: None = Depends(auth.require_same_origin),
) -> dict[str, str]:
    if not auth.verify_email_token(payload.token):
        raise HTTPException(status_code=400, detail="Verification token is invalid or expired.")
    return {"message": "Email verified. You can now sign in."}


@app.post("/auth/verification/resend", status_code=202)
def auth_resend_verification(
    payload: ResendVerificationRequest,
    _origin: None = Depends(auth.require_same_origin),
) -> dict[str, str]:
    email = payload.email
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                User.email == email,
                User.password_hash.is_not(None),
                User.email_verified.is_(False),
            )
        )
        user_id = user.id if user is not None else None
    if user_id is not None:
        token = auth.create_email_verification(user_id)
        try:
            auth.send_verification_email(email, token)
        except Exception as exc:
            logger.error("Verification email delivery failed for %s: %s", email, exc)
            raise HTTPException(
                status_code=503, detail="Email delivery is temporarily unavailable."
            ) from exc
    # Avoid disclosing whether an address has an account.
    message = (
        "If the account needs verification, its token is in the local Aurelia server log."
        if not auth._setting("SMTP_HOST") and auth._setting("APP_ENV").lower() != "production"
        else "If the account needs verification, an email will be sent."
    )
    return {"message": message}


@app.post("/auth/login")
def auth_login(
    payload: EmailLogin,
    _origin: None = Depends(auth.require_same_origin),
) -> Response:
    auth._session_secret()
    user = auth.authenticate_email_user(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    response = JSONResponse(
        {
            "authenticated": True,
            "user": {"id": user.id, "email": user.email, "name": user.name},
        }
    )
    _set_session_cookie(response, user.id)
    return response


@app.post("/auth/logout", status_code=204, response_class=Response)
def auth_logout(request: Request, _user: UserView = Depends(current_user)) -> Response:
    auth.invalidate_session(request.cookies.get(auth.SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(
        auth.SESSION_COOKIE,
        httponly=True,
        secure=auth._secure_cookies(),
        samesite="lax",
        path="/",
    )
    return response


@app.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
def chat(payload: ChatRequest, user: UserView = Depends(current_user)) -> ChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    history = [turn.model_dump() for turn in payload.history]
    evidence = persistent_document_store.search(user.id, payload.message.strip())
    conversation = None
    if payload.conversation_id:
        with SessionLocal() as db:
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.id == payload.conversation_id,
                    Conversation.user_id == user.id,
                )
            )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        if evidence:
            answer = ConversationalGenerator().generate(
                payload.message.strip(),
                history,
                evidence=[
                    {"citation": item.citation, "text": item.text}
                    for item in evidence
                ],
            )
            # Include deterministic citations so users can trace the retrieved evidence
            # even if a local model omits the requested citation markup.
            citations = list(dict.fromkeys(item.citation for item in evidence))
            answer = f"{answer}\n\nSources: " + "; ".join(f"[{item}]" for item in citations)
        else:
            answer = ConversationalGenerator().generate(payload.message.strip(), history)
    except ChatModelError as exc:
        logger.error("chat model request failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    now = int(time.time() * 1000)
    with SessionLocal() as db:
        if payload.conversation_id:
            stored = db.scalar(
                select(Conversation).where(
                    Conversation.id == payload.conversation_id,
                    Conversation.user_id == user.id,
                )
            )
            if stored is None:
                # It may have been removed while the model was generating.
                raise HTTPException(status_code=404, detail="Conversation not found")
        else:
            stored = Conversation(
                id=str(uuid.uuid4()),
                user_id=user.id,
                title=payload.message.strip()[:500],
                messages=[],
                history=[],
                updated_at=now,
            )
            db.add(stored)
        stored.messages = list(stored.messages or []) + [
            {"role": "user", "content": payload.message.strip(), "time": now},
            {"role": "assistant", "content": answer, "time": now},
        ]
        stored.history = history[-18:] + [
            {"role": "user", "content": payload.message.strip()},
            {"role": "assistant", "content": answer},
        ]
        stored.updated_at = now
        conversation_id = stored.id
        db.commit()

    citations: list[SourceCitation] = []
    if evidence:
        unique_sources: dict[tuple[str, int | None], SourceCitation] = {}
        for item in evidence:
            unique_sources.setdefault(
                (item.filename, item.page),
                SourceCitation(filename=item.filename, page=item.page, quote=item.text),
            )
        citations = list(unique_sources.values())
    return ChatResponse(answer=answer, citations=citations, conversation_id=conversation_id)


@app.post("/upload", response_model=DocumentResponse, status_code=201)
@app.post("/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...), user: UserView = Depends(current_user)
) -> DocumentResponse:
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    try:
        info = persistent_document_store.add(user.id, file.filename or "", payload)
    except DocumentIngestionError as exc:
        message = str(exc)
        status_code = 413 if "10 MiB upload limit" in message else (
            415 if message.startswith("Unsupported file type") else 422
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    return _document_response(info)


@app.get("/documents", response_model=DocumentListResponse)
def list_documents(user: UserView = Depends(current_user)) -> DocumentListResponse:
    return DocumentListResponse(
        documents=[
            ListedDocument(id=info.document_id, filename=info.filename)
            for info in persistent_document_store.list_documents(user.id)
        ]
    )


@app.delete("/documents/{document_id}", status_code=204, response_class=Response)
def delete_document(document_id: str, user: UserView = Depends(current_user)) -> Response:
    if not persistent_document_store.remove(user.id, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=204)


@app.get("/conversations")
def list_conversations(user: UserView = Depends(current_user)) -> dict[str, list[dict[str, object]]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        ).all()
        return {"conversations": [_conversation_payload(row) for row in rows]}


@app.post("/conversations", status_code=201)
def create_conversation(
    payload: ConversationWrite, user: UserView = Depends(current_user)
) -> dict[str, object]:
    conversation = Conversation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=payload.title.strip(),
        messages=payload.messages,
        history=payload.history,
        updated_at=int(time.time() * 1000),
    )
    if not conversation.title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be empty.")
    with SessionLocal() as db:
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return _conversation_payload(conversation)


@app.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str, user: UserView = Depends(current_user)
) -> dict[str, object]:
    with SessionLocal() as db:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return _conversation_payload(conversation)


@app.put("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    payload: ConversationWrite,
    user: UserView = Depends(current_user),
) -> dict[str, object]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be empty.")
    with SessionLocal() as db:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.title = title
        conversation.messages = payload.messages
        conversation.history = payload.history
        conversation.updated_at = int(time.time() * 1000)
        db.commit()
        db.refresh(conversation)
        return _conversation_payload(conversation)


@app.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
def delete_conversation(
    conversation_id: str, user: UserView = Depends(current_user)
) -> Response:
    with SessionLocal() as db:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        db.delete(conversation)
        db.commit()
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def ui_index() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index)
