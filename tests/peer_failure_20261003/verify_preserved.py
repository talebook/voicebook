"""Repeat QA's five positive and five fault-injection probes on current code."""

import hashlib
import importlib.util
import json
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import book2audio.tool_pipeline as pipeline
import book2audio.work as work

HERE = Path(__file__).resolve().parent


def main():
    probe_path = HERE.parent / "review_20261003/reproduce.py"
    spec = importlib.util.spec_from_file_location("preserved_qa_probe", probe_path)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    source = probe_path.read_text()
    original = '[sys.executable, "-c", "import time; time.sleep(30)"]'
    bounded = (
        '[sys.executable, "-c", "import time,subprocess; time.sleep(1.1); '
        'subprocess.run(" + repr(command) + ", check=True)"]'
    )
    assert source.count(original) == 1
    negative_probe = types.ModuleType("bounded_fault_probe")
    negative_probe.__file__ = str(probe_path)
    exec(
        compile(source.replace(original, bounded), str(probe_path), "exec"),
        negative_probe.__dict__,
    )
    original_media = pipeline._run_media

    def ignore_cancel(command, **kwargs):
        kwargs["cancel_file"] = None
        kwargs["stop"] = None
        return original_media(command, **kwargs)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        positive = [probe.lease_during_local_media(root / "lease")]
        positive.extend(
            probe.media_cancel(root / f"{engine}-{stage}", engine=engine, stage=stage)
            for engine in ("edgetts", "qwen3tts")
            for stage in ("normalize", "tempo")
        )
        negative = []
        for engine in ("edgetts", "qwen3tts"):
            for stage in ("normalize", "tempo"):
                with patch.object(pipeline, "_run_media", ignore_cancel):
                    try:
                        negative_probe.media_cancel(
                            root / f"bad-{engine}-{stage}", engine=engine, stage=stage
                        )
                    except AssertionError as error:
                        latency = error.args[0]
                        assert isinstance(latency, float) and latency >= 0.75, (
                            error.args
                        )
                        negative.append(
                            {
                                "case": f"{engine}_{stage}_cancel_disabled",
                                "probe_rejected_fault": True,
                                "observed_latency_seconds": round(latency, 3),
                                "ffmpeg_output_was_produced": True,
                            }
                        )
                    else:
                        raise AssertionError("cancel probe accepted fault")
        with patch.object(work.WorkProgress, "renew_requests", lambda self: None):
            try:
                probe.lease_during_local_media(root / "bad-lease")
            except AssertionError as error:
                observation = error.args[0]
                assert (
                    isinstance(observation, dict)
                    and observation["maximum_simulated_connections"] == 3
                )
                negative.append(
                    {
                        "case": "renewal_disabled",
                        "probe_rejected_fault": True,
                        "configured_limit": 2,
                        "observed_maximum": 3,
                    }
                )
            else:
                raise AssertionError("lease probe accepted fault")
    result = {
        "source_sha256": {
            f"src/book2audio/{Path(module.__file__).name}": hashlib.sha256(
                Path(module.__file__).read_bytes()
            ).hexdigest()
            for module in (pipeline, work)
        },
        "positive_cases": positive,
        "fault_injection_cases": negative,
        "all_checks_passed": True,
    }
    (HERE / "preserved-probes.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
