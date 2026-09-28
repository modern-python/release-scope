import typing

import httpware
import pydantic
import pytest

from release_scope._cache import Cache
from release_scope._errors import AuthError, GitLabError
from release_scope._gitlab import GitLabApi
from release_scope._report import Report, Service
from release_scope._settings import GitLabConfig, Settings
from release_scope._use_case import CollectUseCase
from tests.conftest import GitLab
from tests.gitlab_mock import API, ENDPOINT, ServiceData, commit, fail_everything, fail_service


pytestmark = pytest.mark.httpx2(assert_all_called=False)


def _settings(**overrides: typing.Any) -> Settings:  # noqa: ANN401
    values: dict[str, typing.Any] = {
        "gitlab": GitLabConfig(endpoint=ENDPOINT, token=pydantic.SecretStr("t")),
        "environments": ["preview"],
        "jira_endpoint": "https://jira.example.test/",
        "jira_project_keys": ["SHOP"],
        **overrides,
    }
    return Settings(**values)


def _collect(
    cache: Cache | None = None,
    *,
    groups: tuple[str, ...] = ("team",),
    projects: tuple[str, ...] = (),
    **overrides: typing.Any,  # noqa: ANN401
) -> Report:
    use_case: typing.Final = CollectUseCase(
        api=GitLabApi(http=httpware.Client(base_url=ENDPOINT)), settings=_settings(**overrides)
    )
    return use_case(groups=groups, projects=projects, include_subgroups=False, cache=cache or Cache())


def _only_service(report: Report) -> Service:
    assert len(report.services) == 1
    return report.services[0]


@pytest.mark.usefixtures("gitlab")
def test_rows_run_from_newest_commit_down_to_production() -> None:
    service: typing.Final = _only_service(_collect())

    assert [[item.sha for item in row.commits] for row in service.rows] == [
        ["head"],
        ["c3"],
        ["c2"],
        ["c1"],
        ["c0b", "c0a"],
    ]
    assert [row.kind for row in service.rows] == ["commit", *["merge_request"] * 4]
    assert [[item.iid for item in row.merge_requests] for row in service.rows] == [[], [12], [11], [10], [9]]
    assert [item.name for item in service.environments] == ["production", "preview"]
    assert service.environments[0].deployment_url == f"{ENDPOINT}/team/svc/-/jobs/70"
    assert service.environments[1].deployment_url is None
    assert service.warnings == []


@pytest.mark.usefixtures("gitlab")
def test_only_rows_holding_a_deployed_commit_name_the_environment() -> None:
    service: typing.Final = _only_service(_collect())

    assert [row.environments for row in service.rows] == [[], ["preview"], [], [], []]


@pytest.mark.usefixtures("gitlab")
def test_tags_carry_their_latest_pipeline() -> None:
    rows: typing.Final = _only_service(_collect()).rows

    assert [[tag.name for tag in row.tags] for row in rows] == [[], ["1.2.0"], [], ["1.1.0"], []]
    tagged, untagged_pipeline = rows[1].tags[0], rows[3].tags[0]
    assert tagged.url == f"{ENDPOINT}/team/svc/-/tags/1.2.0"
    assert tagged.pipeline is not None
    assert tagged.pipeline.id == 201
    assert untagged_pipeline.pipeline is None


@pytest.mark.usefixtures("gitlab")
def test_main_pipeline_is_the_latest_push_pipeline_with_its_failed_jobs() -> None:
    rows: typing.Final = _only_service(_collect()).rows

    assert [row.main_pipeline.id if row.main_pipeline else None for row in rows] == [104, 103, 102, None, None]
    failed_on_c3: typing.Final = rows[1].main_pipeline.failed_jobs if rows[1].main_pipeline else []
    assert [(item.kind, item.name) for item in failed_on_c3] == [
        ("job", "lint"),
        ("bridge", "appsec"),
        ("bridge", "docs"),
    ]
    assert failed_on_c3[1].downstream_pipeline_url == f"{ENDPOINT}/team/svc/-/pipelines/9"
    assert failed_on_c3[2].downstream_pipeline_url is None
    allowed: typing.Final = rows[2].main_pipeline.failed_jobs if rows[2].main_pipeline else []
    assert [(item.name, item.allow_failure) for item in allowed] == [("flaky", True)]


@pytest.mark.usefixtures("gitlab")
def test_jira_keys_come_from_merge_requests_or_commit_messages() -> None:
    rows: typing.Final = _only_service(_collect()).rows

    assert [[key.key for key in row.jira_keys] for row in rows] == [["SHOP-9"], ["SHOP-12", "SHOP-13"], [], [], []]
    assert rows[1].jira_keys[0].url == "https://jira.example.test/browse/SHOP-12"


@pytest.mark.usefixtures("gitlab")
def test_jira_keys_have_no_url_without_a_jira_endpoint() -> None:
    rows: typing.Final = _only_service(_collect(jira_endpoint=None, jira_project_keys=[])).rows

    assert [(key.key, key.url) for key in rows[1].jira_keys] == [("SHOP-12", None), ("SHOP-13", None), ("OPS-1", None)]
    assert [key.key for key in rows[2].jira_keys] == ["UTF-8"]


@pytest.mark.usefixtures("gitlab")
def test_merge_request_author_falls_back_to_nothing() -> None:
    rows: typing.Final = _only_service(_collect()).rows

    assert rows[1].merge_requests[0].author == "dev"
    assert rows[3].merge_requests[0].author is None


def test_second_run_reuses_settled_facts_from_the_cache(gitlab: GitLab) -> None:
    cache: typing.Final = Cache()
    first: typing.Final = _collect(cache)
    gitlab.router.reset()

    second: typing.Final = _collect(Cache(previous=cache.current))

    jobs_requested: typing.Final = {call.request.url.path for call in gitlab.router["1:jobs"].calls}
    assert gitlab.router["1:commit_mrs"].call_count == 0
    assert jobs_requested == {"/api/v4/projects/1/pipelines/104/jobs"}
    assert second.services == first.services


def test_cache_drops_a_pipeline_once_its_updated_at_moves(gitlab: GitLab) -> None:
    cache: typing.Final = Cache()
    _collect(cache)
    gitlab.service.push_pipelines[1]["updated_at"] = "2026-09-28T00:00:00Z"
    gitlab.router.reset()

    _collect(Cache(previous=cache.current))

    jobs_requested: typing.Final = {call.request.url.path for call in gitlab.router["1:jobs"].calls}
    assert jobs_requested == {"/api/v4/projects/1/pipelines/103/jobs", "/api/v4/projects/1/pipelines/104/jobs"}


def test_a_failing_service_keeps_its_cache_and_does_not_stop_the_others(gitlab: GitLab) -> None:
    cache: typing.Final = Cache()
    _collect(cache)
    gitlab.add_failing_service(ServiceData(id=2, path="team/broken"), 500)
    fail_service(gitlab.router, gitlab.service, 502)
    next_cache: typing.Final = Cache(previous=cache.current)

    report: typing.Final = _collect(next_cache)

    assert [(item.project, item.error) for item in report.services] == [
        ("team/broken", "GitLab returned 500 for /api/v4/projects/2/deployments."),
        ("team/svc", "GitLab returned 502 for /api/v4/projects/1/deployments."),
    ]
    assert next_cache.current.pipelines["1"] == cache.current.pipelines["1"]


def test_authentication_failure_stops_the_run(gitlab: GitLab) -> None:
    fail_everything(gitlab.router, 401)

    with pytest.raises(AuthError, match="401"):
        _collect()


def test_unknown_project_stops_the_run(gitlab: GitLab) -> None:
    gitlab.router.get(f"{API}/projects/team%2Fmissing").respond(404)

    with pytest.raises(GitLabError, match="404"):
        _collect(groups=(), projects=("team/missing",))


@pytest.mark.usefixtures("gitlab")
def test_project_listed_twice_is_collected_once() -> None:
    report: typing.Final = _collect(projects=("team/svc",))

    assert [item.project for item in report.services] == ["team/svc"]


def test_service_without_production_deployment_has_no_rows(gitlab: GitLab) -> None:
    del gitlab.service.deployments["production"]

    service: typing.Final = _only_service(_collect())

    assert service.rows == []
    assert service.warnings == ["No successful deployment to 'production'."]


def test_service_without_default_branch_has_no_rows(gitlab: GitLab) -> None:
    gitlab.service.default_branch = None

    service: typing.Final = _only_service(_collect())

    assert service.rows == []
    assert service.warnings == ["Project has no default branch."]


def test_service_already_on_production_has_no_rows(gitlab: GitLab) -> None:
    gitlab.service.commits = []

    service: typing.Final = _only_service(_collect())

    assert service.rows == []
    assert service.warnings == []


def test_long_range_is_truncated_with_a_warning(gitlab: GitLab) -> None:
    gitlab.paging.per_page = 2

    service: typing.Final = _only_service(_collect(max_commits=2))

    assert [row.commits[0].sha for row in service.rows] == ["head", "c3"]
    assert service.warnings == ["Stopped after 2 commits; older changes are omitted."]


@pytest.mark.usefixtures("gitlab")
def test_range_page_larger_than_the_limit_is_trimmed() -> None:
    service: typing.Final = _only_service(_collect(max_commits=3))

    assert [row.commits[0].sha for row in service.rows] == ["head", "c3", "c2"]
    assert service.warnings == ["Stopped after 3 commits; older changes are omitted."]


def test_long_tag_list_is_truncated_with_a_warning(gitlab: GitLab) -> None:
    gitlab.paging.per_page = 1
    gitlab.service.tags.extend({"name": f"0.0.{n}", "commit": {"id": f"old{n}"}} for n in range(100))

    service: typing.Final = _only_service(_collect())

    assert service.warnings == ["Tag list was truncated; some tags may be missing from rows."]


def test_commit_without_message_uses_its_title_for_jira_keys(gitlab: GitLab) -> None:
    gitlab.service.commits[0] = commit("head", "SHOP-77 fix", date="2026-09-25T00:00:00Z", message="")

    rows: typing.Final = _only_service(_collect()).rows

    assert [key.key for key in rows[0].jira_keys] == ["SHOP-77"]
