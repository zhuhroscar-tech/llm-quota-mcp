from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _project_metadata() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as f:
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


def test_required_repository_files_are_present():
    for relative in [
        "CHANGELOG.md",
        "LICENSE",
        "MANIFEST.in",
        "README.md",
        "README.zh-CN.md",
        ".github/workflows/ci.yml",
        ".gitignore",
    ]:
        assert (ROOT / relative).is_file(), relative


def test_readmes_link_release_history_and_license():
    for relative in ["README.md", "README.zh-CN.md"]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "CHANGELOG.md" in text
        assert "LICENSE" in text


def test_changelog_starts_with_current_version():
    project = _project_metadata()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert changelog.startswith("# Changelog\n\n## v" + project["version"])
    assert "## v0.1.2" in changelog
    assert "## v0.1.1" in changelog


def test_manifest_includes_release_and_test_metadata():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    for expected in [
        "include CHANGELOG.md",
        "include README.zh-CN.md",
        "recursive-include .github/workflows *.yml",
        "recursive-include docs *.mp4 *.png",
        "recursive-include tests *.py",
    ]:
        assert expected in manifest


def test_ci_runs_for_main_pull_requests_and_tags():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow
    assert 'tags: ["v*"]' in workflow
    assert "pull_request:" in workflow
    assert "python -m build" in workflow
    assert "actions/upload-artifact" in workflow
