import unittest

from jarvis.brain import Agent
from jarvis.llm import OllamaError


class FakeClient:
    def __init__(self, response: str = "Hello from the agent.") -> None:
        self.response = response
        self.calls: list[list[dict[str, str]]] = []

    def chat_stream(self, messages, on_token):
        self.calls.append([message.copy() for message in messages])
        on_token(self.response)
        return self.response


class FailingClient:
    def chat_stream(self, messages, on_token):
        raise OllamaError("test failure")


class AgentTests(unittest.TestCase):
    def test_unsuccessful_generation_preserves_existing_conversation(self):
        agent = Agent(FakeClient())
        agent.respond_stream('First turn', lambda token: None)
        original = agent.messages
        for error in [KeyboardInterrupt(), ValueError('invalid request'), RuntimeError('callback failed')]:
            with self.subTest(error=type(error).__name__):
                def fail(token):
                    raise error
                with self.assertRaises(type(error)):
                    agent.respond_stream('Unfinished turn', fail)
                self.assertEqual(agent.messages, original)
        agent.respond_stream('Next turn', lambda token: None)
        self.assertEqual(len(agent.messages), len(original) + 2)

    def test_agent_manages_context_and_reset(self) -> None:
        client = FakeClient()
        agent = Agent(client, system_prompt="Test system prompt")
        tokens: list[str] = []

        response = agent.respond_stream(" Hello ", tokens.append)

        self.assertEqual(response, "Hello from the agent.")
        self.assertEqual(tokens, ["Hello from the agent."])
        self.assertEqual(
            agent.messages,
            [
                {"role": "system", "content": "Test system prompt"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hello from the agent."},
            ],
        )
        agent.reset()
        self.assertEqual(agent.messages, [{"role": "system", "content": "Test system prompt"}])

    def test_agent_rolls_back_user_message_on_llm_error(self) -> None:
        agent = Agent(FailingClient())

        with self.assertRaises(OllamaError):
            agent.respond_stream("Hello", lambda token: None)

        self.assertEqual(len(agent.messages), 1)
        self.assertEqual(agent.messages[0]["role"], "system")

    def test_agent_rejects_empty_input(self) -> None:
        agent = Agent(FakeClient())

        with self.assertRaises(ValueError):
            agent.respond_stream("   ", lambda token: None)

    def test_coding_requests_use_optional_coding_client(self) -> None:
        general = FakeClient("general")
        coding = FakeClient("coding")
        agent = Agent(general, coding_client=coding)

        self.assertEqual(agent.respond_stream("Debug this Python project", lambda token: None), "coding")
        self.assertEqual(len(general.calls), 0)
        self.assertEqual(len(coding.calls), 1)


if __name__ == "__main__":
    unittest.main()
