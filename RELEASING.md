# Releasing Voicefolio

This guide prepares and verifies release candidates. **A green check is not authorization to tag or publish.** A human release owner must explicitly approve those actions. Catalog refresh workflows never publish package releases.

## 1. Start from a clean checkout

```bash
git status --short
git fetch --tags
```

Review the accepted release scope and confirm no downstream repository or historical release record is being changed. Do not rewrite the released `v0.1.0` ledger entry.

## 2. Install release tooling

Use a supported Python version and install development, documentation, and Twine tooling:

```bash
python -m pip install -e '.[dev]'
python -m pip install -r docs/requirements.txt twine
```

Install `voicefolio[audio]` only if manually exercising FLAC conversion. No physical audio device is required for CI or package smoke checks.

## 3. Run tests and static/documentation checks

```bash
python -m pytest -q
ruff check .
mypy voicefolio
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Run the supported Linux/macOS/Windows and Python-version CI matrix. Review all warnings as errors for Sphinx and resolve them before release.
The required CI matrix is Ubuntu, macOS, and Windows across Python 3.10–3.14. A local green run is not a substitute: capture successful checks for the exact candidate commit, including the release-artifacts job.

## 4. Verify packaged catalogs

```bash
voicefolio catalog verify voicefolio/resources/catalogs/kyutai-tts-voices.json
voicefolio catalog verify voicefolio/resources/catalogs/fine-read-it-voices.json
voicefolio catalog verify voicefolio/resources/catalogs/voice-zero.json
voicefolio validate
```

The Kyutai compatibility baseline remains 1,161 immutable rows with unchanged ref-to-SHA-256 mappings. If catalog data changed, rebuild each candidate twice against one resolved upstream revision, compare the byte-identical outputs, inspect source diffs, license/attribution evidence, quarantine diagnostics, and the recorded refresh revision. Never let a missing baseline silently enable bootstrap behavior.

For a release candidate, record successful scheduled runs of all three source-refresh workflows (Kyutai, Fine Read It, and Voice-Zero) and inspect their resolved revisions, deterministic outputs, immutable-row checks, and quarantine diagnostics. Workflow definitions or local source tests alone are not scheduled-run evidence.

## 5. Review changelog and release record

Update the unreleased changelog source through the repository's release-ledger workflow. Review package versioning, public API/CLI compatibility, catalog counts, source evidence, and generated changelog output. Do not edit historical release records to describe new features.

Keep the v0.1.2 heading undated and marked Unreleased until the release owner supplies the actual release date. Before using the draft for a final candidate, commit the candidate changes, refresh the Releaseledger snapshot to that exact commit, inspect and account for every added commit, validate complete audit coverage, and rebuild the draft. Do not treat a stale range or an uncommitted worktree as the final release scope.

## 6. Build and check distributions

Start with a clean output directory:

```bash
rm -rf build dist
python -m build
python -m twine check dist/*
python tools/check_release_artifacts.py --artifacts dist
```

If Termux/Android cannot load Twine's `nh3` extension, do not skip this check: run it on the supported Ubuntu release/CI runner.

The reusable checker verifies exactly one wheel and sdist, package/version/dependency metadata, the three packaged catalogs and source-policy resources, `py.typed`, the browser page, catalog parsing/source verification, sdist contents, and an sdist rebuild in a temporary directory. On an approved release candidate, pass the intended tag explicitly:

```bash
python tools/check_release_artifacts.py --artifacts dist --release-tag vX.Y.Z
```

## 7. Smoke-test the installed wheel

```bash
python tools/smoke_installed.py --artifacts dist
```

The smoke tool installs the wheel into a temporary virtual environment and runs outside the checkout. It exercises import, `--version`, help, all catalog namespaces, `show`, `binding`, `validate`, and an offline fixture fetch/export. It does not require network access, a browser GUI, or a sound device.

## 8. Tag/publish authorization gate

Confirm all checks and review the exact wheel/sdist and changelog. Verify that the intended tag's version matches the built artifacts. **Only after explicit human authorization** may the release owner create a tag or publish the package. Do not use this implementation, catalog refresh, or ordinary CI to tag or publish automatically.
Release readiness also requires successful CI for the exact candidate commit across the complete OS/Python matrix and successful scheduled Kyutai, Fine Read It, and Voice-Zero refresh evidence for that candidate. If either external gate is unavailable or has not run, stop and report the release as not ready; never create a tag or publish without explicit human release-owner authorization.
