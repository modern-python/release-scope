import collections.abc
import importlib.metadata
import json
import pathlib
import runpy
import sys
import typing

import pytest
from typer.testing import CliRunner

from release_scope import ioc
from release_scope.__main__ import MAIN_APP
from tests.conftest import GitLab
from tests.gitlab_mock import ENDPOINT, ServiceData, fail_everything, requested_paths


pytestmark = pytest.mark.httpx2(assert_all_called=False)

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
def test_collect_writes_report_and_cache(gitlab: GitLab, tmp_path: pathlib.Path) -> None:
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
    assert {call.request.headers["PRIVATE-TOKEN"] for call in gitlab.router.calls} == {"glpat-test"}

    gitlab.router.reset()
    second: typing.Final = _invoke("collect", "-g", "team", "-o", str(output), "--cache", str(cache))
    assert second.exit_code == 0, second.output
    assert "/api/v4/projects/1/pipelines/103/jobs" not in requested_paths(gitlab.router)


@pytest.mark.usefixtures("cli_env")
def test_unreadable_cache_is_ignored_with_a_warning(gitlab: GitLab, tmp_path: pathlib.Path) -> None:
    cache: typing.Final = tmp_path / "cache.json"
    cache.write_text('{"schema_version": 99}')

    result: typing.Final = _invoke("collect", "-p", "team/svc", "-o", str(tmp_path / "r.json"), "--cache", str(cache))

    assert result.exit_code == 0, result.output
    assert f"Warning: Ignoring unreadable cache {cache}: ValidationError." in result.output
    assert json.loads(cache.read_text())["schema_version"] == 1
    assert gitlab.router.calls


@pytest.mark.usefixtures("cli_env")
def test_failed_service_is_reported_and_exits_non_zero(gitlab: GitLab, tmp_path: pathlib.Path) -> None:
    gitlab.add_failing_service(ServiceData(id=2, path="team/broken"), 400)
    output: typing.Final = tmp_path / "report.json"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 1
    assert "Error: team/broken: GitLab returned 400" in result.output
    assert [item["error"] is None for item in json.loads(output.read_text())["services"]] == [False, True]


@pytest.mark.usefixtures("cli_env")
def test_authentication_failure_exits_with_auth_code(gitlab: GitLab, tmp_path: pathlib.Path) -> None:
    fail_everything(gitlab.router, 403)
    output: typing.Final = tmp_path / "report.json"

    result: typing.Final = _invoke("collect", "-g", "team", "-o", str(output))

    assert result.exit_code == 3
    assert "Error: GitLab rejected the token (403)" in result.output
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


def test_version_falls_back_when_package_metadata_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.version", missing)

    assert _invoke("--version").output.strip() == "0"


def test_module_entry_point_runs_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["release-scope", "--version"])
    monkeypatch.delitem(sys.modules, "release_scope.__main__")

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("release_scope", run_name="__main__")

    assert exc_info.value.code == 0
