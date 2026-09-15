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
        fast_client: OllamaClient | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        tools: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
        max_tool_rounds: int = 4,
        max_context_characters: int = 48_000,
    ) -> None:
        self.client = client
        self.coding_client = coding_client
        self.fast_client = fast_client
        self.system_prompt = system_prompt
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be positive")
        self.tools = tools
        self.memory = memory
        self.conversation_id: str | None = None
        self.max_tool_rounds = max_tool_rounds
        if max_context_characters < 4_000:
            raise ValueError("max_context_characters must be at least 4000")
        self.max_context_characters = max_context_characters
        self._messages: list[dict] = []
        self.on_activity: Callable[[str], None] = lambda activity: None
        self._last_client = client
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

    def restore(self, conversation_id: str, messages: list[dict]) -> None:
        """Restore persisted chat context while excluding internal timestamps."""
        restored = []
        for message in messages:
            role = message.get('role')
            content = message.get('content')
            if role not in {'user', 'assistant'} or not isinstance(content, str):
                continue
            item = {'role': role, 'content': content}
            restored.append(item)
        self._messages = self._bounded_context(
            [{'role': 'system', 'content': self.system_prompt}, *restored])
        self.conversation_id = conversation_id

    def respond_stream(
        self,
        user_input: str,
        on_token: Callable[[str], None],
    ) -> str:
        """Generate a response and stream each token to the supplied callback."""
        cleaned_input = user_input.strip()
        if not cleaned_input:
            raise ValueError("user_input cannot be empty")

        pending_messages = self._bounded_context(self.messages)
        pending_messages.append({"role": "user", "content": cleaned_input})
        if self.memory is not None and self.conversation_id is not None:
            self.memory.add_message(self.conversation_id, "user", cleaned_input)
        client = self._client_for(cleaned_input)
        self._last_client = client
        # Lightweight fast-model requests never need the full tool schema.
        if self.tools is not None and client is not self.fast_client:
            return self._respond_with_tools(pending_messages, on_token, client)
        response = client.chat_stream(pending_messages, on_token)
        self._messages = pending_messages + [{"role": "assistant", "content": response}]
        if self.memory is not None and self.conversation_id is not None:
            self.memory.add_message(self.conversation_id, "assistant", response)
        return response

    @property
    def diagnostics(self) -> dict:
        return {'model': getattr(self._last_client, 'model', None),
                'metrics': deepcopy(getattr(self._last_client, 'last_metrics', {}))}

    def _bounded_context(self, messages: list[dict]) -> list[dict]:
        """Keep recent complete user turns within the local model's practical budget."""
        if len(messages) <= 1:
            return messages
        system = messages[0]
        turns = []
        current = []
        for message in messages[1:]:
            if message.get('role') == 'user' and current:
                turns.append(current)
                current = []
            current.append(message)
        if current:
            turns.append(current)
        kept = []
        used = len(str(system.get('content', '')))
        for turn in reversed(turns):
            size = sum(len(str(item.get('content', ''))) for item in turn)
            if kept and used + size > self.max_context_characters:
                break
            kept.append(turn)
            used += size
        return [system] + [message for turn in reversed(kept) for message in turn]

    def _client_for(self, user_input: str) -> OllamaClient:
        if self.coding_client is not None:
            coding_terms = {
                "code", "coding", "debug", "bug", "error", "test", "project",
                "file", "function", "python", "javascript", "git", "repository",
            }
            if coding_terms.intersection(user_input.casefold().split()):
                return self.coding_client
        if self.fast_client is not None:
            normalized = user_input.casefold().strip(' .!?')
            fast_phrases = ('hello', 'hi', 'hey', 'thanks', 'thank you', 'good morning',
                            'good afternoon', 'good evening', 'who are you', 'what can you do')
            if len(user_input) <= 120 and any(normalized == phrase or normalized.startswith(phrase + ' ')
                                              for phrase in fast_phrases):
                return self.fast_client
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
