import json
import unittest
from urllib.request import Request

from jarvis.llm import OllamaClient, OllamaError
from jarvis.brain import Agent


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeStreamResponse:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.lines = [json.dumps(payload).encode("utf-8") + b"\n" for payload in payloads]

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


class OllamaClientTests(unittest.TestCase):
    def test_structured_tool_calls_and_request_schemas(self):
        captured = {}
        call = {'function': {'name': 'get_time', 'arguments': {}}}
        def request(request, **kwargs):
            captured.update(json.loads(request.data))
            return FakeStreamResponse([
                {'message': {'content': '', 'tool_calls': [call]}, 'done': False},
                {'done': True},
            ])
        client = OllamaClient('http://localhost:11434', 'test', request_fn=request)
        schemas = [{'type': 'function', 'function': {'name': 'get_time'}}]
        result = client.chat_message_stream([], lambda t: None, tools=schemas)
        self.assertEqual(result['tool_calls'], [call])
        self.assertEqual(captured['tools'], schemas)

    def test_malformed_tool_calls_are_rejected(self):
        for calls in [None, {}, [None], [{'function': {}}],
                      [{'function': {'name': 'get_time', 'arguments': 'shell'}}]]:
            with self.subTest(calls=calls):
                client = OllamaClient('http://localhost:11434', 'test',
                    request_fn=lambda *a, **k: FakeStreamResponse([
                        {'message': {'tool_calls': calls}, 'done': True}]))
                with self.assertRaises(OllamaError):
                    client.chat_message_stream([], lambda t: None, tools=[])

    def test_failed_streams_do_not_commit_partial_history(self) -> None:
        partial = {"message": {"content": "partial"}, "done": False}
        cases = [
            ([partial], "before generation completed"),
            ([partial, {"error": "generation failed"}], "generation failed"),
            ([partial, {"message": {"content": 123}}], "invalid message content"),
            ([partial, {"message": None}], "invalid streaming response"),
        ]
        for payloads, error in cases:
            with self.subTest(payloads=payloads):
                client = OllamaClient("http://localhost:11434", "test",
                    request_fn=lambda *args, **kwargs: FakeStreamResponse(payloads))
                agent = Agent(client)
                original = agent.messages
                tokens = []
                with self.assertRaisesRegex(OllamaError, error):
                    agent.respond_stream("Hello", tokens.append)
                self.assertEqual(tokens, ["partial"])
                self.assertEqual(agent.messages, original)

    def test_separate_completion_frame(self) -> None:
        client = OllamaClient("http://localhost:11434", "test",
            request_fn=lambda *args, **kwargs: FakeStreamResponse([
                {"message": {"content": "Hello"}, "done": False},
                {"done": True},
            ]))
        self.assertEqual(client.chat_stream([], lambda token: None), "Hello")

    def test_whitespace_only_response_is_rejected(self) -> None:
        client = OllamaClient("http://localhost:11434", "test",
            request_fn=lambda *args, **kwargs: FakeStreamResponse([
                {"message": {"content": "  "}, "done": True},
            ]))
        with self.assertRaisesRegex(OllamaError, "no message content"):
            client.chat_stream([], lambda token: None)

    def test_chat_returns_assistant_content(self) -> None:
        captured: dict[str, object] = {}

        def request(request: object, timeout: float) -> FakeResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"message": {"content": " Hello from JARVIS. "}})

        client = OllamaClient("http://localhost:11434", "qwen3:8b", request_fn=request)

        result = client.chat([{"role": "user", "content": "Hello"}])

        self.assertEqual(result, "Hello from JARVIS.")
        self.assertEqual(captured["timeout"], 120.0)
        request = captured["request"]
        self.assertIsInstance(request, Request)
        request_payload = json.loads(request.data.decode("utf-8"))
        self.assertFalse(request_payload["think"])

    def test_invalid_response_raises_ollama_error(self) -> None:
        def request(request: object, timeout: float) -> FakeResponse:
            return FakeResponse({"done": True})

        client = OllamaClient("http://localhost:11434", "qwen3:8b", request_fn=request)

        with self.assertRaises(OllamaError):
            client.chat([])

    def test_chat_stream_emits_tokens_immediately(self) -> None:
        captured: dict[str, object] = {}

        def request(request: Request, timeout: float) -> FakeStreamResponse:
            captured["request"] = request
            return FakeStreamResponse(
                [
                    {"message": {"content": "Hello"}, "done": False},
                    {"message": {"content": " from JARVIS."}, "done": True},
                ]
            )

        client = OllamaClient("http://localhost:11434", "qwen3:8b", request_fn=request)
        tokens: list[str] = []

        result = client.chat_stream([], tokens.append)

        self.assertEqual(result, "Hello from JARVIS.")
        self.assertEqual(tokens, ["Hello", " from JARVIS."])
        request_payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertTrue(request_payload["stream"])


if __name__ == "__main__":
    unittest.main()
