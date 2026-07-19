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

    def test_all_edge_voices_ship_ten_scene_previews(self):
        voices = preview_catalog("edgetts")["voices"]

        self.assertEqual(8, len(voices))
        self.assertTrue(all(item["preview_available"] for item in voices))
        self.assertTrue(all(len(item["preview_scenes"]) == 10 for item in voices))


if __name__ == "__main__":
    unittest.main()
