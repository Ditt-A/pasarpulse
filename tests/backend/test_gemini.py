import json

from app.backend.reasoning import gemini


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary": "The selected forecast is available.",
                                            "reasons": [],
                                            "actions": [{"action_id": "ABSTAIN", "evidence_ids": []}],
                                            "dashboard_actions": [],
                                            "abstained": True,
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode()


def test_gemini_uses_generate_content_structured_high_thinking(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(gemini, "LLM_API_KEY", "runtime-only-test-key")
    monkeypatch.setattr(gemini, "LLM_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(gemini, "LLM_THINKING_LEVEL", "high")
    monkeypatch.setattr(gemini.urllib.request, "urlopen", fake_urlopen)

    response = gemini.ask_gemini("What happened?", {"forecast": {}, "evidence_quality": {}})

    assert response.abstained is True
    assert captured["url"].endswith("/v1beta/models/gemini-3.5-flash-lite:generateContent")
    assert captured["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["generationConfig"]["responseSchema"] == gemini.COPILOT_SCHEMA
    assert captured["body"]["system_instruction"]["parts"]
    assert captured["body"]["contents"][0]["role"] == "user"
