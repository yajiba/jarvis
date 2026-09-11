import os
import errno
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from jarvis.tools import Tool, ToolRegistry, create_local_tools


class RegistryTests(unittest.TestCase):
    def test_validation_and_permissions_precede_execution(self):
        handler = Mock(return_value='done')
        tool = Tool('test', 'Test', {'properties': {'name': {'type': 'string', 'enum': ['ok']}},
                                    'required': ['name']}, handler, 'confirm')
        registry = ToolRegistry([tool])
        for name, args in [('missing', {}), ('test', []), ('test', {}),
                           ('test', {'name': 1}), ('test', {'name': 'bad'}),
                           ('test', {'name': 'ok', 'extra': 'bad'}), ('test', {'name': 'ok'})]:
            with self.subTest(name=name, args=args):
                self.assertFalse(registry.execute(name, args)['ok'])
        handler.assert_not_called()
        denied = ToolRegistry([tool], confirm=lambda name, args: False)
        self.assertFalse(denied.execute('test', {'name': 'ok'})['ok'])
        handler.assert_not_called()
        allowed = ToolRegistry([tool], confirm=lambda name, args: True)
        self.assertTrue(allowed.execute('test', {'name': 'ok'})['ok'])
        handler.assert_called_once_with(name='ok')


class LocalToolTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tools = create_local_tools(self.root)

    def test_read_and_list_files(self):
        (self.root / 'hello.txt').write_text('hello', encoding='utf-8')
        (self.root / '.env').write_text('secret', encoding='utf-8')
        self.assertEqual(self.tools.execute('read_file', {'path': 'hello.txt'})['result'], 'hello')
        result = self.tools.execute('list_files', {'path': '.'})['result']
        self.assertEqual(result['entries'], [{'name': 'hello.txt', 'directory': False}])

    def test_paths_and_file_limits(self):
        (self.root / '.env').write_text('secret')
        (self.root / 'private.key').write_text('secret')
        (self.root / 'large.txt').write_bytes(b'x' * 32769)
        (self.root / 'binary').write_bytes(b'\x00\xff')
        for path in ['..', str(self.root.parent), '.env', 'private.key', 'large.txt', 'binary', 'missing', '.']:
            with self.subTest(path=path):
                self.assertFalse(self.tools.execute('read_file', {'path': path})['ok'])

    def test_symlink_escape_is_denied(self):
        with TemporaryDirectory() as outside:
            secret = Path(outside) / 'secret.txt'
            secret.write_text('private')
            link = self.root / 'link.txt'
            try:
                link.symlink_to(secret)
            except OSError as error:
                if getattr(error, 'winerror', None) != 1314 and error.errno not in {
                    errno.EPERM, errno.ENOSYS, errno.ENOTSUP,
                }:
                    raise
                # Exercise the post-resolution boundary even when the OS cannot
                # create a real symlink. All other paths resolve normally.
                original_resolve = Path.resolve
                def resolve_path(path, *args, **kwargs):
                    if path == link:
                        return original_resolve(secret, *args, **kwargs)
                    return original_resolve(path, *args, **kwargs)
                with patch.object(Path, 'resolve', autospec=True, side_effect=resolve_path) as resolve:
                    self._assert_escape_denied()
                    resolve.assert_any_call(link, strict=True)
            else:
                self._assert_escape_denied()

    def _assert_escape_denied(self):
        with patch.object(Path, 'open') as open_file:
            result = self.tools.execute('read_file', {'path': 'link.txt'})
        self.assertEqual(result, {'ok': False, 'error': 'Path is outside the allowed roots or unavailable'})
        open_file.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows adapter')
    def test_application_uses_fixed_executable_without_shell(self):
        with patch('jarvis.tools.local.subprocess.Popen') as launch, \
                patch('jarvis.tools.local.Path.is_file', return_value=True):
            self.assertTrue(self.tools.execute('open_application', {'name': 'vscode'})['ok'])
            args, kwargs = launch.call_args
            self.assertEqual(len(args[0]), 1)
            self.assertEqual(Path(args[0][0]).name, 'Code.exe')
            self.assertFalse(kwargs['shell'])
            launch.reset_mock()
            self.assertFalse(self.tools.execute('open_application', {'name': 'cmd /c whoami'})['ok'])
            launch.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows adapter')
    def test_launch_failures_and_folder_validation(self):
        with patch('jarvis.tools.local.Path.is_file', return_value=False):
            self.assertFalse(self.tools.execute('open_application', {'name': 'vscode'})['ok'])
        with patch('jarvis.tools.local.Path.is_file', return_value=True), \
                patch('jarvis.tools.local.subprocess.Popen', side_effect=OSError('Launch failed')):
            self.assertFalse(self.tools.execute('open_application', {'name': 'vscode'})['ok'])
        with patch('jarvis.tools.local.os.startfile') as launch:
            self.assertTrue(self.tools.execute('open_folder', {'path': '.'})['ok'])
            launch.assert_called_once_with(str(self.root.resolve()))
            launch.reset_mock()
            self.assertFalse(self.tools.execute('open_folder', {'path': '..'})['ok'])
            launch.assert_not_called()

    def test_system_tools(self):
        self.assertTrue(self.tools.execute('get_time', {})['ok'])
        self.assertIn('os', self.tools.execute('get_system_info', {})['result'])

    def test_configured_external_root_can_be_read_and_searched(self):
        with TemporaryDirectory() as external:
            external_root = Path(external)
            (external_root / 'sentrix.txt').write_text('Sentrix project', encoding='utf-8')
            tools = create_local_tools(self.root, allowed_roots=(external_root,))
            read = tools.execute('read_file', {'path': str(external_root / 'sentrix.txt')})
            search = tools.execute('search_files', {'pattern': '*.txt'})
            roots = tools.execute('list_allowed_roots', {})
            self.assertEqual(read, {'ok': True, 'result': 'Sentrix project'})
            self.assertIn('sentrix.txt', search['result']['matches'])
            self.assertIn(str(external_root.resolve()), roots['result'])
