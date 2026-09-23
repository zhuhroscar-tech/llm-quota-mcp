try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


def _project_metadata() -> dict:
    with open("pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]


def test_project_uses_current_spdx_license_metadata():
    project = _project_metadata()

    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert "License :: OSI Approved :: MIT License" not in project.get(
        "classifiers", []
    )


def test_package_version_matches_runtime_version():
    from llm_quota import __version__

    assert _project_metadata()["version"] == __version__
