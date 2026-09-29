import typing

import httpware
import pydantic
import pytest
import respx

from release_scope._cache import Cache
from release_scope._gitlab import GitLabApi
from release_scope._jira import JiraApi
from release_scope._report import Report, Service
from release_scope._settings import GitLabConfig, Settings
from release_scope._use_case import CollectUseCase
from tests.payloads import (
    COMMITS,
    ENDPOINT,
    JIRA_ENDPOINT,
    SERVICE_API,
    commit,
    merge_request,
    remote_link,
)


def _scope(*keys: str, cache: Cache | None = None) -> Report:
    use_case: typing.Final = CollectUseCase(
        api=GitLabApi(http=httpware.Client(base_url=ENDPOINT)),
        jira=JiraApi(http=httpware.Client(base_url=JIRA_ENDPOINT)),
        settings=Settings(
            gitlab=GitLabConfig(endpoint=ENDPOINT, token=pydantic.SecretStr("t")),
            environments=["preview"],
            jira_endpoint=JIRA_ENDPOINT,
            jira_project_keys=["SHOP"],
        ),
    )
    return use_case.for_issues(keys=list(keys) or ["SHOP-12"], cache=cache or Cache())


def _service(report: Report, path: str = "team/svc") -> Service:
    return next(item for item in report.services if item.project == path)


def _links(*urls: str) -> list[dict[str, typing.Any]]:
    return [remote_link(url) for url in urls]


@pytest.mark.httpx2(assert_all_called=False)
@pytest.mark.usefixtures("scoped")
def test_scope_collects_every_service_the_issues_link_to() -> None:
    report: typing.Final = _scope()

    assert report.jira_scope == ["SHOP-12"]
    assert [item.project for item in report.services] == ["team/svc", "team/web", "team/worker"]
    assert _service(report, "team/web").error == "team/web: GitLab returned 404 for /api/v4/projects/team/web."
    assert _service(report, "team/web").project_url == f"{ENDPOINT}/team/web"
    assert _service(report, "team/worker").warnings[0].startswith("CI/CD is disabled")


@pytest.mark.httpx2(assert_all_called=False)
@pytest.mark.usefixtures("scoped")
def test_rows_run_from_production_to_the_latest_linked_change() -> None:
    service: typing.Final = _service(_scope())

    assert [[item.iid for item in row.merge_requests] for row in service.rows] == [[12], [11], [10], [9]]
    assert [row.linked for row in service.rows] == [True, False, False, False]
    assert service.release is not None
    assert service.release.state == "pending"
    assert service.release.tag is not None
    assert service.release.tag.name == "1.2.0"


@pytest.mark.httpx2(assert_all_called=False)
def test_release_tag_is_the_nearest_tag_above_an_untagged_target(scoped: respx.Router) -> None:
    scoped["remote_links:SHOP-12"].respond(json=_links(f"{ENDPOINT}/team/svc/-/merge_requests/11"))
    scoped.get(f"{SERVICE_API}/merge_requests/11").respond(
        json=merge_request(11, "Bump UTF-8 handling", merge_commit_sha="c2", sha="x11")
    )

    service: typing.Final = _service(_scope())

    assert [[item.iid for item in row.merge_requests] for row in service.rows] == [[11], [10], [9]]
    assert service.release is not None
    assert service.release.tag is not None
    assert service.release.tag.name == "1.2.0"


@pytest.mark.httpx2(assert_all_called=False)
def test_release_has_no_tag_when_none_is_at_or_above_the_target(scoped: respx.Router) -> None:
    scoped["tags"].respond(json=[{"name": "1.1.0", "commit": {"id": "c1"}}])

    service: typing.Final = _service(_scope())

    assert service.release is not None
    assert (service.release.state, service.release.tag) == ("pending", None)


@pytest.mark.httpx2(assert_all_called=False)
def test_merged_change_outside_the_range_is_in_production(scoped: respx.Router) -> None:
    scoped["remote_links:SHOP-12"].respond(json=_links(f"{ENDPOINT}/team/svc/-/merge_requests/5"))
    scoped.get(f"{SERVICE_API}/merge_requests/5").respond(json=merge_request(5, "Old", merge_commit_sha="old"))

    service: typing.Final = _service(_scope())

    assert service.rows == []
    assert service.release is not None
    assert service.release.state == "in_production"


@pytest.mark.httpx2(assert_all_called=False)
def test_open_and_off_branch_merge_requests_are_reported(scoped: respx.Router) -> None:
    scoped["remote_links:SHOP-12"].respond(
        json=_links(f"{ENDPOINT}/team/svc/-/merge_requests/13", f"{ENDPOINT}/team/svc/-/merge_requests/14")
    )
    scoped.get(f"{SERVICE_API}/merge_requests/13").respond(json=merge_request(13, "WIP", state="opened"))
    scoped.get(f"{SERVICE_API}/merge_requests/14").respond(
        json=merge_request(14, "Backport", target_branch="release/1.x", merge_commit_sha="bp")
    )

    service: typing.Final = _service(_scope())

    assert service.rows == []
    assert service.release is not None
    assert service.release.state == "not_merged"
    assert [item.iid for item in service.release.pending_merge_requests] == [13]
    assert service.warnings == ["!14 was merged into release/1.x, not main."]


@pytest.mark.httpx2(assert_all_called=False)
def test_linked_commit_on_the_default_branch_is_a_target(scoped: respx.Router) -> None:
    scoped["commits"].respond(json=[commit("abcdef1234", "Hotfix", date="2026-09-25T00:00:00Z"), *COMMITS[1:]])
    scoped.get(f"{SERVICE_API}/repository/commits/abcdef1234/merge_requests").respond(json=[])
    scoped["remote_links:SHOP-12"].respond(json=_links(f"{ENDPOINT}/team/svc/-/commit/abcdef1"))

    service: typing.Final = _service(_scope())

    assert len(service.rows) == 5
    assert service.rows[0].linked
    assert service.release is not None
    assert (service.release.state, service.release.tag) == ("pending", None)


@pytest.mark.httpx2(assert_all_called=False)
def test_linked_commit_outside_the_range_is_not_found(scoped: respx.Router) -> None:
    scoped["remote_links:SHOP-12"].respond(json=_links(f"{ENDPOINT}/team/svc/-/commit/fedcba9"))

    service: typing.Final = _service(_scope())

    assert service.rows == []
    assert service.release is not None
    assert service.release.state == "not_found"


@pytest.mark.httpx2(assert_all_called=False)
def test_scope_issues_and_row_issues_are_both_read(scoped: respx.Router) -> None:
    report: typing.Final = _scope()

    assert report.jira is not None
    assert sorted(report.jira.issues) == ["SHOP-12"]
    assert report.jira.missing == ["SHOP-13"]
    assert report.jira.issues["SHOP-12"].url == f"{JIRA_ENDPOINT}/browse/SHOP-12"
    assert scoped["jira_search"].call_count == 2
    assert scoped["remote_links:SHOP-12"].call_count == 1


@pytest.mark.httpx2(assert_all_called=False)
def test_missing_scope_issue_yields_no_services(scoped: respx.Router) -> None:
    report: typing.Final = _scope("SHOP-404")

    assert report.services == []
    assert report.jira is not None
    assert report.jira.missing == ["SHOP-404"]
    assert scoped["jira_search"].call_count == 1


@pytest.mark.httpx2(assert_all_called=False)
def test_scope_stops_when_jira_fails(scoped: respx.Router) -> None:
    scoped["jira_search"].respond(401)

    report: typing.Final = _scope()

    assert report.services == []
    assert report.jira is not None
    assert report.jira.error is not None


@pytest.mark.httpx2(assert_all_called=False)
def test_merged_merge_request_is_cached(scoped: respx.Router) -> None:
    cache: typing.Final = Cache()
    _scope(cache=cache)

    _scope(cache=Cache(previous=cache.current))

    assert scoped["mr:12"].call_count == 1


@pytest.mark.httpx2(assert_all_called=False)
def test_a_failing_scoped_service_keeps_the_others(scoped: respx.Router) -> None:
    scoped["mr:12"].respond(500)

    report: typing.Final = _scope()

    assert _service(report).error == "team/svc: GitLab returned 500 for merge requests."
