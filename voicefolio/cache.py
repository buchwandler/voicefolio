from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .models import IntegrityError, ResolvedVoice, VoiceEntry


def default_cache_dir() -> Path:
    override = os.environ.get("VOICEFOLIO_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "voicefolio"


def asset_path(entry: VoiceEntry, cache_dir: str | Path | None = None) -> Path:
    root = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
    return root / "assets" / "sha256" / entry.sha256[:2] / f"{entry.sha256}.wav"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, entry: VoiceEntry) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IntegrityError(f"cannot inspect {path}: {exc}") from exc
    if size != entry.size:
        raise IntegrityError(
            f"size mismatch for {entry.ref}: expected {entry.size}, found {size}"
        )
    digest = sha256_file(path)
    if digest != entry.sha256:
        raise IntegrityError(
            f"SHA-256 mismatch for {entry.ref}: expected {entry.sha256}, found {digest}"
        )


def fetch(
    entry: VoiceEntry, *, cache_dir: str | Path | None = None, offline: bool = False
) -> ResolvedVoice:
    destination = asset_path(entry, cache_dir)
    if destination.exists():
        verify_file(destination, entry)
        return ResolvedVoice(entry=entry, path=destination)
    if offline:
        raise FileNotFoundError(f"voice {entry.ref} is not cached and offline mode is enabled")

    scheme = urlparse(entry.url).scheme
    if scheme not in {"https", "file"}:
        raise ValueError(f"unsupported catalog URL scheme {scheme!r}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            with urllib.request.urlopen(entry.url, timeout=60) as response:  # noqa: S310 - curated catalogs
                shutil.copyfileobj(response, tmp)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    try:
        verify_file(tmp_path, entry)
        os.replace(tmp_path, destination)
    finally:
        tmp_path.unlink(missing_ok=True)
    return ResolvedVoice(entry=entry, path=destination)
