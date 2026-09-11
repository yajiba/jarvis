from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from jarvis.brain import Agent
from jarvis.llm import OllamaError
from jarvis.tools import Tool, ToolRegistry


def call(name='get_time', arguments=None):
    return {'function': {'name': name, 'arguments': arguments or {}}}


class Client:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def chat_message_stream(self, messages, on_token, tools):
        self.requests.append(deepcopy(messages))
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        on_token(reply.get('content', ''))
        return reply


class ToolAgentTests(unittest.TestCase):
    def setUp(self):
        self.handler = Mock(return_value='12:00')
        self.registry = ToolRegistry([Tool('get_time', 'Time', {'properties': {}}, self.handler)])

    def test_model_tool_result_and_final_answer(self):
        client = Client([{'role': 'assistant', 'content': '', 'tool_calls': [call()]},
                         {'role': 'assistant', 'content': 'It is noon.'}])
        agent = Agent(client, tools=self.registry)
        tokens = []
        self.assertEqual(agent.respond_stream('Time?', tokens.append), 'It is noon.')
        self.handler.assert_called_once_with()
        result = client.requests[1][-1]
        self.assertEqual(result['role'], 'tool')
        self.assertEqual(result['tool_name'], 'get_time')
        self.assertEqual(json.loads(result['content']), {'ok': True, 'result': '12:00'})
        snapshot = agent.messages
        snapshot[2]['tool_calls'][0]['function']['name'] = 'mutated'
        self.assertEqual(agent.messages[2]['tool_calls'][0]['function']['name'], 'get_time')
        agent.reset()
        self.assertEqual(len(agent.messages), 1)

    def test_unknown_tool_returns_error_to_model(self):
        client = Client([{'role': 'assistant', 'content': '', 'tool_calls': [call('shell')]},
                         {'role': 'assistant', 'content': 'Unavailable.'}])
        Agent(client, tools=self.registry).respond_stream('Execute', lambda t: None)
        self.assertFalse(json.loads(client.requests[1][-1]['content'])['ok'])
        self.handler.assert_not_called()

    def test_tool_loop_is_bounded(self):
        reply = {'role': 'assistant', 'content': '', 'tool_calls': [call()]}
        agent = Agent(Client([reply, reply]), tools=self.registry, max_tool_rounds=1)
        with self.assertRaisesRegex(OllamaError, 'limit'):
            agent.respond_stream('Time?', lambda t: None)
        self.handler.assert_called_once()

    def test_executed_results_survive_followup_failure(self):
        client = Client([{'role': 'assistant', 'content': '', 'tool_calls': [call()]},
                         OllamaError('offline')])
        agent = Agent(client, tools=self.registry)
        with self.assertRaises(OllamaError):
            agent.respond_stream('Time?', lambda t: None)
        self.assertEqual(agent.messages[-1]['role'], 'tool')

    def test_failed_initial_generation_does_not_change_history(self):
        agent = Agent(Client([KeyboardInterrupt()]), tools=self.registry)
        with self.assertRaises(KeyboardInterrupt):
            agent.respond_stream('Time?', lambda t: None)
        self.assertEqual(len(agent.messages), 1)

    def test_oversized_batch_executes_nothing(self):
        client = Client([{'role': 'assistant', 'content': '', 'tool_calls': [call()] * 9}])
        agent = Agent(client, tools=self.registry)
        with self.assertRaisesRegex(OllamaError, 'limit'):
            agent.respond_stream('Time?', lambda t: None)
        self.handler.assert_not_called()
        self.assertEqual(len(agent.messages), 1)
