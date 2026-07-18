import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from book2audio.cli import build_parser, main
from book2audio.machine import GenerationCancelled


class CliTests(unittest.TestCase):
    def test_generate_and_convert_default_to_edgetts(self):
        parser = build_parser()
        generate = parser.parse_args(["generate", "book.script", "-o", "output"])
        convert = parser.parse_args(["convert", "book.epub", "-o", "output"])

        self.assertEqual("edgetts", generate.engine)
        self.assertEqual("edgetts", convert.engine)

    def test_qwen_service_reason_is_reported_without_fallback(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("book2audio.cli.generate_audio", side_effect=RuntimeError("Qwen HTTP 500: Arrearage")) as generate,
                redirect_stderr(stderr),
            ):
                status = main(["generate", "book.script", "-o", directory, "--engine", "qwen3tts"])

        self.assertEqual(1, status)
        self.assertIn("Arrearage", stderr.getvalue())
        generate.assert_called_once()
        self.assertEqual("qwen3tts", generate.call_args.kwargs["engine"])

    def test_inspect_reports_result(self):
        stdout = io.StringIO()
        fake_script = type("Result", (), {"chapters": [1, 2], "characters": ["旁白", "甲"]})()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "book.script"
            with patch("book2audio.cli.inspect_book", return_value=fake_script) as inspect, redirect_stdout(stdout):
                status = main(["inspect", "book.txt", "-o", str(output)])
        self.assertEqual(0, status)
        self.assertIn("2 章，1 个角色", stdout.getvalue())
        inspect.assert_called_once()

    def test_machine_mode_emits_jsonl_and_uses_cancel_exit_code(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("book2audio.cli.generate_audio", side_effect=GenerationCancelled("cancelled")),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                status = main(
                    [
                        "generate",
                        "book.script",
                        "-o",
                        directory,
                        "--progress-format",
                        "jsonl",
                        "--resume",
                    ]
                )

        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(3, status)
        self.assertEqual("cancelled", events[-1]["event"])
        self.assertEqual("voicebook-progress.v1", events[-1]["schema"])
        self.assertNotIn("提示", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
