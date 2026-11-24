"""Preflight T17: doubled caption blocks (two on screen at once, or one that ends before it starts) fail the ad."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools')]
import preflight  # noqa: E402

HEAD = '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'


def line(a, b, text, style='Cap'):
    f = lambda t: f'0:{int(t // 60):02d}:{t % 60:05.2f}'  # noqa: E731
    return f'Dialogue: 0,{f(a)},{f(b)},{style},,0,0,0,,{{\\an2}}{text}\n'


class CaptionEvents(unittest.TestCase):
    def check(self, body):
        with tempfile.TemporaryDirectory() as td:
            kit = pathlib.Path(td) / 'EDIT_KIT'
            kit.mkdir()
            (kit / 'captions.ass').write_text(HEAD + body)
            return preflight.check_caption_events(td)

    def test_clean_cards_pass(self):
        out = self.check(line(0, 1.5, 'MY KIDS BOTH') + line(1.5, 3.0, 'ADORE EVERY PET') + line(2.95, 4.2, 'THAT THEY KEEP'))
        self.assertEqual(out, ['PASS T17 no doubled captions in captions.ass'])

    def test_two_blocks_at_once_fail(self):
        out = self.check(line(15.3, 17.44, 'MY KIDS BOTH ADORE') + line(18.66, 20.24, 'KEEP BUT THEIR') + line(16.97, 18.47, 'ADORE EVERY PET THAT'))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith('FAIL T17 doubled captions in captions.ass: 1 pairs'), out[0])
        self.assertIn("'MY KIDS BOTH ADORE' 15.30-17.44s with 'ADORE EVERY PET THAT' from 16.97s", out[0])

    def test_a_block_that_ends_before_it_starts_fails(self):
        out = self.check(line(1, 2, 'ONE') + line(21.68, 16.97, 'HAIR MY KIDS BOTH'))
        self.assertIn('1 ending before they start', out[0])
        self.assertTrue(out[0].startswith('FAIL T17'))

    def test_a_hook_box_over_the_captions_is_fine(self):
        out = self.check(line(0, 4, 'POV: THE COUCH', style='Hook') + line(0, 1.5, 'MY KIDS BOTH') + line(1.5, 3, 'ADORE EVERY PET'))
        self.assertTrue(out[0].startswith('PASS'))

    def test_no_caption_file_says_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(preflight.check_caption_events(td), [])


if __name__ == '__main__':
    unittest.main()
