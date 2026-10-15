"""Smoke-test a Voicefolio wheel from an isolated working directory, offline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SystemExit(
            f"smoke command failed: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel", type=Path, help="wheel file; defaults to the only wheel in --artifacts"
    )
    parser.add_argument("--artifacts", type=Path, default=Path("dist"))
    args = parser.parse_args()
    if args.wheel is not None:
        wheel = args.wheel.resolve()
    else:
        wheels = sorted(args.artifacts.glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"expected exactly one wheel in {args.artifacts}, found {wheels}")
        wheel = wheels[0].resolve()
    if not wheel.is_file():
        raise SystemExit(f"wheel does not exist: {wheel}")

    with tempfile.TemporaryDirectory(prefix="voicefolio-wheel-smoke-") as directory:
        temp = Path(directory)
        environment = temp / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        executable = scripts / ("voicefolio.exe" if os.name == "nt" else "voicefolio")
        cwd = temp / "outside-checkout"
        cwd.mkdir()
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["VOICEFOLIO_CACHE_DIR"] = str(temp / "user-cache")

        _run(
            [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
            cwd=cwd,
            env=env,
        )
        _run(
            [
                str(python),
                "-c",
                (
                    "from pathlib import Path; import sys, voicefolio; "
                    "path = Path(voicefolio.__file__).resolve(); "
                    "assert Path(sys.prefix).resolve() in path.parents, path; "
                    "from voicefolio.catalog import Catalog; "
                    "catalog = Catalog.builtin(); "
                    "assert all(catalog.list(namespace=name) for name in "
                    "('kyutai-tts-voices', 'fine-read-it-voices', 'voice-zero')); "
                    "print('installed package:', path, 'voices:', len(catalog))"
                ),
            ],
            cwd=cwd,
            env=env,
        )
        _run([str(executable), "--version"], cwd=cwd, env=env)
        _run([str(executable), "--help"], cwd=cwd, env=env)
        for namespace in ("kyutai-tts-voices", "fine-read-it-voices", "voice-zero"):
            listing = _run(
                [str(executable), "list", "--namespace", namespace, "--json"],
                cwd=cwd,
                env=env,
            )
            rows = json.loads(listing.stdout)
            if not rows:
                raise SystemExit(f"installed catalog namespace is empty: {namespace}")
        _run(
            [str(executable), "show", "kyutai-tts-voices:voice-donations/0a67"],
            cwd=cwd,
            env=env,
        )
        _run(
            [str(executable), "show", "fine-read-it-voices:F002"],
            cwd=cwd,
            env=env,
        )
        _run(
            [
                str(executable),
                "binding",
                "fine-read-it-voices:F002",
                "--json",
            ],
            cwd=cwd,
            env=env,
        )
        _run([str(executable), "validate"], cwd=cwd, env=env)

        payload = b"offline wheel smoke fixture"
        cache_dir = temp / "fixture-cache"
        catalog_path = temp / "fixture-catalog.json"
        output_path = temp / "fixture-export.wav"
        fixture_code = r"""
import hashlib, json, sys
from pathlib import Path
from voicefolio.cache import asset_path
from voicefolio.models import VoiceEntry, VoiceRef
payload = b"offline wheel smoke fixture"
digest = hashlib.sha256(payload).hexdigest()
entry = VoiceEntry(
    ref=VoiceRef("smoke", "fixture"), dataset="smoke", variant="original",
    format="wav", url="https://example.invalid/fixture.wav", size=len(payload),
    sha256=digest, source_repository="local/fixture", source_revision="a" * 40,
    source_path="fixture.wav", license="CC0-1.0", language="en",
)
cache = Path(sys.argv[1])
path = asset_path(entry, cache)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(payload)
catalog = {"schema": 1, "kind": "voicefolio-catalog", "namespace": "smoke", "voices": [entry.to_dict()]}
Path(sys.argv[2]).write_text(json.dumps(catalog), encoding="utf-8")
"""
        _run(
            [str(python), "-c", fixture_code, str(cache_dir), str(catalog_path)],
            cwd=cwd,
            env=env,
        )
        fixture_ref = "smoke:fixture"
        common = ["--catalog", str(catalog_path), "--cache-dir", str(cache_dir), "--offline"]
        _run([str(executable), "fetch", fixture_ref, *common], cwd=cwd, env=env)
        _run(
            [
                str(executable),
                "export",
                fixture_ref,
                "--output",
                str(output_path),
                *common,
            ],
            cwd=cwd,
            env=env,
        )
        if output_path.read_bytes() != payload:
            raise SystemExit("offline installed-wheel export changed pinned source bytes")

    print(f"installed-wheel smoke OK: {wheel.name}")


if __name__ == "__main__":
    main()
