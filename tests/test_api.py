import app.generation.conversational_generator as generator_module
from app.ingestion.document_store import document_store

def test_health_endpoint(client, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "llama3.2:3b")
    monkeypatch.setattr(generator_module, "get_model_status", lambda: {
        "status": "model_missing",
        "model": "llama3.2:3b",
    })
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "aurelia",
        "model_status": "model_missing",
        "model": "llama3.2:3b",
    }


def test_chat_endpoint_returns_empty_citations_without_relevant_documents(client, monkeypatch):
    observed = {}

    def generate(self, message, history=None):
        assert isinstance(self, generator_module.ConversationalGenerator)
        observed["message"] = message
        observed["history"] = history
        return "Let's talk it through."

    monkeypatch.setattr(generator_module.ConversationalGenerator, "generate", generate)
    response = client.post(
        "/chat",
        json={
            "message": "Can you help?",
            "history": [{"role": "assistant", "content": "Of course."}],
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Let's talk it through."
    assert response.json()["citations"] == []
    assert response.json()["conversation_id"]
    assert observed["message"] == "Can you help?"
    assert observed["history"][0]["content"] == "Of course."


def test_chat_rejects_empty_messages(client):
    response = client.post("/chat", json={"message": "  "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Message cannot be empty"


def test_chat_persists_new_and_followup_turns_on_the_server(client, monkeypatch):
    monkeypatch.setattr(
        generator_module.ConversationalGenerator,
        "generate",
        lambda self, message, history=None: f"Answer: {message}",
    )
    first = client.post("/chat", json={"message": "First turn"})
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    stored = client.get(f"/conversations/{conversation_id}")
    assert stored.status_code == 200
    assert stored.json()["title"] == "First turn"
    assert [message["role"] for message in stored.json()["messages"]] == [
        "user", "assistant"
    ]

    second = client.post(
        "/chat",
        json={
            "message": "Second turn",
            "conversation_id": conversation_id,
            "history": [
                {"role": "user", "content": "First turn"},
                {"role": "assistant", "content": "Answer: First turn"},
            ],
        },
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    stored = client.get(f"/conversations/{conversation_id}").json()
    assert [message["content"] for message in stored["messages"]] == [
        "First turn",
        "Answer: First turn",
        "Second turn",
        "Answer: Second turn",
    ]
    assert [turn["content"] for turn in stored["history"]][-2:] == [
        "Second turn",
        "Answer: Second turn",
    ]


def test_chat_surfaces_local_model_failures(client, monkeypatch):
    def generate(self, message, history=None):
        assert isinstance(self, generator_module.ConversationalGenerator)
        assert message == "Hello"
        assert history == []
        raise generator_module.ChatModelError("Model provider is unavailable. Try again.")

    monkeypatch.setattr(generator_module.ConversationalGenerator, "generate", generate)
    response = client.post("/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Model provider is unavailable. Try again."


def test_upload_chat_cites_relevant_document(client, monkeypatch):
    upload = client.post(
        "/upload",
        files={"file": ("security.txt", b"Rotate access keys every 90 days.", "text/plain")},
    )
    assert upload.status_code == 201
    assert upload.json()["filename"] == "security.txt"
    assert upload.json()["chunks"] == 1
    listed = client.get("/documents").json()["documents"][0]
    assert listed == {"id": upload.json()["document_id"], "filename": "security.txt"}

    observed = {}

    def generate(self, message, history=None, evidence=None):
        observed["message"] = message
        observed["evidence"] = evidence
        return "Rotate keys regularly."

    monkeypatch.setattr(generator_module.ConversationalGenerator, "generate", generate)
    response = client.post("/chat", json={"message": "How often rotate access keys?"})

    assert response.status_code == 200
    assert response.json()["answer"] == (
        "Rotate keys regularly.\n\nSources: [security.txt, document, chunk 1]"
    )
    assert response.json()["citations"] == [
        {
            "filename": "security.txt",
            "quote": "Rotate access keys every 90 days.",
        }
    ]
    assert observed["message"] == "How often rotate access keys?"
    assert observed["evidence"][0]["citation"] == "security.txt, document, chunk 1"
    assert "every 90 days" in observed["evidence"][0]["text"]
    assert client.delete(f"/documents/{upload.json()['document_id']}").status_code == 204
    assert client.get("/documents").json() == {"documents": []}
    assert client.delete(f"/documents/{upload.json()['document_id']}").status_code == 404


def test_documents_route_accepts_the_existing_ui_upload_contract(client):
    upload = client.post(
        "/documents",
        files={"file": ("notes.txt", b"Local note text.", "text/plain")},
    )

    assert upload.status_code == 201
    assert upload.json()["filename"] == "notes.txt"
    assert client.get("/documents").json() == {
        "documents": [{"id": upload.json()["document_id"], "filename": "notes.txt"}]
    }


def test_unrelated_question_keeps_ordinary_chat(client, monkeypatch):
    document_store.add("security.txt", b"Rotate access keys every 90 days.")
    observed = {}

    def generate(self, message, history=None):
        observed["message"] = message
        return "A general answer."

    monkeypatch.setattr(generator_module.ConversationalGenerator, "generate", generate)
    response = client.post("/chat", json={"message": "What is the capital of France?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "A general answer."
    assert response.json()["citations"] == []
    assert response.json()["conversation_id"]
    assert observed["message"] == "What is the capital of France?"


def test_upload_rejects_invalid_and_oversized_files(client):
    unsupported = client.post(
        "/upload",
        files={"file": ("script.exe", b"not a document", "application/octet-stream")},
    )
    assert unsupported.status_code == 415
    assert "PDF, DOCX, or TXT" in unsupported.json()["detail"]

    oversized = client.post(
        "/upload",
        files={"file": ("large.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")},
    )
    assert oversized.status_code == 413
    assert "10 MiB" in oversized.json()["detail"]


def test_upload_bounds_streamed_request_body_without_content_length(client):
    body_size = 10 * 1024 * 1024 + 64 * 1024 + 1
    response = client.post(
        "/upload",
        content=(b"x" * (64 * 1024) for _ in range(body_size // (64 * 1024) + 1)),
        headers={"Content-Type": "multipart/form-data; boundary=bounded-upload"},
    )

    assert response.status_code == 413


def test_removed_legacy_document_endpoints_remain_unavailable(client):
    assert client.post("/query", json={"question": "hello"}).status_code == 404
    assert client.post("/ingest_url", json={"url": "https://example.com"}).status_code == 404
    assert client.post("/reindex").status_code == 404
    assert client.get("/doc/example.txt").status_code == 404


def test_homepage_renders_aurelia_chat_and_document_library(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "How can I help today?" in response.text
    assert "Aurelia" in response.text
    assert 'aria-label="Knowledge library"' in response.text
    assert 'id="documentInput"' in response.text
    assert 'id="dictateButton"' in response.text
    assert "Choose a text file" not in response.text
    assert "Your sources" not in response.text
    assert "AI foundations" in response.text
    assert "Machine learning" in response.text
    assert "LLMs and RAG" in response.text
    assert "Design an AI system" in response.text
    assert 'aria-label="AI topics"' in response.text
    assert 'class="topic-button"' in response.text
    assert 'aria-label="Recent chats"' in response.text
    assert 'id="conversationList"' in response.text
    assert 'aria-label="Knowledge library"' in response.text
    assert 'id="documentInput"' in response.text
    assert 'id="dictateButton"' in response.text
