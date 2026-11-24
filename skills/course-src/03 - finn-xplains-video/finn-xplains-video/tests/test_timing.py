import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'voiceover_timing.py'

class TimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / 'voice.wav'
        with wave.open(str(self.audio), 'wb') as f:
            f.setparams((2, 2, 8000, 0, 'NONE', 'not compressed'))
            f.writeframes(b'\x00' * 24001 * 4)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)

    def test_measures_full_sample_duration_including_silence(self):
        result = self.run_cli('probe', self.audio, '--fps', '30')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['decoded_samples'], 24001)
        self.assertEqual(data['sample_rate'], 8000)
        self.assertEqual(data['channels'], 2)
        self.assertEqual(data['duration_fraction'], '24001/8000')
        self.assertEqual(data['video_frames'], 91)

    def test_allocates_contiguous_scene_frames_from_the_full_audio(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio, '--fps', '30').stdout)
        data = json.loads(timing.read_text())
        scenes = self.root / 'scenes.json'
        scenes.write_text(json.dumps({'source_sha256': data['source_sha256'], 'scenes': [
            {'id': 'S01', 'start_sample': 0, 'end_sample': 8000},
            {'id': 'S02', 'start_sample': 8000, 'end_sample': 24001}
        ]}))
        result = self.run_cli('check', timing, scenes)
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = json.loads(result.stdout)
        self.assertEqual(checked['video_frames'], 91)
        self.assertEqual([(s['start_frame'], s['end_frame']) for s in checked['scenes']], [(0, 30), (30, 91)])

    def test_rejects_a_gap_in_scene_coverage(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio).stdout)
        data = json.loads(timing.read_text())
        scenes = self.root / 'scenes.json'
        scenes.write_text(json.dumps({'source_sha256': data['source_sha256'], 'scenes': [
            {'id': 'S01', 'start_sample': 0, 'end_sample': 8000},
            {'id': 'S02', 'start_sample': 8001, 'end_sample': 24001}
        ]}))
        result = self.run_cli('check', timing, scenes)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')

    def test_rejects_uncovered_audio_tail(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio).stdout)
        data = json.loads(timing.read_text())
        scenes = self.root / 'scenes.json'
        scenes.write_text(json.dumps({'source_sha256': data['source_sha256'], 'scenes': [
            {'id': 'S01', 'start_sample': 0, 'end_sample': 24000}
        ]}))
        self.assertEqual(self.run_cli('check', timing, scenes).returncode, 2)

    def test_rejects_a_board_for_a_different_recording(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio).stdout)
        scenes = self.root / 'scenes.json'
        scenes.write_text(json.dumps({'source_sha256': '0' * 64, 'scenes': [
            {'id': 'S01', 'start_sample': 0, 'end_sample': 24001}
        ]}))
        self.assertEqual(self.run_cli('check', timing, scenes).returncode, 2)

    def test_rejects_invalid_scene_intervals(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio).stdout)
        data = json.loads(timing.read_text())
        invalid = [
            [{'id': 'S01', 'start_sample': 0, 'end_sample': 0}, {'id': 'S02', 'start_sample': 0, 'end_sample': 24001}],
            [{'id': 'S01', 'start_sample': 0, 'end_sample': -1}, {'id': 'S02', 'start_sample': -1, 'end_sample': 24001}],
            [{'id': 'S01', 'start_sample': False, 'end_sample': 24001}],
            [{'id': 'S01', 'start_sample': 0, 'end_sample': 1}, {'id': 'S02', 'start_sample': 1, 'end_sample': 2}, {'id': 'S03', 'start_sample': 2, 'end_sample': 24001}],
        ]
        for rows in invalid:
            with self.subTest(rows=rows):
                scenes = self.root / 'scenes.json'
                scenes.write_text(json.dumps({'source_sha256': data['source_sha256'], 'scenes': rows}))
                self.assertEqual(self.run_cli('check', timing, scenes).returncode, 2)

    def test_requires_track_selection_for_multiple_audio_streams(self):
        multi = self.root / 'multiple.mka'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.audio),
                        '-map', '0:a:0', '-map', '0:a:0', '-c:a', 'copy', str(multi)], check=True)
        self.assertEqual(self.run_cli('probe', multi).returncode, 2)
        selected = self.run_cli('probe', multi, '--audio-stream', '1')
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(json.loads(selected.stdout)['decoded_samples'], 24001)

    def test_rejects_audio_replaced_after_measurement(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio).stdout)
        data = json.loads(timing.read_text())
        scenes = self.root / 'scenes.json'
        scenes.write_text(json.dumps({'source_sha256': data['source_sha256'], 'scenes': [
            {'id': 'S01', 'start_sample': 0, 'end_sample': 24001}
        ]}))
        original = self.audio.read_bytes()
        self.audio.write_bytes(original[:-2] + b'\x01\x00')
        self.assertEqual(self.run_cli('check', timing, scenes).returncode, 2)

    def test_rejects_duplicate_scene_ids(self):
        timing = self.root / 'timing.json'
        timing.write_text(self.run_cli('probe', self.audio).stdout)
        data = json.loads(timing.read_text())
        scenes = self.root / 'scenes.json'
        scenes.write_text(json.dumps({'source_sha256': data['source_sha256'], 'scenes': [
            {'id': 'S01', 'start_sample': 0, 'end_sample': 8000},
            {'id': 'S01', 'start_sample': 8000, 'end_sample': 24001}
        ]}))
        self.assertEqual(self.run_cli('check', timing, scenes).returncode, 2)

if __name__ == '__main__':
    unittest.main()
