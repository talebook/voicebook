import unittest

from book2audio.attribution import Attributor, clean_name_candidate


class ClassicalAttributionTests(unittest.TestCase):
    def test_speaker_action_suffix_is_not_part_of_name(self):
        self.assertEqual("悟空", clean_name_candidate("悟空應聲"))
        self.assertEqual("祖師", clean_name_candidate("祖師又笑"))
        self.assertEqual("雨村", clean_name_candidate("雨村忙笑"))
        self.assertEqual("封肅", clean_name_candidate("封肅忙陪笑"))
        self.assertEqual("道人", clean_name_candidate("只聽道人問"))
        self.assertEqual("王冕", clean_name_candidate("王冕心裡想"))
        self.assertEqual("孫悟空", clean_name_candidate("孫悟空在傍"))

    def test_traditional_transition_words_do_not_become_characters(self):
        text = (
            "孫悟空笑道：「師父放心。」孫悟空又道：「我去也。」\n"
            "祖師又笑道：「你這猢猻。」祖師道：「且退下。」\n"
            "且聽下回分解。甚麼人在此高叫？"
        )
        attributor = Attributor()
        attributor.build_names(text)
        self.assertIn("孫悟空", attributor.names)
        self.assertIn("祖師", attributor.names)
        self.assertNotIn("悟空笑", attributor.names)
        self.assertNotIn("祖師又", attributor.names)
        self.assertNotIn("且聽下", attributor.names)
        self.assertNotIn("甚麼", attributor.names)

    def test_exact_character_beats_longer_noisy_candidate(self):
        attributor = Attributor(names={"王冕", "向王冕", "孫悟空", "孫悟空在傍"})
        self.assertEqual("王冕", attributor.to_name("王冕"))
        self.assertEqual("孫悟空", attributor.to_name("孫悟空"))

    def test_high_frequency_traditional_name_survives_noisy_extensions(self):
        text = "\n".join([
            "王冕心裡想道：「我當讀書。」",
            "王冕說道：「我去放牛。」",
            "王冕笑道：「不妨事。」",
            "王冕屈身行禮。",
        ] * 3)
        attributor = Attributor()
        attributor.build_names(text)
        self.assertIn("王冕", attributor.names)


if __name__ == "__main__":
    unittest.main()
