import base64
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from jarvis.config import Settings
from jarvis.tools.vision import Vision
from jarvis.tools.registry import ToolRegistry


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.settings=Settings(vision_model='vision-test',gui_enabled=True)
        self.client=Mock()
        self.client.chat.return_value='A blue square.'
        self.vision=Vision(self.settings,(self.root,),self.client)

    def test_real_image_encoded_for_local_model(self):
        from PIL import Image
        Image.new('RGB',(32,32),'blue').save(self.root/'sample.png')
        result=self.vision.analyze_image('sample.png','What color is this?')
        self.assertEqual(result['answer'],'A blue square.')
        messages=self.client.chat.call_args.args[0]
        self.assertTrue(base64.b64decode(messages[1]['images'][0]).startswith(b'\x89PNG'))

    def test_unapproved_image_paths_and_missing_model_are_rejected(self):
        (self.root/'.private.png').write_bytes(b'fake')
        for path in ['../outside.png','.private.png']:
            with self.assertRaises((ValueError,OSError)):
                self.vision.analyze_image(path,'Describe it')
        self.client.chat.assert_not_called()
        disabled=Vision(Settings(),(self.root,),self.client)
        with self.assertRaisesRegex(ValueError,'JARVIS_VISION_MODEL'):
            disabled.analyze_screen('Describe it')

    def test_remote_host_rejected_before_capture(self):
        remote=Vision(replace(self.settings,ollama_host='https://example.com'),(self.root,),self.client)
        with patch.object(remote,'_desktop') as desktop:
            with self.assertRaisesRegex(ValueError,'loopback'):
                remote.analyze_screen('Describe it')
            desktop.assert_not_called()

    def test_screen_and_camera_denied_without_capture(self):
        registry=ToolRegistry(self.vision.tools())
        with patch.object(self.vision,'_desktop') as desktop:
            self.assertFalse(registry.execute('analyze_screen',{'question':'Describe it'})['ok'])
            self.assertFalse(registry.execute('analyze_camera',{'question':'Describe it'})['ok'])
            desktop.assert_not_called()

    def test_gui_requires_recent_single_use_observation(self):
        desktop=Mock()
        desktop.size.return_value=(100,100)
        desktop.FailSafeException=RuntimeError
        args={'observation_id':'token','action':'click','value':'20,30'}
        registry=ToolRegistry(self.vision.tools(),lambda *_:True)
        with patch.object(self.vision,'_desktop',return_value=desktop):
            self.assertFalse(registry.execute('desktop_action',args)['ok'])
            self.vision._observation=('token',time.monotonic(),(100,100))
            self.assertFalse(registry.execute('desktop_action',{**args,'value':'999,30'})['ok'])
            self.assertTrue(registry.execute('desktop_action',args)['ok'])
            desktop.click.assert_called_once_with(20,30)
            self.assertFalse(registry.execute('desktop_action',args)['ok'])

    def test_disabled_expired_and_control_characters_are_rejected(self):
        self.vision._observation=('token',time.monotonic()-61,(100,100))
        with self.assertRaises(ValueError):
            self.vision.desktop_action('token','click','1,1')
        self.vision._observation=('token',time.monotonic(),(100,100))
        with self.assertRaises(ValueError):
            self.vision.action_preview('token','type','command\n')
        self.vision.settings=replace(self.settings,gui_enabled=False)
        with self.assertRaises(ValueError):
            self.vision.action_preview('token','key','enter')

    def test_camera_released_on_read_failure(self):
        camera=Mock()
        camera.isOpened.return_value=True
        camera.read.return_value=(False,None)
        cv2=Mock()
        cv2.VideoCapture.return_value=camera
        with patch.dict('sys.modules',{'cv2':cv2}):
            with self.assertRaisesRegex(RuntimeError,'frame'):
                self.vision.analyze_camera('Describe it')
        camera.release.assert_called_once()
