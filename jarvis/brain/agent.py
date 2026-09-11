"""Conversation orchestration for JARVIS."""

from collections.abc import Callable
from copy import deepcopy
import json

from jarvis.llm import OllamaClient, OllamaError
from jarvis.memory import MemoryStore
from jarvis.prompts import SYSTEM_PROMPT
from jarvis.tools.registry import ToolRegistry


class Agent:
    """Maintain conversation context while delegating generation to an LLM client."""

    def __init__(
        self,
        client: OllamaClient,
        coding_client: OllamaClient | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        tools: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
        max_tool_rounds: int = 4,
    ) -> None:
        self.client = client
        self.coding_client = coding_client
        self.system_prompt = system_prompt
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be positive")
        self.tools = tools
        self.memory = memory
        self.conversation_id: str | None = None
        self.max_tool_rounds = max_tool_rounds
        self._messages: list[dict] = []
        self.on_activity: Callable[[str], None] = lambda activity: None
        self.reset()

    @property
    def messages(self) -> list[dict]:
        """Return a copy of the current context for inspection or diagnostics."""
        return deepcopy(self._messages)

    def reset(self) -> None:
        """Start a new conversation with the configured system prompt."""
        self._messages = [{"role": "system", "content": self.system_prompt}]
        if self.memory is not None:
            self.conversation_id = self.memory.start_conversation()

    def respond_stream(
        self,
        user_input: str,
        on_token: Callable[[str], None],
    ) -> str:
        """Generate a response and stream each token to the supplied callback."""
        cleaned_input = user_input.strip()
        if not cleaned_input:
            raise ValueError("user_input cannot be empty")

        pending_messages = self.messages
        pending_messages.append({"role": "user", "content": cleaned_input})
        if self.memory is not None and self.conversation_id is not None:
            self.memory.add_message(self.conversation_id, "user", cleaned_input)
        client = self._client_for(cleaned_input)
        if self.tools is not None:
            return self._respond_with_tools(pending_messages, on_token, client)
        response = client.chat_stream(pending_messages, on_token)
        self._messages = pending_messages + [{"role": "assistant", "content": response}]
        if self.memory is not None and self.conversation_id is not None:
            self.memory.add_message(self.conversation_id, "assistant", response)
        return response

    def _client_for(self, user_input: str) -> OllamaClient:
        if self.coding_client is not None:
            coding_terms = {
                "code", "coding", "debug", "bug", "error", "test", "project",
                "file", "function", "python", "javascript", "git", "repository",
            }
            if coding_terms.intersection(user_input.casefold().split()):
                return self.coding_client
        return self.client

    def _respond_with_tools(
        self,
        pending: list[dict],
        on_token: Callable[[str], None],
        client: OllamaClient,
    ) -> str:
        assert self.tools is not None
        for round_number in range(self.max_tool_rounds + 1):
            message = client.chat_message_stream(pending, on_token, tools=self.tools.schemas)
            calls = message.get('tool_calls', [])
            if not calls:
                self._messages = pending + [message]
                response = message['content'].strip()
                if self.memory is not None and self.conversation_id is not None:
                    self.memory.add_message(self.conversation_id, 'assistant', response)
                return response
            if round_number == self.max_tool_rounds or len(calls) > 8:
                raise OllamaError("Tool call limit reached; no further tools were executed")
            if message.get('content'):
                on_token('\n')
            pending.append(message)
            for call in calls:
                function = call['function']
                self.on_activity(function['name'].replace('_', ' ').capitalize())
                result = self.tools.execute(function['name'], function['arguments'])
                self.on_activity("Thinking")
                if self.memory is not None and self.conversation_id is not None:
                    self.memory.add_tool_history(
                        self.conversation_id, function['name'], function['arguments'], result
                    )
                pending.append({'role': 'tool', 'tool_name': function['name'],
                                'content': json.dumps(result, ensure_ascii=False)})
                if self.memory is not None and self.conversation_id is not None:
                    self.memory.add_message(
                        self.conversation_id,
                        'tool',
                        json.dumps(result, ensure_ascii=False),
                        function['name'],
                    )
            # Executed actions cannot be rolled back. Preserve results even if
            # the next generation fails, so subsequent turns know what happened.
            self._messages = deepcopy(pending)
        raise OllamaError("Tool call limit reached")
