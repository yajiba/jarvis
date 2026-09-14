"""Small Ollama client for the Phase 1 chat loop."""

import json
from collections.abc import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import cast


class OllamaError(RuntimeError):
    """Raised when Ollama cannot complete a request."""


def _request_error(host: str, timeout_seconds: float, error: OSError) -> OllamaError:
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, TimeoutError):
        return OllamaError(
            f"Ollama generation timed out after {timeout_seconds:g} seconds at {host}. "
            "The model may still be loading or the document may be too large."
        )
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return OllamaError(
            f"Ollama closed the connection during generation at {host}. "
            "Check the Ollama logs and available RAM/VRAM."
        )
    return OllamaError(f"Could not connect to Ollama at {host}. Is Ollama running?")


class OllamaClient:
    def __init__(
        self,
        host: str,
        model: str,
        timeout_seconds: float = 120.0,
        request_fn: Callable[..., object] | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._request_fn = request_fn or urlopen

    def chat(self, messages: list[dict[str, str]]) -> str:
        request = self._build_request(messages, stream=False)

        try:
            response = self._request_fn(request, timeout=self.timeout_seconds)
            with response:
                response_data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama returned HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise _request_error(self.host, self.timeout_seconds, error) from error
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
            raise OllamaError("Ollama returned an invalid response") from error

        try:
            return response_data["message"]["content"].strip()
        except (KeyError, TypeError, AttributeError) as error:
            raise OllamaError("Ollama response did not contain message content") from error

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        on_token: Callable[[str], None],
    ) -> str:
        return self.chat_message_stream(messages, on_token)["content"].strip()

    def chat_message_stream(
        self, messages: list[dict], on_token: Callable[[str], None],
        tools: list[dict] | None = None,
    ) -> dict:
        """Return an assistant message, preserving structured tool calls."""
        request = self._build_request(messages, stream=True, tools=tools)
        response_text: list[str] = []
        tool_calls: list[dict] = []
        completed = False

        try:
            response = self._request_fn(request, timeout=self.timeout_seconds)
            with response:
                response_lines = cast(Iterable[bytes], response)
                for raw_line in response_lines:
                    if not raw_line.strip():
                        continue
                    response_data = json.loads(raw_line.decode("utf-8"))
                    if not isinstance(response_data, dict):
                        raise OllamaError("Ollama returned an invalid streaming response")
                    if "error" in response_data:
                        raise OllamaError(f"Ollama generation failed: {response_data['error']}")
                    message = response_data.get("message", {})
                    token = message.get("content", "")
                    if not isinstance(token, str):
                        raise OllamaError("Ollama returned invalid message content")
                    calls = message.get("tool_calls", [])
                    if not isinstance(calls, list):
                        raise OllamaError("Ollama returned invalid tool calls")
                    for call in calls:
                        if not isinstance(call, dict) or not isinstance(call.get('function'), dict):
                            raise OllamaError("Ollama returned an invalid tool call")
                        function = call['function']
                        if not isinstance(function.get('name'), str) or not isinstance(function.get('arguments'), dict):
                            raise OllamaError("Ollama returned invalid tool arguments")
                        tool_calls.append(call)
                    if token:
                        response_text.append(token)
                        on_token(token)
                    if response_data.get("done") is True:
                        completed = True
                        break
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama returned HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise _request_error(self.host, self.timeout_seconds, error) from error
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError) as error:
            raise OllamaError("Ollama returned an invalid streaming response") from error

        if not completed:
            raise OllamaError("Ollama stream ended before generation completed")
        if not "".join(response_text).strip() and not tool_calls:
            raise OllamaError("Ollama returned no message content")
        result = {"role": "assistant", "content": "".join(response_text)}
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    def _build_request(
        self, messages: list[dict], stream: bool, tools: list[dict] | None = None
    ) -> Request:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": stream,
                "think": False,
                **({"tools": tools} if tools is not None else {}),
            }
        ).encode("utf-8")
        return Request(
            f"{self.host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
