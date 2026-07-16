import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from book2audio.audio import smooth_pcm16_wav_edges
from book2audio.pipeline import synth_chapter_qwen


SAMPLE_RATE = 24_000
SEGMENT_FRAMES = 2_400
CLICK_INDEX = 21


def write_qwen_click_fixture(path: Path) -> None:
    """Write the repeatable near-full-scale start transient seen in real Qwen WAVs."""
    samples = array("h", [0]) * SEGMENT_FRAMES
    samples[0] = 18_770
    samples[CLICK_INDEX - 1] = -101
    samples[CLICK_INDEX] = 32_767
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())


def read_samples(path: Path) -> array:
    with wave.open(str(path), "rb") as wav:
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
        return samples


class FakeQwenEngine:
    async def synth(self, _text, _spec, out_path):
        write_qwen_click_fixture(out_path)


class PCM16WaveEdgeTests(unittest.TestCase):
    def test_smoothing_preserves_format_and_frames_while_suppressing_start_click(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "click.wav"
            write_qwen_click_fixture(path)
            smooth_pcm16_wav_edges(path)
            with wave.open(str(path), "rb") as wav:
                self.assertEqual((1, 2, SAMPLE_RATE, SEGMENT_FRAMES), (
                    wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()))
            samples = read_samples(path)

        largest_start_jump = max(
            abs(samples[index] - samples[index - 1])
            for index in range(1, SAMPLE_RATE // 100)
        )
        self.assertEqual(0, samples[0])
        self.assertEqual(0, samples[-1])
        self.assertLess(largest_start_jump, 5_000)


class QwenAudioBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_chapter_synthesis_suppresses_qwen_start_click_at_every_segment(self):
        parts = [("第一段", ("Cherry",)), ("第二段", ("Andre",))]
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            with patch("book2audio.tts.Qwen3TTSAIEngine", FakeQwenEngine):
                chapter = await synth_chapter_qwen(parts, work_dir, 1)
            samples = read_samples(chapter)

        search_frames = SAMPLE_RATE // 100
        for start in (0, SEGMENT_FRAMES):
            first = max(1, start)
            largest_jump = max(
                abs(samples[index] - samples[index - 1])
                for index in range(first, start + search_frames)
            )
            self.assertLess(
                largest_jump,
                5_000,
                f"segment at frame {start} retains a click-sized jump: {largest_jump}",
            )


if __name__ == "__main__":
    unittest.main()
