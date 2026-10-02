import shutil
import tempfile
import unittest
import wave
from pathlib import Path

from concurrency_20261003.audio_markers import (
    SAMPLE_RATE,
    marker_pcm,
    validate_audio_content,
)


@unittest.skipUnless(shutil.which("ffmpeg"), "需要 ffmpeg")
class AudioContentTests(unittest.TestCase):
    def check_content(self, actual, expected, *, silence=True):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sequence.wav"
            with wave.open(str(audio), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                for label in actual:
                    wav.writeframes(marker_pcm(label))
                    if silence:
                        wav.writeframes(b"\x00\x00" * (SAMPLE_RATE // 10))
            return validate_audio_content(audio, expected)

    def test_detector_accepts_ordered_content(self):
        labels = ["标题1", "章1段0", "章1段1"]
        self.assertEqual(labels, self.check_content(labels, labels)["observed"])

    def test_detector_rejects_reordered_content(self):
        with self.assertRaises(AssertionError):
            self.check_content(
                ["标题1", "章1段1", "章1段0"], ["标题1", "章1段0", "章1段1"]
            )

    def test_detector_rejects_missing_content(self):
        with self.assertRaises(AssertionError):
            self.check_content(["标题1", "章1段0"], ["标题1", "章1段0", "章1段1"])

    def test_detector_rejects_duplicate_occurrence(self):
        with self.assertRaises(AssertionError):
            self.check_content(["标题1", "章1段0", "章1段0"], ["标题1", "章1段0"])

    def test_detector_rejects_consecutive_duplicate_without_silence(self):
        with self.assertRaises(AssertionError):
            self.check_content(["章1段0", "章1段0"], ["章1段0"], silence=False)


if __name__ == "__main__":
    unittest.main()
