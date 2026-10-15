from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from functools import wraps
from pathlib import Path
from typing import Annotated, Literal, ParamSpec

import typer

from . import __version__
from .cache import fetch, sha256_file
from .catalog import Catalog, load_catalog
from .cli_help import AdaptiveTyper, AdaptiveTyperGroup
from .errors import CatalogError, PlaybackError, VoicefolioError
from .integration import managed_reference
from .materialize import materialize_wav
from .migration import migrate_pocket_catalog
from .models import MaterializedVoice
from .playback import play_audio, play_wav
from .server import serve_browser
from .sources.fine_read_it_voices import (
    DEFAULT_REPOSITORY as DEFAULT_FINE_READ_IT_REPOSITORY,
)
from .sources.fine_read_it_voices import (
    build_catalog as build_fine_read_it_catalog,
)
from .sources.kyutai_tts_voices import (
    DEFAULT_REPOSITORY,
    DEFAULT_REVISION,
    verify_kyutai_catalog,
)
from .sources.kyutai_tts_voices import (
    build_catalog as build_kyutai_catalog,
)
from .sources.registry import verify_maintained_catalog
from .sources.voice_zero import (
    DEFAULT_REPOSITORY as DEFAULT_VOICE_ZERO_REPOSITORY,
)
from .sources.voice_zero import (
    DEFAULT_REVISION as DEFAULT_VOICE_ZERO_REVISION,
)
from .sources.voice_zero import (
    build_catalog as build_voice_zero_catalog,
)

app = AdaptiveTyper(
    cls=AdaptiveTyperGroup,
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Manage, preview, pin, and export reference voices.",
)


def _version_option(value: bool | None) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_option,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
) -> None:
    """Manage, preview, pin, and export reference voices."""
    del version


P = ParamSpec("P")


def _handle_voicefolio_errors(function: Callable[P, None]) -> Callable[P, None]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            function(*args, **kwargs)
        except VoicefolioError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    return wrapped


catalog_app = AdaptiveTyper(
    cls=AdaptiveTyperGroup,
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Build and verify source catalogs.",
)
app.add_typer(catalog_app, name="catalog")


def _catalog(catalog: list[Path] | None) -> Catalog:
    return load_catalog(catalog or ())


def _builtin_kyutai_catalog_path() -> Path:
    return Path(__file__).parent / "resources" / "catalogs" / "kyutai-tts-voices.json"


def _builtin_fine_read_it_catalog_path() -> Path:
    return Path(__file__).parent / "resources" / "catalogs" / "fine-read-it-voices.json"


def _builtin_voice_zero_catalog_path() -> Path:
    return Path(__file__).parent / "resources" / "catalogs" / "voice-zero.json"


@catalog_app.command("build-kyutai")  # type: ignore[untyped-decorator]
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


@catalog_app.command("build-fine-read-it")  # type: ignore[untyped-decorator]
def build_fine_read_it_command(
    repository: Annotated[
        str, typer.Option(help="Hugging Face dataset repository.")
    ] = DEFAULT_FINE_READ_IT_REPOSITORY,
    revision: Annotated[str, typer.Option(help="Upstream branch, tag, or commit.")] = "main",
    previous: Annotated[
        Path | None, typer.Option(help="Previous catalog used to protect published refs.")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Output catalog JSON path.")] = None,
    bootstrap: Annotated[
        bool,
        typer.Option(help="Allow the first catalog build when no previous catalog exists."),
    ] = False,
) -> None:
    """Build the Fine Read It catalog from a pinned upstream snapshot."""
    packaged_catalog = _builtin_fine_read_it_catalog_path()
    previous_path = previous or (packaged_catalog if packaged_catalog.exists() else None)
    output_path = output or packaged_catalog
    try:
        result = build_fine_read_it_catalog(
            previous_path,
            repository=repository,
            revision=revision,
            bootstrap=bootstrap,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (CatalogError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(output_path))


@catalog_app.command("build-voice-zero")  # type: ignore[untyped-decorator]
def build_voice_zero_command(
    repository: Annotated[
        str, typer.Option(help="GitHub owner/name repository.")
    ] = DEFAULT_VOICE_ZERO_REPOSITORY,
    revision: Annotated[
        str, typer.Option(help="Upstream branch, tag, or commit.")
    ] = DEFAULT_VOICE_ZERO_REVISION,
    previous: Annotated[
        Path | None, typer.Option(help="Previous catalog used to protect published refs.")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Output catalog JSON path.")] = None,
    bootstrap: Annotated[
        bool,
        typer.Option(help="Allow the first catalog build when no previous catalog exists."),
    ] = False,
) -> None:
    """Build the Voice-Zero catalog from a pinned GitHub snapshot."""
    packaged_catalog = _builtin_voice_zero_catalog_path()
    previous_path = previous or (packaged_catalog if packaged_catalog.exists() else None)
    output_path = output or packaged_catalog
    try:
        result = build_voice_zero_catalog(
            previous_path,
            repository=repository,
            revision=revision,
            bootstrap=bootstrap,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (CatalogError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(output_path))


@catalog_app.command("verify")  # type: ignore[untyped-decorator]
def verify_catalog_command(catalog_path: Path) -> None:
    """Verify a maintained source catalog using its declared namespace."""
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CatalogError("catalog root must be an object")
        verify_maintained_catalog(raw)
    except (CatalogError, OSError, json.JSONDecodeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"ok: {len(raw['voices'])} voices")


@app.command("version")  # type: ignore[untyped-decorator]
def version_command() -> None:
    """Print the dynamically derived package version."""
    typer.echo(__version__)


@app.command("list")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def list_command(
    catalog: Annotated[
        list[Path] | None, typer.Option("--catalog", help="Additional catalog JSON.")
    ] = None,
    namespace: Annotated[str | None, typer.Option("--namespace")] = None,
    dataset: Annotated[str | None, typer.Option()] = None,
    language: Annotated[str | None, typer.Option("--language", "-l")] = None,
    license: Annotated[str | None, typer.Option()] = None,
    variant: Annotated[str | None, typer.Option()] = None,
    speaker: Annotated[str | None, typer.Option("--speaker")] = None,
    gender: Annotated[str | None, typer.Option("--gender")] = None,
    pitch_band: Annotated[str | None, typer.Option("--pitch-band")] = None,
    emotion: Annotated[str | None, typer.Option("--emotion")] = None,
    query: Annotated[str | None, typer.Option("--query", "-q")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List stable voice IDs without downloading audio."""
    rows = _catalog(catalog).list(
        namespace=namespace,
        dataset=dataset,
        language=language,
        license=license,
        variant=variant,
        query=query,
        speaker=speaker,
        gender=gender,
        pitch_band=pitch_band,
        emotion=emotion,
    )
    if json_output:
        typer.echo(json.dumps([row.to_dict() for row in rows], indent=2))
        return
    typer.echo("REF\tLANGUAGE\tLICENSE\tVARIANT\tDATASET")
    for row in rows:
        typer.echo(f"{row.ref}\t{row.language}\t{row.license}\t{row.variant}\t{row.dataset}")


@app.command("show")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def show_command(
    ref: str,
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
) -> None:
    """Show pinned provenance for one stable voice ID."""
    entry = _catalog(catalog).get(ref)
    typer.echo(json.dumps(entry.to_dict(), indent=2))


@app.command("fetch")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def fetch_command(
    ref: str,
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
) -> None:
    """Fetch one source asset into the content-addressed cache and verify its pin."""
    resolved = fetch(_catalog(catalog).get(ref), cache_dir=cache_dir, offline=offline)
    typer.echo(str(resolved.path))


@app.command("preview")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def preview_command(
    ref: str,
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
    device: Annotated[str | None, typer.Option("--device")] = None,
) -> None:
    """Fetch a verified WAV or FLAC source asset and play it through native audio output."""
    entry = _catalog(catalog).get(ref)
    resolved = fetch(entry, cache_dir=cache_dir, offline=offline)
    typer.echo(str(resolved.path))
    playback_device: str | int | None = device
    if device is not None and device.isdecimal():
        playback_device = int(device)
    try:
        (play_audio if getattr(entry, "format", "wav") == "flac" else play_wav)(
            resolved.path,
            device=playback_device,
        )
    except PlaybackError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("browse")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def browse_command(
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    query: Annotated[str | None, typer.Option("--query", "-q")] = None,
    namespace: Annotated[str | None, typer.Option("--namespace")] = None,
    dataset: Annotated[str | None, typer.Option()] = None,
    language: Annotated[str | None, typer.Option("--language", "-l")] = None,
    license: Annotated[str | None, typer.Option()] = None,
    variant: Annotated[str | None, typer.Option()] = None,
    speaker: Annotated[str | None, typer.Option("--speaker")] = None,
    gender: Annotated[str | None, typer.Option("--gender")] = None,
    pitch_band: Annotated[str | None, typer.Option("--pitch-band")] = None,
    emotion: Annotated[str | None, typer.Option("--emotion")] = None,
    page_size: Annotated[int, typer.Option(help="Voices shown per page.")] = 20,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
    device: Annotated[str | None, typer.Option("--device")] = None,
) -> None:
    """Interactively filter, page through, and preview catalog voices."""
    if page_size < 1:
        raise typer.BadParameter("page-size must be positive")

    active = _catalog(catalog)
    catalog_entries = active.list()

    def entry_metadata(entry: object) -> Mapping[str, object]:
        metadata = getattr(entry, "metadata", {})
        return metadata if isinstance(metadata, Mapping) else {}

    def entry_namespace(entry: object) -> str:
        ref = getattr(entry, "ref", None)
        namespace_value = getattr(ref, "namespace", None)
        if isinstance(namespace_value, str):
            return namespace_value
        fallback = getattr(entry, "namespace", "")
        return fallback if isinstance(fallback, str) else ""

    available_languages = sorted({entry.language for entry in catalog_entries} | {"und"})
    available_namespaces = sorted(
        {entry_namespace(entry) for entry in catalog_entries if entry_namespace(entry)}
    )
    facet_options = {
        "speaker": sorted(
            {
                value
                for entry in catalog_entries
                for value in (
                    entry_metadata(entry).get("speaker_name"),
                    entry_metadata(entry).get("speaker_id"),
                )
                if isinstance(value, str) and value
            }
        ),
        "gender": sorted(
            {
                value
                for entry in catalog_entries
                if isinstance((value := entry_metadata(entry).get("gender")), str)
            }
        ),
        "pitch-band": sorted(
            {
                value
                for entry in catalog_entries
                if isinstance((value := entry_metadata(entry).get("pitch_band")), str)
            }
        ),
        "emotion": sorted(
            {
                value
                for entry in catalog_entries
                if isinstance((value := entry_metadata(entry).get("emotion")), str)
            }
        ),
    }
    if language is not None and language not in available_languages:
        available = ", ".join(available_languages)
        raise typer.BadParameter(f"unknown language {language!r}. Available: {available}.")
    page = 0
    while True:
        rows = active.list(
            namespace=namespace,
            dataset=dataset,
            language=language,
            license=license,
            variant=variant,
            query=query,
            speaker=speaker,
            gender=gender,
            pitch_band=pitch_band,
            emotion=emotion,
        )
        page_count = max(1, (len(rows) + page_size - 1) // page_size)
        page = min(page, page_count - 1)
        page_rows = rows[page * page_size : (page + 1) * page_size]

        typer.echo(f"Voicefolio — {len(rows)} voices")
        typer.echo(
            f"Filters: search={query or '<none>'}  language={language or '<all>'}  "
            f"namespace={namespace or '<all>'}  dataset={dataset or '<all>'}  "
            f"license={license or '<all>'}  variant={variant or '<all>'}  "
            f"speaker={speaker or '<all>'}  gender={gender or '<all>'}  "
            f"pitch-band={pitch_band or '<all>'}  emotion={emotion or '<all>'}"
        )
        typer.echo(f"Page {page + 1}/{page_count}")
        for number, entry in enumerate(page_rows, start=1):
            metadata = entry_metadata(entry)
            speaker_name = metadata.get("speaker_name")
            pitch_band_value = metadata.get("pitch_band")
            emotion_value = metadata.get("emotion")
            variant_label = (
                f"{entry.variant}/{emotion_value}" if emotion_value else entry.variant
            )
            typer.echo(
                f"{number:>2} {entry.ref}  {entry.language}  {entry.license}  "
                f"{variant_label}  source={entry_namespace(entry)}  "
                f"speaker={speaker_name or '<unknown>'}  "
                f"pitch={pitch_band_value or '<unknown>'}"
            )
        typer.echo(
            "[number] play  / search  l language  s source/namespace  f facets  "
            "n next  p previous  q quit"
        )

        command = typer.prompt(">").strip()
        if command.lower() == "q":
            return
        if command.lower() == "n":
            page = min(page + 1, page_count - 1)
            continue
        if command.lower() == "p":
            page = max(page - 1, 0)
            continue
        if command.lower() == "l":
            selected_language = typer.prompt(
                "Language (empty clears)", default="", show_default=False
            ).strip()
            if not selected_language:
                language = None
                page = 0
            elif selected_language not in available_languages:
                available = ", ".join(available_languages)
                typer.echo(f"Unknown language '{selected_language}'. Available: {available}.")
            else:
                language = selected_language
                page = 0
            continue
        if command.lower() == "s":
            typer.echo(f"Available sources: {', '.join(available_namespaces) or '<none>'}")
            selected_namespace = typer.prompt(
                "Source namespace (empty clears)", default="", show_default=False
            ).strip()
            if selected_namespace and selected_namespace not in available_namespaces:
                available = ", ".join(available_namespaces)
                typer.echo(f"Unknown source '{selected_namespace}'. Available: {available}.")
                continue
            namespace = selected_namespace or None
            page = 0
            continue
        if command.lower() == "f":
            selected_filter = (
                typer.prompt(
                    "Facet (speaker, gender, pitch-band, emotion; empty cancels)",
                    default="",
                    show_default=False,
                )
                .strip()
                .lower()
            )
            if not selected_filter:
                continue
            if selected_filter not in facet_options:
                typer.echo("Choose speaker, gender, pitch-band, or emotion.")
                continue
            typer.echo(
                f"Available {selected_filter}: "
                f"{', '.join(facet_options[selected_filter]) or '<none>'}"
            )
            selected_value = typer.prompt(
                f"{selected_filter} (empty clears)", default="", show_default=False
            ).strip()
            if not selected_value:
                if selected_filter == "speaker":
                    speaker = None
                elif selected_filter == "gender":
                    gender = None
                elif selected_filter == "pitch-band":
                    pitch_band = None
                else:
                    emotion = None
                page = 0
                continue
            choices = facet_options[selected_filter]
            if selected_filter == "speaker":
                if not any(
                    selected_value.casefold() in choice.casefold() for choice in choices
                ):
                    typer.echo("No matching speaker; the existing filter is unchanged.")
                    continue
                speaker = selected_value
            else:
                canonical = next(
                    (
                        choice
                        for choice in choices
                        if choice.casefold() == selected_value.casefold()
                    ),
                    None,
                )
                if canonical is None:
                    available = ", ".join(choices) or "<none>"
                    typer.echo(
                        f"Unknown {selected_filter} '{selected_value}'. Available: {available}."
                    )
                    continue
                if selected_filter == "gender":
                    gender = canonical
                elif selected_filter == "pitch-band":
                    pitch_band = canonical
                else:
                    emotion = canonical
            page = 0
            continue
        if command == "/" or command.startswith("/"):
            query = (
                typer.prompt("Search (empty clears)").strip()
                if command == "/"
                else command[1:].strip()
            )
            query = query or None
            page = 0
            continue
        if not command.isdecimal() or not 1 <= int(command) <= len(page_rows):
            typer.echo("Choose a listed number, /search, l, n, p, or q.", err=True)
            continue

        entry = page_rows[int(command) - 1]
        playback_device: str | int | None = device
        if device is not None and device.isdecimal():
            playback_device = int(device)
        try:
            resolved = fetch(entry, cache_dir=cache_dir, offline=offline)
            typer.echo(f"Playing {entry.ref}")
            (play_audio if getattr(entry, "format", "wav") == "flac" else play_wav)(
                resolved.path,
                device=playback_device,
            )
        except VoicefolioError as exc:
            typer.echo(f"Error: {exc}", err=True)


@app.command("browse-web")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def browse_web_command(
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
    port: Annotated[
        int, typer.Option(help="Loopback HTTP port; 0 selects an available port.")
    ] = 0,
) -> None:
    """Open the minimal local browser addon for catalog search and preview."""
    if not 0 <= port <= 65535:
        raise typer.BadParameter("port must be between 0 and 65535")
    serve_browser(_catalog(catalog), cache_dir=cache_dir, offline=offline, port=port)


@app.command("export")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def export_command(
    ref: str,
    output: Annotated[Path, typer.Option("--output", "-o")],
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
    cache_dir: Annotated[Path | None, typer.Option()] = None,
    offline: Annotated[bool, typer.Option()] = False,
    manifest: Annotated[Path | None, typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
    export_format: Annotated[Literal["wav", "source"], typer.Option("--format")] = "wav",
    force_extension: Annotated[bool, typer.Option("--force-extension")] = False,
) -> None:
    """Export a renderer WAV or exact source bytes with a provenance manifest."""
    entry = _catalog(catalog).get(ref)
    output = output.expanduser()
    manifest_path = (
        manifest or output.with_suffix(output.suffix + ".voicefolio.json")
    ).expanduser()
    if manifest_path == output:
        raise typer.BadParameter("manifest path must be different from output path")
    if (
        export_format == "source"
        and not force_extension
        and output.suffix.lower() != f".{entry.format}"
    ):
        raise typer.BadParameter(
            f"source export for {entry.ref} requires a .{entry.format} suffix; "
            "pass --force-extension to override"
        )
    if export_format == "wav" and entry.format == "flac" and output.suffix.lower() != ".wav":
        raise typer.BadParameter("renderer-ready FLAC exports require a .wav suffix")

    resolved = (
        fetch(entry, cache_dir=cache_dir, offline=offline)
        if export_format == "source"
        else materialize_wav(entry, cache_dir=cache_dir, offline=offline)
    )
    if output.exists() and not force:
        raise typer.BadParameter(f"output exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    source = resolved.source if isinstance(resolved, MaterializedVoice) else resolved
    exported_sha = resolved.sha256
    output_format = entry.format if export_format == "source" else "wav"
    materialization = (
        {
            "recipe": resolved.recipe,
            "sample_rate": resolved.sample_rate,
            "channels": resolved.channels,
            "subtype": resolved.subtype,
        }
        if isinstance(resolved, MaterializedVoice)
        else None
    )

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
        shutil.copyfile(resolved.path, temporary)
        actual_sha = sha256_file(temporary)
        if actual_sha != exported_sha:
            raise VoicefolioError("exported asset digest changed unexpectedly")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "kind": "voicefolio-export",
        "ref": str(entry.ref),
        "sha256": exported_sha,
        "source_sha256": source.sha256,
        "size": output.stat().st_size,
        "source_size": source.entry.size,
        "format": entry.format,
        "source_format": entry.format,
        "output_format": output_format,
        "license": entry.license,
        "source_repository": entry.source_repository,
        "source_revision": entry.source_revision,
        "source_path": entry.source_path,
        "dataset": entry.dataset,
        "variant": entry.variant,
        "output": output.name,
    }
    if materialization is not None:
        payload["materialization"] = materialization
    manifest_temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=manifest_path.parent, delete=False
        ) as handle:
            manifest_temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(manifest_temporary, manifest_path)
    finally:
        if manifest_temporary is not None:
            manifest_temporary.unlink(missing_ok=True)
    typer.echo(str(output))
    typer.echo(str(manifest_path))


@app.command("binding")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
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


@app.command("validate")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
def validate_command(
    catalog: Annotated[list[Path] | None, typer.Option("--catalog")] = None,
) -> None:
    """Load and validate all active catalogs and stable-ID digest collisions."""
    active = _catalog(catalog)
    typer.echo(f"ok: {len(active)} voices")


@app.command("migrate-pocket")  # type: ignore[untyped-decorator]
@_handle_voicefolio_errors
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
