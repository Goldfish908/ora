import json

import pytest

from ora_agent.llm import LLMRequestError, _read_sse_payload


class FakeResponse:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def line(payload):
    return f"data: {json.dumps(payload)}\n".encode()


def test_stream_requires_terminal_marker():
    response = FakeResponse([line({"choices": [{"delta": {"content": "partial"}}]})])
    with pytest.raises(LLMRequestError, match="ended before"):
        _read_sse_payload(response, 0, lambda: None)


def test_stream_surfaces_error_payload():
    response = FakeResponse([line({"error": {"message": "generation failed"}})])
    with pytest.raises(LLMRequestError, match="error payload"):
        _read_sse_payload(response, 0, lambda: None)


def test_stream_accepts_finish_without_done_marker():
    response = FakeResponse([
        line({"model": "m", "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}),
    ])
    raw, chunks, _ = _read_sse_payload(response, 0, lambda: None)
    assert json.loads(raw)["choices"][0]["finish_reason"] == "stop"
    assert chunks == 1
