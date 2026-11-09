# Aurelia

A chat application with private, per-account document retrieval and persistent conversations. PDF, DOCX, and UTF-8 TXT documents are parsed and indexed by Aurelia; relevant excerpts are passed to the configured Ollama model with citations. No external vector database or OpenAI API key is required.

## Local setup and run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Local development defaults to SQLite, HTTP cookies, and a development-only session signing key.
Email verification tokens are printed to the application log when SMTP is not configured; they
are never returned in the registration API response. For better local secret hygiene, you may set
`SESSION_SECRET` to a random value:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Put the output in `.env`; do not commit `.env` or share the value. Email/password registration is
available locally without SMTP. Google sign-in requires the OAuth client variables described below.

Run the schema migration and start the API:

```bash
alembic upgrade head
python run.py
```

Run `python run.py`, open <http://127.0.0.1:8000>, and create an account. In local development,
verification tokens are written to the application log; paste the token into the verification form.
Alternatively, use Google sign-in after configuring OAuth. Local HTTP cookies are not marked
`Secure`; they are `HttpOnly`,
`SameSite=Lax`, cryptographically signed, and backed by revocable database sessions. Browser
authentication POSTs must send a same-origin `Origin` header (or same-origin `Referer`). For
model-backed chat, install [Ollama](https://ollama.com/download), run `ollama pull gemma3:4b`,
and start `ollama serve`. Gemma 3 4B follows language and tutoring instructions more reliably
than the smaller 1B model, but uses more memory and may respond more slowly. By default,
`.env.example` points to local Ollama at
`http://127.0.0.1:11434/v1`. Configure `OLLAMA_BASE_URL` and `OLLAMA_MODEL` to use a different
Ollama-compatible OpenAI API endpoint. If that endpoint requires bearer authentication, set
`OLLAMA_API_KEY`; omit it for a server that does not require credentials.

The browser interface includes dictation where supported, saved chat navigation, document uploads, citations, and copy/feedback/regenerate/speech controls. The tutor is prompted to explain AI concepts and system design progressively, uses examples on request, and replies in the language used (including Hindi and Hinglish). If no private document excerpts are relevant, chat falls back to ordinary model conversation. Documents up to 10 MiB are accepted in PDF, DOCX, or UTF-8 TXT format; text PDFs are searchable, but scanned/image-only PDFs may need OCR outside this project.

## Google OAuth setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create/select a project and configure the OAuth consent screen. Choose the audience appropriate for your Google account type; publish it or add test users as required by Google's testing mode.
2. Create an OAuth Client ID with application type **Web application**.
3. For local development at `http://127.0.0.1:8000`, add that exact origin as an Authorized JavaScript origin and `http://127.0.0.1:8000/auth/google/callback` as an Authorized redirect URI. If you instead open the app at `http://localhost:8000`, set `APP_BASE_URL` to that exact URL and register the matching localhost origin and callback. For Render, also add the exact deployed `https://<service-name>.onrender.com` origin and `https://<service-name>.onrender.com/auth/google/callback` redirect URI.
4. Save the client ID and secret in local `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Never put credentials in source control.
5. Google sign-in is public self-registration; Google must return an authenticated subject and a verified email. No invite allowlist is used.

The callback validates a cryptographically random, one-time, expiring OAuth `state` value against both a server-side database record and an `HttpOnly` browser cookie. It obtains the profile from Google's authenticated OpenID Connect user-info endpoint; it requires Google's `email_verified` claim and does not trust an email or identity supplied by the browser. Every cookie-authenticated state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`) also requires an `Origin` matching the configured `APP_BASE_URL`, or—when `Origin` is absent—a matching `Referer`; missing, malformed, or cross-origin values are rejected.

## Render deployment

`render.yaml` defines a Python web service and a private Render PostgreSQL database. Create a Blueprint from this repository in Render and deploy it. The blueprint uses Render's **free** plans to avoid assuming a paid plan; be aware the free PostgreSQL instance is temporary and may expire after Render's free retention period. For data that must be retained, choose a persistent PostgreSQL plan before inviting users and maintain database backups.

In the Render service's Environment settings, set the exact assigned HTTPS service URL as
`APP_BASE_URL` (no trailing slash), and provide `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`SMTP_HOST`, and `SMTP_FROM`. Configure `SMTP_USERNAME`/`SMTP_PASSWORD` if the relay requires
authentication; the default is STARTTLS on port 587. Secrets are not provided by this repository:
create the Google OAuth credentials and SMTP mailbox/relay credentials yourself. `SESSION_SECRET`
is generated by the blueprint; `DATABASE_URL` is connected to the private PostgreSQL database.
Configure `OLLAMA_BASE_URL` to the already reachable Ollama server's OpenAI-compatible base URL,
including `/v1` (for example, `https://ollama.example.net/v1`). Do not use `localhost` or
`127.0.0.1` for this Render setting: that would refer to the web service container, not your
separate model server. Set `OLLAMA_API_KEY` only if the endpoint requires a bearer token; the
credential is sent to the model endpoint for both chat requests and the health/status probe. An
API key requires an HTTPS model URL. `OLLAMA_MODEL` defaults to `llama3.2:1b`; change it to a
model available on your Ollama server.
The start command applies `alembic upgrade head` and then starts the documented entry point,
`python run.py`, using Render's assigned port. Add the deployed Google origin and callback URL to
the OAuth client before testing login. `APP_ENV=production` is configured by the Blueprint;
production authentication fails closed unless `SESSION_SECRET` is at least 32 characters and
`APP_BASE_URL` is HTTPS. Email/password registration also fails closed until SMTP delivery is
configured.

The Blueprint uses Render's free PostgreSQL plan to avoid silently opting into a billable resource.
Free Render databases are temporary and expire; upgrade to a persistent PostgreSQL plan and arrange
backups **before storing data for real users**. The free web service may also sleep. The PostgreSQL
database persists account, verification, session, conversation, document, and chunk records; no
uploaded original files are retained.

Chat uses the configured Ollama-compatible endpoint; the Render Blueprint requires an explicit
`OLLAMA_BASE_URL` and has no loopback default. Ensure the URL is reachable from Render and exposes
Ollama's OpenAI-compatible `/v1/chat/completions` interface. `/health` also probes the Ollama
`/api/tags` endpoint to report model status.

## Configuration

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development` locally (default); set to `production` for hosted deployment security checks. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth web client credentials; required only for Google sign-in. |
| `SESSION_SECRET` | Production: at least 32 random characters, generated/stored as a secret; signs opaque session IDs. Sessions are stored and revocable in the database. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` | Required for production email verification. STARTTLS is enabled by default; use `SMTP_USE_SSL=true` for implicit TLS. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Optional SMTP authentication credentials. |
| `SMTP_STARTTLS` / `SMTP_USE_SSL` | TLS mode settings; do not disable transport encryption in production. |
| `DATABASE_URL` | SQLAlchemy URL; local default is persistent `sqlite:///data/aurelia.db`, Render uses private PostgreSQL. |
| `APP_BASE_URL` | Public base URL used for OAuth callbacks, same-origin CSRF checks, and production secure cookies. Local default: `http://127.0.0.1:8000`. |
| `OLLAMA_BASE_URL` | Ollama-compatible OpenAI API base URL. Local default: `http://127.0.0.1:11434/v1`; set an externally reachable HTTPS URL in Render. |
| `OLLAMA_API_KEY` | Optional bearer credential for a protected endpoint; HTTPS is required when set. |
| `OLLAMA_MODEL` | Model name available from the configured Ollama server. |
| `HOST` / `PORT` | Bind address and port; Render supplies `PORT`. |

## Authentication API

All request/response bodies are JSON except the Google redirects/callback. Authentication is
cookie-based. The `aurelia_session` cookie is signed, `HttpOnly`, `SameSite=Lax`, and `Secure` when
`APP_BASE_URL` is HTTPS; its opaque random identifier is stored as a hash in the database. Browser
POST requests must send `Origin` matching `APP_BASE_URL` (or a matching `Referer`); a failed check
returns `403`.

- `POST /auth/register` accepts `{"email":"...","password":"...","name":"..."}` (`name` optional;
  password 12–1024 characters). Returns `201` with a generic message and `user_id`. Email is
  normalized; passwords are hashed with stdlib scrypt. A verification token expires after 24 hours.
- `POST /auth/verify-email` accepts `{"token":"..."}`. Returns `200` after one-time token
  consumption, `400` for invalid, expired, or already-used tokens.
- `POST /auth/verification/resend` accepts `{"email":"..."}` and returns `202` without disclosing
  whether an account exists.
- `POST /auth/login` accepts `{"email":"...","password":"..."}`. Returns `200` with
  `{"authenticated":true,"user":{"id","email","name"}}` and sets the session cookie; invalid
  credentials return `401`, and a correct password for an unverified account returns `403`.
- `GET /auth/me` returns `{"email":"...","name":"..."}` or `401`. `GET /auth/session` also returns
  `{"authenticated":true,"user":{"id":"...","email":"...","name":"..."}}`.
- `POST /auth/logout` revokes the database session and clears the cookie (`204`).
- `GET /auth/google/login` redirects to Google; `GET /auth/google/callback` validates a one-time
  OAuth state and Google's verified identity, then sets the same session cookie. Google sign-in
  self-registers and can link to an existing account with the same Google-verified email,
  including an account whose email/password verification is still pending. `/auth/google` and
  `/auth/callback` remain aliases for compatibility.

Email/password verification is printed to the development application log only when SMTP is
unconfigured locally. Production never returns the raw token through an API response and refuses
to register unless `SMTP_HOST` and `SMTP_FROM` are set. Google and SMTP credentials were not
available during implementation; configure them in Render's secret environment settings before
enabling those sign-in/delivery paths.

## Conversation and chat API

- `GET /conversations` returns `{"conversations":[conversation,...]}`. `POST /conversations`
  accepts `{"title":"...","messages":[],"history":[]}` and returns `201` with a conversation.
- `GET /conversations/{id}` reads one conversation; `PUT /conversations/{id}` replaces its
  `title`, `messages`, and `history`; `DELETE /conversations/{id}` returns `204`.
- A conversation is `{"id":"UUID","title":"...","messages":[...],"history":[...],"updatedAt":<unix-ms>}`.
  Messages contain `role` and `content`, with optional UI metadata such as `time`, `citations`, and
  `feedback`. History turns contain `role` and `content`.
- `POST /chat` accepts `{"message":"...","history":[{"role":"user|assistant","content":"..."}],"conversation_id":"UUID"}`; `history` and `conversation_id` are optional. It returns `{"answer":"...","citations":[...],"conversation_id":"UUID"}`. Without an ID, the server creates and persists a conversation titled from the first message. Send its returned ID on later turns to append them. An unknown or unowned ID returns `404`. Chat messages and history are saved under the authenticated user.

The shipped UI loads each account's list from `GET /conversations`, persists conversation updates
through the owner-scoped conversation routes, and sends `conversation_id` with every `/chat` turn.
Older conversation history from earlier versions may remain in this browser's local storage, but it
is neither displayed nor imported into an account; this prevents one person using a shared browser
from seeing another account's legacy chats. The old history is left untouched.

## Documents API

- `POST /documents` (also `/upload`) accepts a multipart `file` in PDF, DOCX, or UTF-8 TXT format; `GET /documents` lists only the current user's documents; `DELETE /documents/{document_id}` removes an owned document. Uploads are limited to 10 MiB.
- `GET /health` reports app/model status and is public for hosting health checks.

Users, email-verification state, extracted chunks, conversations, OAuth states, and revocable
sessions persist in the configured database. Uploaded originals are not retained; only extracted
indexed text is stored. Every chat/document route requires authentication, and all reads, writes,
retrievals, updates, and deletes use the current user's database ID. Foreign resource IDs return
`404`. Scanned/image-only PDFs may not produce searchable text because OCR is not included.

## Tests

```bash
pytest -q
```

Tests use an isolated in-memory SQLite database and mock model/OAuth network activity.
