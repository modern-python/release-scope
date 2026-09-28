import typing

import pydantic
import pytest

from release_scope._cache import Cache
from release_scope._errors import AuthError, GitLabError
from release_scope._gitlab import GitLabApi
from release_scope._report import Report, Service
from release_scope._settings import GitLabConfig, Settings
from release_scope._use_case import CollectUseCase
from tests.fake_gitlab import ENDPOINT, FakeGitLab, FakeProject, commit


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
    fake: FakeGitLab,
    cache: Cache | None = None,
    *,
    groups: tuple[str, ...] = ("team",),
    projects: tuple[str, ...] = (),
    **overrides: typing.Any,  # noqa: ANN401
) -> Report:
    use_case: typing.Final = CollectUseCase(api=GitLabApi(http=fake.client()), settings=_settings(**overrides))
    return use_case(groups=groups, projects=projects, include_subgroups=False, cache=cache or Cache())


def _only_service(report: Report) -> Service:
    assert len(report.services) == 1
    return report.services[0]


def test_rows_run_from_newest_commit_down_to_production(fake_gitlab: FakeGitLab) -> None:
    service: typing.Final = _only_service(_collect(fake_gitlab))

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


def test_only_rows_holding_a_deployed_commit_name_the_environment(fake_gitlab: FakeGitLab) -> None:
    service: typing.Final = _only_service(_collect(fake_gitlab))

    assert [row.environments for row in service.rows] == [[], ["preview"], [], [], []]


def test_tags_carry_their_latest_pipeline(fake_gitlab: FakeGitLab) -> None:
    rows: typing.Final = _only_service(_collect(fake_gitlab)).rows

    assert [[tag.name for tag in row.tags] for row in rows] == [[], ["1.2.0"], [], ["1.1.0"], []]
    tagged, untagged_pipeline = rows[1].tags[0], rows[3].tags[0]
    assert tagged.url == f"{ENDPOINT}/team/svc/-/tags/1.2.0"
    assert tagged.pipeline is not None
    assert tagged.pipeline.id == 201
    assert untagged_pipeline.pipeline is None


def test_main_pipeline_is_the_latest_push_pipeline_with_its_failed_jobs(fake_gitlab: FakeGitLab) -> None:
    rows: typing.Final = _only_service(_collect(fake_gitlab)).rows

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


def test_jira_keys_come_from_merge_requests_or_commit_messages(fake_gitlab: FakeGitLab) -> None:
    rows: typing.Final = _only_service(_collect(fake_gitlab)).rows

    assert [[key.key for key in row.jira_keys] for row in rows] == [["SHOP-9"], ["SHOP-12", "SHOP-13"], [], [], []]
    assert rows[1].jira_keys[0].url == "https://jira.example.test/browse/SHOP-12"


def test_jira_keys_have_no_url_without_a_jira_endpoint(fake_gitlab: FakeGitLab) -> None:
    rows: typing.Final = _only_service(_collect(fake_gitlab, jira_endpoint=None, jira_project_keys=[])).rows

    assert [(key.key, key.url) for key in rows[1].jira_keys] == [("SHOP-12", None), ("SHOP-13", None), ("OPS-1", None)]
    assert [key.key for key in rows[2].jira_keys] == ["UTF-8"]


def test_merge_request_author_falls_back_to_nothing(fake_gitlab: FakeGitLab) -> None:
    rows: typing.Final = _only_service(_collect(fake_gitlab)).rows

    assert rows[1].merge_requests[0].author == "dev"
    assert rows[3].merge_requests[0].author is None


def test_second_run_reuses_settled_facts_from_the_cache(fake_gitlab: FakeGitLab) -> None:
    cache: typing.Final = Cache()
    first: typing.Final = _collect(fake_gitlab, cache)
    fake_gitlab.requests.clear()

    second: typing.Final = _collect(fake_gitlab, Cache(previous=cache.current))

    paths: typing.Final = fake_gitlab.paths()
    assert not any(path.endswith("/merge_requests") and "/commits/" in path for path in paths)
    assert "/api/v4/projects/1/pipelines/104/jobs" in paths
    assert "/api/v4/projects/1/pipelines/103/jobs" not in paths
    assert second.services == first.services


def test_cache_drops_a_pipeline_once_its_updated_at_moves(fake_gitlab: FakeGitLab) -> None:
    cache: typing.Final = Cache()
    _collect(fake_gitlab, cache)
    fake_gitlab.projects[0].push_pipelines[1]["updated_at"] = "2026-09-28T00:00:00Z"
    fake_gitlab.requests.clear()

    _collect(fake_gitlab, Cache(previous=cache.current))

    assert "/api/v4/projects/1/pipelines/103/jobs" in fake_gitlab.paths()


def test_a_failing_service_keeps_its_cache_and_does_not_stop_the_others(fake_gitlab: FakeGitLab) -> None:
    cache: typing.Final = Cache()
    _collect(fake_gitlab, cache)
    fake_gitlab.projects.append(FakeProject(id=2, path="team/broken", fail_with=500))
    fake_gitlab.groups["team"].append(2)
    fake_gitlab.projects[0].fail_with = 502
    next_cache: typing.Final = Cache(previous=cache.current)

    report: typing.Final = _collect(fake_gitlab, next_cache)

    assert [(item.project, item.error) for item in report.services] == [
        ("team/broken", "GitLab returned 500 for /api/v4/projects/2/deployments."),
        ("team/svc", "GitLab returned 502 for /api/v4/projects/1/deployments."),
    ]
    assert next_cache.current.pipelines["1"] == cache.current.pipelines["1"]


def test_authentication_failure_stops_the_run(fake_gitlab: FakeGitLab) -> None:
    fake_gitlab.status_override = 401

    with pytest.raises(AuthError, match="401"):
        _collect(fake_gitlab)


def test_unknown_project_stops_the_run(fake_gitlab: FakeGitLab) -> None:
    with pytest.raises(GitLabError, match="404"):
        _collect(fake_gitlab, groups=(), projects=("team/missing",))


def test_project_listed_twice_is_collected_once(fake_gitlab: FakeGitLab) -> None:
    report: typing.Final = _collect(fake_gitlab, projects=("team/svc",))

    assert [item.project for item in report.services] == ["team/svc"]


def test_service_without_production_deployment_has_no_rows(fake_gitlab: FakeGitLab) -> None:
    del fake_gitlab.projects[0].deployments["production"]

    service: typing.Final = _only_service(_collect(fake_gitlab))

    assert service.rows == []
    assert service.warnings == ["No successful deployment to 'production'."]


def test_service_without_default_branch_has_no_rows(fake_gitlab: FakeGitLab) -> None:
    fake_gitlab.projects[0].default_branch = None

    service: typing.Final = _only_service(_collect(fake_gitlab))

    assert service.rows == []
    assert service.warnings == ["Project has no default branch."]


def test_service_already_on_production_has_no_rows(fake_gitlab: FakeGitLab) -> None:
    fake_gitlab.projects[0].commits = []

    service: typing.Final = _only_service(_collect(fake_gitlab))

    assert service.rows == []
    assert service.warnings == []


def test_long_range_is_truncated_with_a_warning(fake_gitlab: FakeGitLab) -> None:
    fake_gitlab.per_page = 2

    service: typing.Final = _only_service(_collect(fake_gitlab, max_commits=2))

    assert [row.commits[0].sha for row in service.rows] == ["head", "c3"]
    assert service.warnings == ["Stopped after 2 commits; older changes are omitted."]


def test_range_page_larger_than_the_limit_is_trimmed(fake_gitlab: FakeGitLab) -> None:
    service: typing.Final = _only_service(_collect(fake_gitlab, max_commits=3))

    assert [row.commits[0].sha for row in service.rows] == ["head", "c3", "c2"]
    assert service.warnings == ["Stopped after 3 commits; older changes are omitted."]


def test_long_tag_list_is_truncated_with_a_warning(fake_gitlab: FakeGitLab) -> None:
    fake_gitlab.per_page = 1
    fake_gitlab.projects[0].tags.extend({"name": f"0.0.{n}", "commit": {"id": f"old{n}"}} for n in range(100))

    service: typing.Final = _only_service(_collect(fake_gitlab))

    assert service.warnings == ["Tag list was truncated; some tags may be missing from rows."]


def test_commit_without_message_uses_its_title_for_jira_keys(fake_gitlab: FakeGitLab) -> None:
    fake_gitlab.projects[0].commits[0] = commit("head", "SHOP-77 fix", date="2026-09-25T00:00:00Z", message="")

    rows: typing.Final = _only_service(_collect(fake_gitlab)).rows

    assert [key.key for key in rows[0].jira_keys] == ["SHOP-77"]
