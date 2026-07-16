import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from book2audio.audio import smooth_pcm16_wav_edges
from book2audio.pipeline import (
    QWEN_CHAPTER_END_PAUSE_MS,
    QWEN_SEGMENT_PAUSE_MS,
    QWEN_TITLE_PAUSE_MS,
    synth_chapter_qwen,
)


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
    async def test_chapter_synthesis_suppresses_clicks_and_inserts_logical_pauses(self):
        self.assertEqual(900, QWEN_TITLE_PAUSE_MS)
        parts = [
            ("标题", ("Cherry", 1.0)),
            ("第二段", ("Andre", 1.0)),
            ("第三段", ("Neil", 1.0)),
        ]
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            with patch("book2audio.tts.Qwen3TTSAIEngine", FakeQwenEngine):
                chapter = await synth_chapter_qwen(parts, work_dir, 1)
            samples = read_samples(chapter)

        title_pause_frames = round(SAMPLE_RATE * QWEN_TITLE_PAUSE_MS / 1000)
        segment_pause_frames = round(SAMPLE_RATE * QWEN_SEGMENT_PAUSE_MS / 1000)
        chapter_pause_frames = round(SAMPLE_RATE * QWEN_CHAPTER_END_PAUSE_MS / 1000)
        starts = (
            0,
            SEGMENT_FRAMES + title_pause_frames,
            SEGMENT_FRAMES * 2 + title_pause_frames + segment_pause_frames,
        )
        self.assertEqual(
            SEGMENT_FRAMES * 3 + title_pause_frames + segment_pause_frames + chapter_pause_frames,
            len(samples),
        )
        self.assertFalse(any(samples[SEGMENT_FRAMES:starts[1]]))
        self.assertFalse(any(samples[starts[1] + SEGMENT_FRAMES:starts[2]]))
        self.assertFalse(any(samples[starts[2] + SEGMENT_FRAMES:]))

        search_frames = SAMPLE_RATE // 100
        for start in starts:
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

    async def test_api_chunks_inside_one_logical_part_do_not_gain_extra_pause(self):
        parts = [("长标题", ("Cherry", 1.0)), ("对白", ("Andre", 1.0))]

        def split_into_test_chunks(text):
            return ["第一块", "第二块"] if text == "长标题" else [text]

        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            with (
                patch("book2audio.tts.Qwen3TTSAIEngine", FakeQwenEngine),
                patch("book2audio.tts.split_tts_text", side_effect=split_into_test_chunks),
            ):
                chapter = await synth_chapter_qwen(parts, work_dir, 1)
            samples = read_samples(chapter)

        title_pause_frames = round(SAMPLE_RATE * QWEN_TITLE_PAUSE_MS / 1000)
        chapter_pause_frames = round(SAMPLE_RATE * QWEN_CHAPTER_END_PAUSE_MS / 1000)
        self.assertEqual(
            SEGMENT_FRAMES * 3 + title_pause_frames + chapter_pause_frames,
            len(samples),
        )


if __name__ == "__main__":
    unittest.main()
