from pathlib import Path

import tomllib


def test_dynamic_version_and_flat_layout():
    root = Path(__file__).parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools_scm"]["version_file"] == "voicefolio/_version.py"
    assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["."]
    assert not (root / "src").exists()
