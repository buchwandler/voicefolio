from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    import tomli as tomllib


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
    assert "resources/web/*.html" in data["tool"]["setuptools"]["package-data"]["voicefolio"]
    assert not (root / "src").exists()


def test_built_wheel_and_sdist_include_complete_catalog(tmp_path: Path):
    root = Path(__file__).parents[1]
    catalog = root / "voicefolio/resources/catalogs/kyutai-tts-voices.json"
    license_policy = root / "voicefolio/resources/sources/kyutai-tts-voices-licenses.json"
    browser_page = root / "voicefolio/resources/web/index.html"
    language_policy = root / "voicefolio/resources/sources/kyutai-tts-voices-languages.json"
    shutil.rmtree(root / "build", ignore_errors=True)
    (root / "voicefolio.egg-info" / "SOURCES.txt").unlink(missing_ok=True)
    result = subprocess.run(
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
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        pytest.fail(f"package build failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        member = "voicefolio/resources/catalogs/kyutai-tts-voices.json"
        assert member in archive.namelist()
        assert archive.read(member) == catalog.read_bytes()
        policy_member = "voicefolio/resources/sources/kyutai-tts-voices-licenses.json"
        assert policy_member in archive.namelist()
        assert archive.read(policy_member) == license_policy.read_bytes()
        language_member = "voicefolio/resources/sources/kyutai-tts-voices-languages.json"
        assert language_member in archive.namelist()
        assert archive.read(language_member) == language_policy.read_bytes()
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
        browser_member = "voicefolio/resources/web/index.html"
        assert browser_member in archive.namelist()
        assert archive.read(browser_member) == browser_page.read_bytes()

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
        language_policy_member = next(
            name
            for name in archive.getnames()
            if name.endswith("/voicefolio/resources/sources/kyutai-tts-voices-languages.json")
        )
        language_policy_source = archive.extractfile(language_policy_member)
        assert language_policy_source is not None
        assert language_policy_source.read() == language_policy.read_bytes()
        assert any(name.endswith("/voicefolio/py.typed") for name in archive.getnames())
        browser_member = next(
            name
            for name in archive.getnames()
            if name.endswith("/voicefolio/resources/web/index.html")
        )
        browser_source = archive.extractfile(browser_member)
        assert browser_source is not None
        assert browser_source.read() == browser_page.read_bytes()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(wheel)
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from voicefolio import Catalog; "
                "catalog = Catalog.builtin(); "
                "from importlib.resources import files; "
                "page = files('voicefolio').joinpath('resources').joinpath('web').joinpath('index.html').read_text(); "
                "assert 'Language' in page and 'api/languages' in page; "
                "entry = catalog.get('kyutai-tts-voices:voice-donations/0a67'); "
                "assert entry.sha256 == '4bd75d0ef0ad3f4e82ac075eab2a132651d2463f83bec210edeeccaf69294886'; "
                "print('wheel catalog:', len(catalog))"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    expected_count = len(json.loads(catalog.read_text(encoding="utf-8"))["voices"])
    assert smoke.stdout.strip() == f"wheel catalog: {expected_count}"
