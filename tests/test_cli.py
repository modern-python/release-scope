import collections.abc
import json
import pathlib
import runpy
import sys
import typing

import pytest
import respx
from typer.testing import CliRunner

from release_scope import ioc
from release_scope.__main__ import MAIN_APP
from tests.payloads import API, ENDPOINT, SERVICE, project


_RUNNER: typing.Final = CliRunner()


@pytest.fixture(autouse=True)
def _open_container() -> collections.abc.Iterator[None]:
    with ioc.container:
        yield


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
    monkeypatch.setenv("RELEASE_SCOPE_GITLAB__ENDPOINT", ENDPOINT)
    monkeypatch.setenv("RELEASE_SCOPE_ENVIRONMENTS", '["preview"]')


def _invoke(*args: str) -> typing.Any:  # noqa: ANN401
    return _RUNNER.invoke(MAIN_APP, list(args))


@pytest.mark.usefixtures("cli_env")
def test_collect_writes_report_and_cache(gitlab: respx.Router, tmp_path: pathlib.Path) -> None:
    output: typing.Final = tmp_path / "out" / "report.json"
    cache: typing.Final = tmp_path / "cache.json"

    first: typing.Final = _invoke("collect", "--group", "team", "--output", str(output), "--cache", str(cache))

    assert first.exit_code == 0, first.output
    report: typing.Final = json.loads(output.read_text())
    assert report["schema_version"] == 1
    assert report["production_environment"] == "production"
    assert [len(item["rows"]) for item in report["services"]] == [5]
    assert "1 services, 5 rows, 0 failed" in first.output
    assert json.loads(cache.read_text())["pipelines"]["1"]
    assert {call.request.headers["PRIVATE-TOKEN"] for call in gitlab.calls} == {"glpat-test"}

    second: typing.Final = _invoke("collect", "-g", "team", "-o", str(output), "--cache", str(cache))
    assert second.exit_code == 0, second.output
    assert gitlab["commit_mrs:head"].call_count == 1
    assert [gitlab[f"jobs:{pipeline_id}"].call_count for pipeline_id in (104, 103)] == [2, 1]


@pytest.mark.usefixtures("cli_env", "gitlab")
def test_unreadable_cache_is_ignored_with_a_warning(tmp_path: pathlib.Path) -> None:
    cache: typing.Final = tmp_path / "cache.json"
    cache.write_text('{"schema_version": 99}')

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "r.json"), "--cache", str(cache))

    assert result.exit_code == 0, result.output
    assert f"Warning: Ignoring unreadable cache {cache}: ValidationError." in result.output
    assert json.loads(cache.read_text())["schema_version"] == 1


@pytest.mark.usefixtures("cli_env")
def test_failed_service_is_reported_and_exits_non_zero(gitlab: respx.Router, tmp_path: pathlib.Path) -> None:
    gitlab["group"].respond(json=[SERVICE, project(2, "team/broken")])
    gitlab.get(f"{API}/projects/2/deployments").respond(400)
    output: typing.Final = tmp_path / "report.json"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 1
    assert "Error: team/broken: GitLab returned 400 for deployments." in result.output
    assert [item["error"] is None for item in json.loads(output.read_text())["services"]] == [False, True]


@pytest.mark.usefixtures("cli_env")
def test_forbidden_service_fails_alone_and_exits_non_zero(gitlab: respx.Router, tmp_path: pathlib.Path) -> None:
    gitlab["group"].respond(json=[SERVICE, project(2, "team/nodeploy")])
    gitlab.get(f"{API}/projects/2/deployments").respond(403)

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "report.json"))

    assert result.exit_code == 1
    assert "Error: team/nodeploy: GitLab denied access to deployments (403). Check that:" in result.output
    assert "1 failed" in result.output


@pytest.mark.usefixtures("cli_env")
def test_rejected_token_exits_with_auth_code(httpx2_mock: respx.Router, tmp_path: pathlib.Path) -> None:
    httpx2_mock.get(f"{API}/groups/team/projects").respond(401)

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "report.json"))

    assert result.exit_code == 3
    assert "Error: GitLab rejected the token (401)." in result.output


@pytest.mark.usefixtures("cli_env")
def test_authentication_failure_exits_with_auth_code(httpx2_mock: respx.Router, tmp_path: pathlib.Path) -> None:
    httpx2_mock.get(f"{API}/groups/team/projects").respond(403)
    output: typing.Final = tmp_path / "report.json"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 3
    assert "Error: GitLab denied access to group 'team' (403)" in result.output
    assert not output.exists()


@pytest.mark.usefixtures("cli_env")
def test_collect_needs_a_group_or_project(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "-o", str(tmp_path / "r.json"))

    assert result.exit_code == 2
    assert "Pass at least one --group or --project." in result.output


def test_collect_needs_a_token(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "r.json"))

    assert result.exit_code == 2
    assert "GitLab token is missing" in result.output


def test_version_prints_package_version() -> None:
    result: typing.Final = _invoke("--version")

    assert result.exit_code == 0
    assert result.output.strip()


def test_module_entry_point_runs_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["release-scope", "--version"])
    monkeypatch.delitem(sys.modules, "release_scope.__main__")

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("release_scope", run_name="__main__")

    assert exc_info.value.code == 0


def test_render_writes_markdown_from_a_report(tmp_path: pathlib.Path) -> None:
    report: typing.Final = tmp_path / "report.json"
    report.write_text(
        '{"schema_version": 1, "collected_at": "2026-09-29T10:15:00Z", '
        '"production_environment": "prod", "services": []}'
    )
    page: typing.Final = tmp_path / "out" / "report.md"

    result: typing.Final = _invoke("render", str(report), "--output", str(page))

    assert result.exit_code == 0, result.output
    assert page.read_text().startswith("# Release scope\n")
    assert f"-> {page}" in result.output


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (None, "FileNotFoundError"),
        ('{"schema_version": 2}', "ValidationError"),
        ("not json", "ValidationError"),
    ],
)
def test_render_rejects_an_unreadable_report(tmp_path: pathlib.Path, content: str | None, reason: str) -> None:
    report: typing.Final = tmp_path / "report.json"
    if content is not None:
        report.write_text(content)

    result: typing.Final = _invoke("render", str(report), "-o", str(tmp_path / "report.md"))

    assert result.exit_code == 2
    assert f"Error: Cannot read report {report}: {reason}." in result.output
    assert not (tmp_path / "report.md").exists()
