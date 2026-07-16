import tempfile
import unittest
from pathlib import Path

from book2audio.casting import (
    CharacterProfile,
    QWEN_SYSTEM_VOICES,
    assign_qwen_voices,
    build_profiles,
)
from book2audio.tts import QwenTTSClient, split_tts_text


FAKE_WAV = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + bytes(32)


class FakeResponse:
    def __init__(self, status_code=200, content=FAKE_WAV, headers=None, text=""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "audio/wav"}
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class QwenVoiceCastingTests(unittest.TestCase):
    def test_novel_titles_drive_profiles_before_qwen_casting(self):
        text = (
            "养魂炉里的老道残魂发出一阵怪笑。老道沙哑地说道：小子，你且听好。\n"
            "青年男子韩立沉声回答：前辈请讲。母亲在旁边柔声安慰孩子。"
        )

        profiles = build_profiles(text, {"老道", "韩立", "母亲"})
        voices = {name: spec[0] for name, spec in assign_qwen_voices(profiles).items()}

        self.assertEqual(("male", "老年"), (profiles["老道"].gender, profiles["老道"].age_stage))
        self.assertEqual("female", profiles["母亲"].gender)
        self.assertIn(voices["老道"], {"Arthur", "Eldric Sage", "Vincent"})
        self.assertIn(voices["母亲"], {"Serena", "Cherry", "Maia", "Katerina", "Bellona"})

    def test_roles_get_age_gender_and_description_appropriate_voices(self):
        profiles = {
            "小童": CharacterProfile("小童", gender="male", age_stage="童年"),
            "老者": CharacterProfile("老者", gender="male", age_stage="老年"),
            "烟嗓叔": CharacterProfile(
                "烟嗓叔", gender="male", age_stage="中年", voice_desc=["沙哑"]),
            "少女甲": CharacterProfile("少女甲", gender="female", age_stage="少年"),
            "少女乙": CharacterProfile("少女乙", gender="female", age_stage="少年"),
            "老婆婆": CharacterProfile("老婆婆", gender="female", age_stage="老年"),
        }

        voices = {name: spec[0] for name, spec in assign_qwen_voices(profiles).items()}

        self.assertEqual("Pip", voices["小童"])
        self.assertEqual("Eldric Sage", voices["老者"])
        self.assertEqual("Vincent", voices["烟嗓叔"])
        self.assertEqual("Ebona", voices["老婆婆"])
        self.assertNotEqual(voices["少女甲"], voices["少女乙"])
        self.assertTrue(set(voices.values()).issubset(QWEN_SYSTEM_VOICES))


class QwenTTSClientTests(unittest.TestCase):
    def test_client_sends_observed_payload_and_writes_wav(self):
        session = FakeSession([FakeResponse()])
        client = QwenTTSClient(session=session)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.wav"
            result = client.synth_to_file("你好", "Cherry", output)

            self.assertEqual(output, result)
            self.assertEqual(FAKE_WAV, output.read_bytes())
        url, kwargs = session.calls[0]
        self.assertEqual("https://qwen3ttsai.com/api/qwen3tts/generate", url)
        self.assertEqual({"text": "你好", "voice": "Cherry", "mode": "system"}, kwargs["json"])
        self.assertEqual(60.0, kwargs["timeout"])

    def test_client_retries_rate_limit_then_returns_audio(self):
        session = FakeSession([
            FakeResponse(429, b"", {"content-type": "application/json", "retry-after": "0"}, "busy"),
            FakeResponse(),
        ])
        delays = []
        client = QwenTTSClient(session=session, sleeper=delays.append)

        self.assertEqual(FAKE_WAV, client.generate("重试", "Andre"))
        self.assertEqual(2, len(session.calls))
        self.assertEqual([0.0], delays)

    def test_long_novel_text_is_split_without_exceeding_api_limit(self):
        text = "甲" * 700 + "。" + "乙" * 700

        chunks = split_tts_text(text)

        self.assertEqual(text, "".join(chunks))
        self.assertTrue(all(0 < len(chunk) <= 1000 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
