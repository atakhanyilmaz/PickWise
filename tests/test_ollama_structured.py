"""Transport/schema contract tests; no real Gemma quality claims."""

import pytest

from core.llm.conversation import IntentDecision, OrderFields
from core.llm.ollama_client import InvalidModelOutput, OllamaClient


def client_with_response(monkeypatch, response):
    client = OllamaClient()
    client._metadata = {"model_tag": "gemma4:e2b"}
    requests = []

    def request(path, payload=None):
        requests.append((path, payload))
        return response

    monkeypatch.setattr(client, "_request", request)
    return client, requests


def test_schema_is_enforced_in_transport_and_audited(monkeypatch):
    client, requests = client_with_response(
        monkeypatch,
        {
            "done": True,
            "done_reason": "stop",
            "message": {"content": '{"tool":"simulate_order","evidence":"Yeni iş"}'},
        },
    )
    output, metadata = client.structured(
        IntentDecision, "Niyeti çıkar", {"user_text": "Yeni iş"}, "intent-v1"
    )
    assert output.tool == "simulate_order"
    payload = requests[0][1]
    assert payload["format"] == IntentDecision.model_json_schema()
    assert payload["options"]["temperature"] == 0
    assert metadata["output_mode"] == "json_schema_with_pydantic_validation"
    assert len(metadata["schema_sha256"]) == 64
    assert metadata["num_predict"] == payload["options"]["num_predict"]
    assert "schema_sha256" not in client._metadata


@pytest.mark.parametrize(
    "response",
    [
        {"done": False, "message": {"content": "{}"}},
        {"done": True, "done_reason": "length", "message": {"content": "{}"}},
        {"done": True, "message": {"content": "not JSON"}},
        {
            "done": True,
            "message": {"content": '{"tool":"delete_plan","evidence":"sil"}'},
        },
        {"done": True, "message": {"content": '{"tool":"inspect_plan"}'}},
        {
            "done": True,
            "message": {
                "content": '{"tool":"inspect_plan","evidence":"plan","execute":true}'
            },
        },
        {"done": True},
    ],
)
def test_constrained_output_still_requires_local_validation(monkeypatch, response):
    client, requests = client_with_response(monkeypatch, response)
    with pytest.raises(InvalidModelOutput):
        client.structured(IntentDecision, "Niyet", {"user_text": "plan"}, "v1")
    assert len(requests) == 1  # No hidden retries or automatic repair.


def test_nested_nullable_schema_is_sent_without_flattening(monkeypatch):
    fields = OrderFields(
        order_name=None,
        operations=[
            {
                "name": "işlem",
                "options": [{"machine_text": "Torna 1", "duration_text": None}],
            }
        ],
        deadline_kind="none",
        deadline_text=None,
        preservation="none",
        preservation_text=None,
    )
    client, requests = client_with_response(
        monkeypatch, {"done": True, "message": {"content": fields.model_dump_json()}}
    )
    output, _ = client.structured(OrderFields, "Alanlar", {}, "fields-v2")
    assert output.operations[0].options[0].duration_text is None
    assert requests[0][1]["format"] == OrderFields.model_json_schema()
