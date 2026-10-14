from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .cache import fetch, sha256_file
from .catalog import Catalog, load_catalog
from .integration import managed_reference
from .migration import migrate_pocket_catalog
from .models import CatalogError, PlaybackError
from .playback import play_wav
from .sources.kyutai_tts_voices import (
    DEFAULT_REPOSITORY,
    DEFAULT_REVISION,
    verify_kyutai_catalog,
)
from .sources.kyutai_tts_voices import (
    build_catalog as build_kyutai_catalog,
)

app = typer.Typer(
    no_args_is_help=True, help="Manage, preview, pin, and export reference voices."
)


catalog_app = typer.Typer(no_args_is_help=True, help="Build and verify source catalogs.")
app.add_typer(catalog_app, name="catalog")


def _catalog(catalog: list[Path] | None) -> Catalog:
    return load_catalog(catalog or ())


def _builtin_kyutai_catalog_path() -> Path:
    return Path(__file__).parent / "resources" / "catalogs" / "kyutai-tts-voices.json"


@catalog_app.command("build-kyutai")
def build_kyutai_command(
    repository: Annotated[str, typer.Option(help="Hugging Face dataset repository.")] = (
        DEFAULT_REPOSITORY
    ),
    revision: Annotated[str, typer.Option(help="Upstream branch, tag, or commit.")] = (
        DEFAULT_REVISION
    ),
    previous: Annotated[
        Path | None, typer.Option(help="Previous catalog used to protect published refs.")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Output catalog JSON path.")] = None,
) -> None:
    """Build the authoritative Kyutai catalog from a pinned upstream snapshot."""
    packaged_catalog = _builtin_kyutai_catalog_path()
    previous_path = previous or packaged_catalog
    output_path = output or packaged_catalog
    try:
        result = build_kyutai_catalog(previous_path, repository=repository, revision=revision)
        verify_kyutai_catalog(result)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (CatalogError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(output_path))


@catalog_app.command("verify")
def verify_catalog_command(catalog_path: Path) -> None:
    """Verify a Kyutai source catalog against Voicefolio maintainer invariants."""
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CatalogError("catalog root must be an object")
        verify_kyutai_catalog(raw)
    except (CatalogError, OSError, json.JSONDecodeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"ok: {len(raw['voices'])} voices")


@app.command("version")
def version_command() -> None:
    """Print the dynamically derived package version."""
    typer.echo(__version__)


@app.command("list")
def list_command(
    catalog: Annotated[
        list[Path] | None, typer.Option("--catalog", help="Additional catalog JSON.")
    ] = None,
    dataset: Annotated[str | None, typer.Option()] = None,
    license: Annotated[str | None, typer.Option()] = None,
    variant: Annotated[str | None, typer.Option()] = None,
    query: Annotated[str | None, typer.Option("--query", "-q")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List stable voice IDs without downloading audio."""
    rows = _catalog(catalog).list(
        dataset=dataset, license=license, variant=variant, query=query
    )
    if json_output:
        typer.echo(json.dumps([row.to_dict() for row in rows], indent=2))
        return
    for row in rows:
        typer.echo(f"{row.ref}\t{row.license}\t{row.variant}\t{row.dataset}")


@app.command("show")
def show_command(
    ref: str,
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
) -> None:
    """Show pinned provenance for one stable voice ID."""
    entry = _catalog(catalog).get(ref)
    typer.echo(json.dumps(entry.to_dict(), indent=2))


@app.command("fetch")
def fetch_command(
    ref: str,
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
) -> None:
    """Fetch one WAV into the content-addressed cache and verify its pin."""
    resolved = fetch(_catalog(catalog).get(ref), cache_dir=cache_dir, offline=offline)
    typer.echo(str(resolved.path))


@app.command("preview")
def preview_command(
    ref: str,
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
    device: Annotated[str | None, typer.Option("--device")] = None,
) -> None:
    """Fetch a verified WAV into cache and play it through native audio output."""
    resolved = fetch(_catalog(catalog).get(ref), cache_dir=cache_dir, offline=offline)
    typer.echo(str(resolved.path))
    playback_device: str | int | None = device
    if device is not None and device.isdecimal():
        playback_device = int(device)
    try:
        play_wav(resolved.path, device=playback_device)
    except PlaybackError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("export")
def export_command(
    ref: str,
    output: Annotated[Path, typer.Option("--output", "-o")],
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
    manifest: Annotated[Path | None, typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """Export exactly one pinned WAV and a provenance manifest."""
    entry = _catalog(catalog).get(ref)
    resolved = fetch(entry, cache_dir=cache_dir, offline=offline)
    output = output.expanduser()
    if output.exists() and not force:
        raise typer.BadParameter(f"output exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resolved.path, output)
    exported_sha = sha256_file(output)
    if exported_sha != entry.sha256:
        output.unlink(missing_ok=True)
        raise RuntimeError("exported WAV digest changed unexpectedly")
    manifest_path = manifest or output.with_suffix(output.suffix + ".voicefolio.json")
    payload = {
        "schema": 1,
        "kind": "voicefolio-export",
        "ref": str(entry.ref),
        "sha256": entry.sha256,
        "size": entry.size,
        "format": entry.format,
        "license": entry.license,
        "source_repository": entry.source_repository,
        "source_revision": entry.source_revision,
        "source_path": entry.source_path,
        "dataset": entry.dataset,
        "variant": entry.variant,
        "output": output.name,
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    typer.echo(str(output))
    typer.echo(str(manifest_path))


@app.command("binding")
def binding_command(
    ref: str,
    renderer: Annotated[str, typer.Option()] = "pocket",
    target_id: Annotated[str, typer.Option()] = "REPLACE_WITH_TARGET_ID",
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Emit a RenderPlan/VoiceRender managed-reference binding."""
    source = managed_reference(ref, catalog=_catalog(catalog))
    binding = {
        "renderer": renderer,
        "target_id": target_id,
        "options": {"voice_source": source},
    }
    if json_output:
        typer.echo(json.dumps(binding, indent=2))
        return
    typer.echo(f"renderer = {json.dumps(renderer)}")
    typer.echo(f"target_id = {json.dumps(target_id)}")
    typer.echo("\n[binding.options.voice_source]")
    for key, value in source.items():
        typer.echo(f"{key} = {json.dumps(value)}")


@app.command("validate")
def validate_command(
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
) -> None:
    """Load and validate all active catalogs and stable-ID digest collisions."""
    active = _catalog(catalog)
    typer.echo(f"ok: {len(active)} voices")


@app.command("migrate-pocket")
def migrate_pocket_command(
    source: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    namespace: Annotated[str, typer.Option()] = "kyutai-tts-voices",
) -> None:
    """Move the old pocket-onnx-bundles prompt catalog into Voicefolio schema."""
    result = migrate_pocket_catalog(source, output, namespace=namespace)
    typer.echo(str(result))


if __name__ == "__main__":
    app()
