from types import SimpleNamespace

import httpx
import pytest

import app.generation.conversational_generator as generator_module
from app.generation.conversational_generator import ChatModelError, ConversationalGenerator


def test_local_model_receives_conversation_history(monkeypatch):
    observed = {}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Hi! How has your day been?"))]
    )

    def create_client(*, base_url, api_key, timeout):
        observed["client"] = {"base_url": base_url, "api_key": api_key, "timeout": timeout}
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: observed.update(request=request) or response
                )
            )
        )

    monkeypatch.setattr(generator_module.openai, "OpenAI", create_client)
    monkeypatch.setenv("MODEL_NAME", "llama3.2:3b")

    answer = ConversationalGenerator().generate(
        "hi",
        [
            {"role": "user", "content": "My name is Sam."},
            {"role": "assistant", "content": "Nice to meet you, Sam."},
        ],
    )

    assert answer == "Hi! How has your day been?"
    assert observed["client"] == {
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "ollama",
        "timeout": 120,
    }
    assert observed["request"]["model"] == "llama3.2:3b"
    assert [item["role"] for item in observed["request"]["messages"]] == [
        "system",
        "user",
        "assistant",
        "system",
        "user",
    ]
    assert observed["request"]["messages"][-1]["content"].endswith("\n\nhi")
    assert "answer in English" in observed["request"]["messages"][-2]["content"]
    system_prompt = observed["request"]["messages"][0]["content"]
    assert "intuition in plain language" in system_prompt
    assert "retrieval-augmented generation (RAG)" in system_prompt
    assert "Do not invent citations, sources, or facts." in system_prompt
    assert "Teach like a patient, precise tutor." in system_prompt
    assert "worked example" in system_prompt
    assert "When the user asks for depth" in system_prompt
    assert "not as a rigid template" in system_prompt
    assert "Choose the response language from the user's latest message" in system_prompt
    assert "If the latest message is clearly English, answer in English." in system_prompt
    assert "Do not let an older language request persist" in system_prompt
    assert "where the language is unclear, use English." in system_prompt
    assert "Hindi, English, and Hinglish" in system_prompt
    assert "answer in Hindi using Devanagari" in system_prompt
    assert "Use familiar, accurate examples" in system_prompt


def test_local_model_receives_document_context_as_untrusted_user_evidence(monkeypatch):
    observed = {}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Rotate every 90 days."))]
    )

    def create_client(**kwargs):
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: observed.update(request=request) or response
                )
            )
        )

    monkeypatch.setattr(generator_module.openai, "OpenAI", create_client)
    answer = ConversationalGenerator().generate(
        "How often?",
        evidence=[
            {
                "citation": "policy.txt, document, chunk 1",
                "text": "Rotate access keys every 90 days.",
            }
        ],
    )

    assert answer == "Rotate every 90 days."
    messages = observed["request"]["messages"]
    assert "untrusted reference data" in messages[1]["content"]
    assert messages[-1]["role"] == "user"
    assert "\n\nHow often?\n\nUNTRUSTED DOCUMENT EXCERPTS" in messages[-1]["content"]
    assert "answer in English" in messages[-2]["content"]
    assert "[policy.txt, document, chunk 1]" in messages[-1]["content"]
    assert "Rotate access keys every 90 days." in messages[-1]["content"]


@pytest.mark.parametrize(
    ("message", "expected_language"),
    [
        ("Please explain this clearly.", "answer in English"),
        ("मुझे यह साफ़ समझाइए।", "answer in Hindi in Devanagari"),
        ("Mujhe ye clearly samjhao.", "answer in natural Hinglish"),
    ],
)
def test_latest_message_selects_reply_language(message, expected_language):
    instruction = generator_module._reply_language_instruction(message)
    assert expected_language in instruction
    assert "overrides any conflicting language preference" in instruction


def test_model_status_reports_ready_when_model_is_available(monkeypatch):
    response = httpx.Response(
        200,
        json={"data": [{"id": "test-model"}]},
        request=httpx.Request("GET", "http://127.0.0.1:11434/v1/models"),
    )
    monkeypatch.setattr(generator_module.httpx, "get", lambda *args, **kwargs: response)

    assert generator_module.get_model_status() == {
        "status": "ready",
        "model": "test-model",
    }


def test_model_status_reports_missing_model(monkeypatch):
    response = httpx.Response(
        200,
        json={"data": [{"id": "other-model"}]},
        request=httpx.Request("GET", "http://127.0.0.1:11434/v1/models"),
    )
    monkeypatch.setattr(generator_module.httpx, "get", lambda *args, **kwargs: response)

    assert generator_module.get_model_status() == {
        "status": "model_missing",
        "model": "test-model",
    }


def test_model_status_reports_offline(monkeypatch):
    def connection_error(*args, **kwargs):
        assert args == ("http://127.0.0.1:11434/v1/models",)
        assert kwargs == {"headers": {}, "timeout": 5}
        raise httpx.ConnectError("Model provider is offline")

    monkeypatch.setattr(generator_module.httpx, "get", connection_error)

    assert generator_module.get_model_status() == {
        "status": "offline",
        "model": "test-model",
    }


def test_local_model_connection_failure_is_actionable(monkeypatch):
    def create_client(**kwargs):
        assert kwargs["base_url"] == "http://127.0.0.1:11434/v1"
        assert kwargs["api_key"] == "ollama"
        raise generator_module.openai.APIConnectionError(
            message="failed to connect",
            request=httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions"),
        )

    monkeypatch.setattr(generator_module.openai, "OpenAI", create_client)

    with pytest.raises(ChatModelError, match="configured model endpoint"):
        ConversationalGenerator().generate("hello")


def test_local_model_missing_error_gives_pull_command(monkeypatch):
    def create_client(**kwargs):
        assert kwargs["base_url"] == "http://127.0.0.1:11434/v1"
        assert kwargs["api_key"] == "ollama"
        response = httpx.Response(
            404,
            request=httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions"),
        )
        raise generator_module.openai.NotFoundError(
            message="model not found",
            response=response,
            body=None,
        )

    monkeypatch.setattr(generator_module.openai, "OpenAI", create_client)

    with pytest.raises(ChatModelError, match="model provider"):
        ConversationalGenerator().generate("hello")


def test_empty_local_model_response_is_not_silently_accepted(monkeypatch):
    response = SimpleNamespace(choices=[])

    def create_completion(**request):
        assert request["model"] == "test-model"
        return response

    def create_client(**kwargs):
        assert kwargs["base_url"] == "http://127.0.0.1:11434/v1"
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create_completion))
        )

    monkeypatch.setattr(
        generator_module.openai,
        "OpenAI",
        create_client,
    )

    with pytest.raises(ChatModelError, match="empty response"):
        ConversationalGenerator().generate("hello")


def test_remote_model_api_uses_configured_url_and_bearer_key(monkeypatch):
    observed = {}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Remote response"))]
    )

    def create_client(*, base_url, api_key, timeout):
        observed.update(base_url=base_url, api_key=api_key, timeout=timeout)
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: response)
            )
        )

    monkeypatch.setenv("MODEL_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("MODEL_API_KEY", "remote-secret")
    monkeypatch.setenv("MODEL_NAME", "provider/model")
    monkeypatch.setattr(generator_module.openai, "OpenAI", create_client)

    assert ConversationalGenerator().generate("Hello") == "Remote response"
    assert observed == {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "remote-secret",
        "timeout": 120,
    }


def test_remote_model_status_sends_bearer_key(monkeypatch):
    observed = {}
    response = httpx.Response(
        200,
        json={"data": [{"id": "test-model"}]},
        request=httpx.Request("GET", "https://openrouter.ai/api/v1/models"),
    )

    def get(url, **kwargs):
        observed.update(url=url, kwargs=kwargs)
        return response

    monkeypatch.setenv("MODEL_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("MODEL_API_KEY", "remote-secret")
    monkeypatch.setattr(generator_module.httpx, "get", get)

    assert generator_module.get_model_status() == {
        "status": "ready",
        "model": "test-model",
    }
    assert observed["url"] == "https://openrouter.ai/api/v1/models"
    assert observed["kwargs"]["headers"] == {"Authorization": "Bearer remote-secret"}


def test_model_api_key_requires_https(monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", "http://model.example.net/v1")
    monkeypatch.setenv("MODEL_API_KEY", "remote-secret")

    with pytest.raises(ChatModelError, match="HTTPS MODEL_BASE_URL"):
        ConversationalGenerator().generate("Hello")

    assert generator_module.get_model_status() == {
        "status": "offline",
        "model": "test-model",
    }


def test_render_uses_openrouter_and_requires_secret_and_model():
    from pathlib import Path

    render_config = (Path(__file__).resolve().parents[1] / "render.yaml").read_text()
    assert "key: MODEL_BASE_URL\n        value: https://openrouter.ai/api/v1" in render_config
    assert "key: MODEL_API_KEY\n        sync: false" in render_config
    assert "key: MODEL_NAME\n        sync: false" in render_config
    assert "127.0.0.1" not in render_config
