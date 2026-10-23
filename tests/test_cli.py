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
    def test_version_comes_from_installed_package_metadata(self):
        stdout = io.StringIO()
        with (
            patch("book2audio.cli.package_version", return_value="9.8.7"),
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            build_parser().parse_args(["--version"])

        self.assertEqual(0, raised.exception.code)
        self.assertEqual("voicebook-tool 9.8.7\n", stdout.getvalue())

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
        fake_script = type(
            "Result",
            (),
            {"chapters": [1, 2], "characters": ["旁白", "甲"], "quality_report": {"version": 1}},
        )()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "book.script"
            with patch("book2audio.cli.inspect_book", return_value=fake_script) as inspect, redirect_stdout(stdout):
                status = main(["inspect", "book.txt", "-o", str(output)])
        self.assertEqual(0, status)
        self.assertIn("2 章，1 个角色", stdout.getvalue())
        inspect.assert_called_once()

    def test_machine_inspect_emits_quality_report(self):
        stdout = io.StringIO()
        report = {"version": 1, "segments_before": 1, "segments_after": 2}
        fake_script = type(
            "Result",
            (),
            {"chapters": [1], "characters": ["旁白"], "quality_report": report},
        )()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "book.script"
            with patch("book2audio.cli.inspect_book", return_value=fake_script), redirect_stdout(stdout):
                status = main(["inspect", "book.txt", "-o", str(output), "--progress-format", "jsonl"])

        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(0, status)
        self.assertEqual(report, events[-1]["normalization"])

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

    def test_v2_identity_and_generation_limits_are_forwarded(self):
        for command, source in (("generate", "book.script"), ("convert", "book.txt")):
            with (
                self.subTest(command=command),
                tempfile.TemporaryDirectory() as directory,
            ):
                stdout = io.StringIO()
                with (
                    patch(
                        f"book2audio.cli.{command}_audio" if command == "generate" else "book2audio.cli.convert_book",
                        return_value=[],
                    ) as generate,
                    redirect_stdout(stdout),
                ):
                    status = main(
                        [
                            command,
                            source,
                            "-o",
                            directory,
                            "--progress-format",
                            "jsonl",
                            "--progress-version",
                            "2",
                            "--task-id",
                            "job-123",
                            "--attempt-id",
                            "try-456",
                            "--concurrency",
                            "1",
                            "--max-retries",
                            "0",
                            "--retry-backoff",
                            "0.5",
                        ]
                    )
                self.assertEqual(0, status)
                options = generate.call_args.kwargs
                self.assertEqual(
                    (1, 0, 0.5),
                    (
                        options["concurrency"],
                        options["max_retries"],
                        options["retry_backoff"],
                    ),
                )
                emitter = options["progress"]
                self.assertEqual(
                    (2, "job-123", "try-456"),
                    (emitter.version, emitter.task_id, emitter.attempt_id),
                )
                self.assertEqual("", stdout.getvalue())

    def test_human_mode_preserves_identity_for_persisted_progress(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            redirect_stdout(io.StringIO()),
            patch("book2audio.cli.generate_audio", return_value=[]) as generate,
        ):
            self.assertEqual(
                0,
                main(["generate", "book.script", "-o", directory, "--task-id", "job-123"]),
            )
            emitter = generate.call_args.kwargs["progress"]
            self.assertEqual("job-123", emitter.task_id)
            self.assertIsNone(emitter.stream)


if __name__ == "__main__":
    unittest.main()
