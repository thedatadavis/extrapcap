from modal_app.functions import admin_trigger as trigger_module


def test_admin_trigger_spawns_supported_modal_workflow(monkeypatch):
    calls = []

    class FakeFunction:
        def spawn(self):
            return type("Call", (), {"object_id": "fc-test-123"})()

    monkeypatch.setenv("ADMIN_TRIGGER_TOKEN", "test-secret")
    monkeypatch.setattr(
        trigger_module.modal.Function,
        "from_name",
        lambda app_name, workflow: calls.append((app_name, workflow)) or FakeFunction(),
    )

    result = trigger_module.admin_trigger.local(
        {"workflow": "candidate_review"},
        authorization="Bearer test-secret",
    )

    assert result == {
        "accepted": True,
        "workflow": "candidate_review",
        "function_call_id": "fc-test-123",
    }
    assert calls == [("extrapcap", "candidate_review")]
