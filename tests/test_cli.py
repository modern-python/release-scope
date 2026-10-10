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
from tests.payloads import API, ENDPOINT, JIRA_ENDPOINT, SERVICE, project


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
    output: typing.Final = tmp_path / "public"
    cache: typing.Final = tmp_path / "cache.json"

    first: typing.Final = _invoke("collect", "--group", "team", "--output", str(output), "--cache", str(cache))

    assert first.exit_code == 0, first.output
    assert sorted(item.name for item in output.iterdir()) == [
        "alpine.LICENSE.txt",
        "alpine.min.js",
        "index.html",
        "report.json",
    ]
    report: typing.Final = json.loads((output / "report.json").read_text())
    assert report["schema_version"] == 5
    assert report["jira"] is None
    assert report["production_environment"] == "production"
    assert [len(item["rows"]) for item in report["services"]] == [5]
    assert "1 services, 5 rows, 0 failed" in first.output
    assert json.loads(cache.read_text())["pipelines"]["1"]
    assert {call.request.headers["PRIVATE-TOKEN"] for call in gitlab.calls} == {"glpat-test"}

    second: typing.Final = _invoke("collect", "-g", "team", "-o", str(output), "--cache", str(cache))
    assert second.exit_code == 0, second.output
    assert gitlab["commit_mrs:head"].call_count == 1
    assert [gitlab[f"jobs:{pipeline_id}"].call_count for pipeline_id in (104, 103)] == [2, 1]


@pytest.mark.httpx2(assert_all_called=False)
@pytest.mark.usefixtures("cli_env", "gitlab")
def test_collect_skips_excluded_projects(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "-g", "team", "--exclude", "team/*", "-o", str(tmp_path / "public"))

    assert result.exit_code == 0, result.output
    assert "0 services, 0 rows, 0 failed" in result.output


@pytest.mark.usefixtures("cli_env", "gitlab")
def test_unreadable_cache_is_ignored_with_a_warning(tmp_path: pathlib.Path) -> None:
    cache: typing.Final = tmp_path / "cache.json"
    cache.write_text('{"schema_version": 99}')

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "public"), "--cache", str(cache))

    assert result.exit_code == 0, result.output
    assert f"Warning: Ignoring unreadable cache {cache}: ValidationError." in result.output
    assert json.loads(cache.read_text())["schema_version"] == 1


@pytest.mark.usefixtures("cli_env")
def test_failed_service_is_reported_and_exits_non_zero(gitlab: respx.Router, tmp_path: pathlib.Path) -> None:
    gitlab["group"].respond(json=[SERVICE, project(2, "team/broken")])
    gitlab.get(f"{API}/projects/2/deployments").respond(400)
    output: typing.Final = tmp_path / "public"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 1
    assert "Error: team/broken: GitLab returned 400 for deployments." in result.output
    assert [item["error"] is None for item in json.loads((output / "report.json").read_text())["services"]] == [
        False,
        True,
    ]


@pytest.mark.usefixtures("cli_env")
def test_collect_reads_jira_issues_with_a_bearer_token(
    jira: respx.Router, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_ENDPOINT", JIRA_ENDPOINT)
    monkeypatch.setenv("JIRA_TOKEN", "jira-pat")
    output: typing.Final = tmp_path / "public"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 0, result.output
    assert sorted(json.loads((output / "report.json").read_text())["jira"]["issues"]) == ["SHOP-12", "SHOP-9"]
    assert jira["jira_search"].calls.last.request.headers["Authorization"] == "Bearer jira-pat"


@pytest.mark.usefixtures("cli_env")
@pytest.mark.httpx2(assert_all_called=False)
def test_jira_failure_is_reported_and_exits_non_zero(
    jira: respx.Router, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_ENDPOINT", JIRA_ENDPOINT)
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_TOKEN", "expired")
    jira["jira_search"].respond(401)
    output: typing.Final = tmp_path / "public"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 1
    assert "Error: Jira rejected the token (401)." in result.output
    assert json.loads((output / "report.json").read_text())["services"][0]["rows"]


@pytest.mark.usefixtures("cli_env")
def test_jira_token_needs_a_jira_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("JIRA_TOKEN", "jira-pat")

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "public"))

    assert result.exit_code == 2
    assert "Jira token is set but RELEASE_SCOPE_JIRA_ENDPOINT is not." in result.output


@pytest.fixture
def jira_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_ENDPOINT", JIRA_ENDPOINT)
    monkeypatch.setenv("JIRA_TOKEN", "jira-pat")
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_PROJECT_KEYS", '["SHOP"]')


@pytest.mark.usefixtures("cli_env", "jira_env", "scoped")
@pytest.mark.httpx2(assert_all_called=False)
def test_collect_for_jira_issues_writes_a_scoped_report(tmp_path: pathlib.Path) -> None:
    output: typing.Final = tmp_path / "public"
    cache: typing.Final = tmp_path / "cache.json"

    result: typing.Final = _invoke("collect", "--jira", "SHOP-12", "-o", str(output), "--cache", str(cache))

    assert result.exit_code == 1
    report: typing.Final = json.loads((output / "report.json").read_text())
    assert report["jira_scope"] == ["SHOP-12"]
    assert [item["project"] for item in report["services"]] == ["team/svc", "team/web", "team/worker"]
    assert json.loads(cache.read_text())["merge_requests"]["1"]["12"]["iid"] == 12
    assert "Error: team/web: GitLab returned 404 for the project." in result.output


@pytest.mark.usefixtures("cli_env", "jira_env", "scoped")
@pytest.mark.httpx2(assert_all_called=False)
def test_jira_issue_missing_from_jira_exits_non_zero(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "--jira", "SHOP-404", "-o", str(tmp_path / "public"))

    assert result.exit_code == 1
    assert "Error: Jira has no issue SHOP-404." in result.output


@pytest.mark.usefixtures("cli_env", "jira_env")
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--jira", "SHOP-1", "-g", "team"), "Pass either --jira or --group/--project, not both."),
        (("--jira", "shop-1"), "Not a Jira issue key: shop-1."),
    ],
)
def test_jira_option_is_validated(tmp_path: pathlib.Path, args: tuple[str, ...], message: str) -> None:
    result: typing.Final = _invoke("collect", *args, "-o", str(tmp_path / "public"))

    assert result.exit_code == 2
    assert message in result.output


@pytest.mark.usefixtures("cli_env")
def test_jira_option_needs_jira_settings(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "--jira", "SHOP-1", "-o", str(tmp_path / "public"))

    assert result.exit_code == 2
    assert "--jira needs RELEASE_SCOPE_JIRA_ENDPOINT and RELEASE_SCOPE_JIRA_TOKEN." in result.output


@pytest.mark.usefixtures("cli_env")
def test_forbidden_service_fails_alone_and_exits_non_zero(gitlab: respx.Router, tmp_path: pathlib.Path) -> None:
    gitlab["group"].respond(json=[SERVICE, project(2, "team/nodeploy")])
    gitlab.get(f"{API}/projects/2/deployments").respond(403)

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "public"))

    assert result.exit_code == 1
    assert "Error: team/nodeploy: GitLab denied access to deployments (403). Check that:" in result.output
    assert "1 failed" in result.output


@pytest.mark.usefixtures("cli_env")
def test_rejected_token_exits_with_auth_code(httpx2_mock: respx.Router, tmp_path: pathlib.Path) -> None:
    httpx2_mock.get(f"{API}/groups/team/projects").respond(401)

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "public"))

    assert result.exit_code == 3
    assert "Error: GitLab rejected the token (401)." in result.output


@pytest.mark.usefixtures("cli_env")
def test_authentication_failure_exits_with_auth_code(httpx2_mock: respx.Router, tmp_path: pathlib.Path) -> None:
    httpx2_mock.get(f"{API}/groups/team/projects").respond(403)
    output: typing.Final = tmp_path / "public"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 3
    assert "Error: GitLab denied access to group 'team' (403)" in result.output
    assert not output.exists()


@pytest.mark.usefixtures("cli_env")
def test_collect_needs_a_group_or_project(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "-o", str(tmp_path / "public"))

    assert result.exit_code == 2
    assert "Pass --jira, or at least one --group or --project." in result.output


def test_collect_needs_a_token(tmp_path: pathlib.Path) -> None:
    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(tmp_path / "public"))

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
