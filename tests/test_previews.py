import unittest

from book2audio.previews import PREVIEW_SCENES, preview_catalog


class PreviewCatalogTests(unittest.TestCase):
    def test_catalog_exposes_all_57_voices_and_ten_scenes(self):
        catalog = preview_catalog()

        self.assertEqual(("voicebook-voice-catalog", 1), (catalog["format"], catalog["version"]))
        self.assertEqual(57, len(catalog["voices"]))
        self.assertEqual(10, len(PREVIEW_SCENES))
        self.assertEqual(10, len(catalog["scene_definitions"]))
        self.assertEqual({"edgetts", "qwen3tts"}, {item["engine"] for item in catalog["voices"]})


if __name__ == "__main__":
    unittest.main()
