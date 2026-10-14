from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import tomllib


def test_dynamic_version_and_flat_layout():
    root = Path(__file__).parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools_scm"]["version_file"] == "voicefolio/_version.py"
    assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["."]
    assert (
        "resources/catalogs/*.json" in data["tool"]["setuptools"]["package-data"]["voicefolio"]
    )
    assert (
        "resources/sources/*.json" in data["tool"]["setuptools"]["package-data"]["voicefolio"]
    )
    assert not any(
        "resources/web/" in item
        for item in data["tool"]["setuptools"]["package-data"]["voicefolio"]
    )
    assert not (root / "src").exists()


def test_built_wheel_and_sdist_include_complete_catalog(tmp_path: Path):
    root = Path(__file__).parents[1]
    catalog = root / "voicefolio/resources/catalogs/kyutai-tts-voices.json"
    license_policy = root / "voicefolio/resources/sources/kyutai-tts-voices-licenses.json"
    shutil.rmtree(root / "build", ignore_errors=True)
    (root / "voicefolio.egg-info" / "SOURCES.txt").unlink(missing_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(tmp_path),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        member = "voicefolio/resources/catalogs/kyutai-tts-voices.json"
        assert member in archive.namelist()
        assert archive.read(member) == catalog.read_bytes()
        policy_member = "voicefolio/resources/sources/kyutai-tts-voices-licenses.json"
        assert policy_member in archive.namelist()
        assert archive.read(policy_member) == license_policy.read_bytes()
        assert "voicefolio/py.typed" in archive.namelist()
        metadata_member = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_member).decode("utf-8")
        requirements = [
            line for line in metadata.splitlines() if line.startswith("Requires-Dist:")
        ]
        assert not any(line.startswith("Requires-Dist: numpy") for line in requirements)
        for dependency in ("sounddevice", "soundfile"):
            declarations = [
                line for line in requirements if line.startswith(f"Requires-Dist: {dependency}")
            ]
            assert len(declarations) == 1
            assert 'extra == "playback"' in declarations[0]
        assert "voicefolio/resources/web/index.html" not in archive.namelist()

    sdist = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        member = next(
            name
            for name in archive.getnames()
            if name.endswith("/voicefolio/resources/catalogs/kyutai-tts-voices.json")
        )
        source = archive.extractfile(member)
        assert source is not None
        assert source.read() == catalog.read_bytes()
        policy_member = next(
            name
            for name in archive.getnames()
            if name.endswith("/voicefolio/resources/sources/kyutai-tts-voices-licenses.json")
        )
        policy = archive.extractfile(policy_member)
        assert policy is not None
        assert policy.read() == license_policy.read_bytes()
        assert any(name.endswith("/voicefolio/py.typed") for name in archive.getnames())
        assert not any(
            name.endswith("/voicefolio/resources/web/index.html") for name in archive.getnames()
        )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(wheel)
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from voicefolio import Catalog; "
                "catalog = Catalog.builtin(); "
                "assert len(catalog.list(namespace='kyutai-tts-voices')) == 1161; "
                "print('wheel catalog:', len(catalog))"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert smoke.stdout.strip() == "wheel catalog: 1161"
