"""Validate built Voicefolio wheel/sdist contents and rebuildability."""

from __future__ import annotations

import argparse
import email.policy
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voicefolio.catalog import Catalog
from voicefolio.sources.registry import verify_maintained_catalog

CATALOGS = {
    "kyutai-tts-voices": "voicefolio/resources/catalogs/kyutai-tts-voices.json",
    "fine-read-it-voices": "voicefolio/resources/catalogs/fine-read-it-voices.json",
    "voice-zero": "voicefolio/resources/catalogs/voice-zero.json",
}
SOURCE_POLICIES = (
    "voicefolio/resources/sources/kyutai-tts-voices-licenses.json",
    "voicefolio/resources/sources/kyutai-tts-voices-languages.json",
    "voicefolio/resources/sources/voice-zero-overrides.json",
)
WEB_RESOURCE = "voicefolio/resources/web/index.html"
TYPING_MARKER = "voicefolio/py.typed"


def _fail(message: str) -> None:
    raise SystemExit(f"artifact check failed: {message}")


def _read_metadata(archive: zipfile.ZipFile) -> tuple[str, str]:
    names = archive.namelist()
    metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
    if len(metadata_names) != 1:
        _fail(f"expected one wheel METADATA file, found {metadata_names}")
    metadata = BytesParser(policy=email.policy.default).parsebytes(
        archive.read(metadata_names[0])
    )
    package_name = metadata.get("Name", "")
    version = metadata.get("Version", "")
    if package_name.casefold().replace("_", "-") != "voicefolio":
        _fail(f"wheel metadata names unexpected package {package_name!r}")
    if not version:
        _fail("wheel metadata has no Version")
    requirements = metadata.get_all("Requires-Dist", [])
    if not any(
        re.match(r"^typer(?:\s|[<>=!~;\[])", value, flags=re.IGNORECASE)
        for value in requirements
    ):
        _fail("wheel runtime metadata does not declare Typer")
    return package_name, version


def _verify_wheel(wheel: Path, expected_version: str | None) -> str:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        package_name, version = _read_metadata(archive)
        expected = {
            TYPING_MARKER,
            WEB_RESOURCE,
            *CATALOGS.values(),
            *SOURCE_POLICIES,
        }
        missing = sorted(expected - names)
        if missing:
            _fail(f"wheel is missing required package data: {missing}")
        if not wheel.name.startswith(f"voicefolio-{version}-"):
            _fail(f"wheel filename {wheel.name!r} disagrees with metadata version {version!r}")
        if expected_version is not None and version != expected_version:
            _fail(f"wheel version {version!r} does not match expected {expected_version!r}")

        for resource in (*CATALOGS.values(), *SOURCE_POLICIES):
            checkout_resource = ROOT / resource
            if not checkout_resource.is_file():
                _fail(f"required checkout resource is missing: {checkout_resource}")
            if archive.read(resource) != checkout_resource.read_bytes():
                _fail(f"wheel resource differs from checkout: {resource}")

        with tempfile.TemporaryDirectory(prefix="voicefolio-artifacts-") as directory:
            temp = Path(directory)
            for namespace, resource in CATALOGS.items():
                payload = json.loads(archive.read(resource))
                if not isinstance(payload, dict) or payload.get("namespace") != namespace:
                    _fail(f"invalid packaged catalog namespace in {resource}")
                catalog_path = temp / Path(resource).name
                catalog_path.write_bytes(archive.read(resource))
                parsed = Catalog.from_paths([catalog_path])
                if not parsed:
                    _fail(f"packaged catalog has no voice rows: {resource}")
                verify_maintained_catalog(payload)
            for resource in SOURCE_POLICIES:
                payload = json.loads(archive.read(resource))
                if not isinstance(payload, dict) or not payload:
                    _fail(f"source policy is empty or malformed: {resource}")
            page = archive.read(WEB_RESOURCE).decode("utf-8")
            if "<html" not in page.casefold() or "api/voices" not in page:
                _fail("packaged browser resource is empty or incomplete")

    print(f"wheel OK: {wheel.name} ({package_name} {version})")
    return version


def _safe_extract_sdist(sdist: Path, destination: Path) -> Path:
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        roots = {
            PurePosixPath(member.name).parts[0]
            for member in members
            if PurePosixPath(member.name).name == "pyproject.toml"
        }
        if len(roots) != 1:
            _fail(f"sdist must contain one project root, found {sorted(roots)}")
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                _fail(f"unsafe path in sdist: {member.name!r}")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    _fail(f"cannot read sdist member {member.name!r}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            else:
                _fail(f"unsupported non-regular sdist member: {member.name!r}")
        return destination / next(iter(roots))


def _verify_sdist(sdist: Path, version: str) -> None:
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        required = [
            *(f"/{resource}" for resource in CATALOGS.values()),
            *(f"/{resource}" for resource in SOURCE_POLICIES),
            *(
                f"/{resource}"
                for resource in (
                    "RELEASING.md",
                    "docs/conf.py",
                    "docs/index.md",
                    "docs/requirements.txt",
                    "tools/check_release_artifacts.py",
                    "tools/smoke_installed.py",
                    "tests/typecheck/mypy.ini",
                    "tests/typecheck/public_api.py",
                )
            ),
            f"/{WEB_RESOURCE}",
            f"/{TYPING_MARKER}",
        ]
        for suffix in required:
            if not any(name.endswith(suffix) for name in names):
                _fail(f"sdist is missing required file {suffix[1:]}")
    if sdist.name != f"voicefolio-{version}.tar.gz":
        _fail(f"sdist filename {sdist.name!r} disagrees with wheel version {version!r}")

    with tempfile.TemporaryDirectory(prefix="voicefolio-sdist-rebuild-") as directory:
        temp = Path(directory)
        source_root = _safe_extract_sdist(sdist, temp / "source")
        output = temp / "rebuilt"
        output.mkdir()
        env = os.environ.copy()
        env["SETUPTOOLS_SCM_PRETEND_VERSION"] = version
        command = [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--outdir",
            str(output),
            str(source_root),
        ]
        result = subprocess.run(
            command,
            cwd=temp,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            _fail(
                "sdist rebuild failed\n"
                f"command: {' '.join(command)}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        rebuilt = list(output.glob("*.whl"))
        if len(rebuilt) != 1:
            _fail(f"expected one wheel rebuilt from sdist, found {rebuilt}")
    print(f"sdist rebuild OK: {sdist.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--release-tag",
        default=os.environ.get("RELEASE_TAG"),
        help="optional release tag; when set, its version must match the artifacts",
    )
    args = parser.parse_args()
    if not args.artifacts.is_dir():
        _fail(f"artifact directory does not exist: {args.artifacts}")
    wheels = sorted(args.artifacts.glob("*.whl"))
    sdists = sorted(args.artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        _fail(f"expected exactly one wheel and one .tar.gz sdist; found {wheels} and {sdists}")
    expected_version = args.release_tag.removeprefix("v") if args.release_tag else None
    version = _verify_wheel(wheels[0], expected_version)
    _verify_sdist(sdists[0], version)
    print("release artifacts OK")


if __name__ == "__main__":
    main()
