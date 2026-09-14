from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from jarvis.tools.presentations import Presentations
from jarvis.tools.registry import ToolRegistry


PRESENTATION_XML = '''<?xml version="1.0"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst>
</p:presentation>'''
RELATIONSHIPS_XML = '''<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Target="slides/slide1.xml"/>
 <Relationship Id="rId2" Target="slides/slide2.xml"/>
</Relationships>'''


def slide_xml(*texts):
    runs = ''.join(f'<a:r><a:t>{text}</a:t></a:r>' for text in texts)
    return (f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{runs}</p:sld>')


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deck = self.root / 'biology lesson.pptx'
        with ZipFile(self.deck, 'w') as archive:
            archive.writestr('ppt/presentation.xml', PRESENTATION_XML)
            archive.writestr('ppt/_rels/presentation.xml.rels', RELATIONSHIPS_XML)
            archive.writestr('ppt/slides/slide1.xml', slide_xml('Second', 'Details B'))
            archive.writestr('ppt/slides/slide2.xml', slide_xml('First', 'Details A'))
        self.presentations = Presentations((self.root,))

    def test_finds_and_extracts_slides_in_presentation_order(self):
        found = self.presentations.find('biology')
        self.assertEqual(found['matches'][0]['path'], str(self.deck))
        result = self.presentations.inspect(str(self.deck))
        self.assertEqual(result['slide_count'], 2)
        self.assertEqual([slide['title'] for slide in result['slides']], ['First', 'Second'])
        self.assertIn('Details A', result['slides'][0]['content'])

    def test_open_requires_approval_and_uses_exact_file(self):
        denied = ToolRegistry(self.presentations.tools(), lambda *_: False)
        inspection_id = self.presentations.inspect(str(self.deck))['inspection_id']
        arguments = {'path': str(self.deck), 'inspection_id': inspection_id}
        self.assertFalse(denied.execute('open_presentation', arguments)['ok'])
        allowed = ToolRegistry(self.presentations.tools(), lambda *_: True)
        with patch('jarvis.tools.presentations.os.name', 'nt'), \
             patch('jarvis.tools.presentations.os.startfile', create=True) as startfile:
            self.assertTrue(allowed.execute('open_presentation', arguments)['ok'])
            startfile.assert_called_once_with(str(self.deck))

    def test_rejects_macro_enabled_and_outside_files(self):
        macro = self.root / 'unsafe.pptm'
        macro.write_bytes(b'not a presentation')
        with self.assertRaisesRegex(ValueError, 'macro-free'):
            self.presentations.inspect(str(macro))
        with self.assertRaisesRegex(ValueError, 'approved folders'):
            self.presentations.inspect(str(self.root.parent / 'outside.pptx'))


if __name__ == '__main__':
    unittest.main()
