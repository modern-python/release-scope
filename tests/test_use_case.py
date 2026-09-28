import typing

import httpcore2
import httpware
import httpx
import pydantic
import pytest
import respx

from release_scope._cache import Cache
from release_scope._errors import AuthError, GitLabError
from release_scope._gitlab import GitLabApi
from release_scope._report import Report, Service
from release_scope._settings import GitLabConfig, Settings
from release_scope._use_case import CollectUseCase
from tests.payloads import API, COMMITS, ENDPOINT, PUSH_PIPELINES, SERVICE, commit, pipeline, project


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


def test_second_run_reuses_settled_facts_from_the_cache(gitlab: respx.Router) -> None:
    cache: typing.Final = Cache()
    first: typing.Final = _collect(cache)

    second: typing.Final = _collect(Cache(previous=cache.current))

    assert second.services == first.services
    assert [gitlab[f"commit_mrs:{sha}"].call_count for sha in ("head", "c0b", "c0a")] == [1, 1, 1]
    assert [gitlab[f"jobs:{pipeline_id}"].call_count for pipeline_id in (104, 103, 102, 201)] == [2, 1, 1, 1]


def test_cache_drops_a_pipeline_once_its_updated_at_moves(gitlab: respx.Router) -> None:
    cache: typing.Final = Cache()
    _collect(cache)
    retried: typing.Final = pipeline(103, "c3", "main", "failed", updated_at="2026-09-28T00:00:00Z")
    gitlab["push_pipelines"].respond(json=[PUSH_PIPELINES[0], retried, *PUSH_PIPELINES[2:]])

    _collect(Cache(previous=cache.current))

    assert [gitlab[f"jobs:{pipeline_id}"].call_count for pipeline_id in (104, 103, 102)] == [2, 2, 1]


def test_a_failing_service_keeps_its_cache_and_does_not_stop_the_others(gitlab: respx.Router) -> None:
    cache: typing.Final = Cache()
    _collect(cache)
    gitlab["group"].respond(json=[SERVICE, project(2, "team/broken")])
    gitlab.get(f"{API}/projects/2/deployments").respond(500)
    gitlab["deploy:production"].respond(502)
    next_cache: typing.Final = Cache(previous=cache.current)

    report: typing.Final = _collect(next_cache)

    assert [(item.project, item.error) for item in report.services] == [
        ("team/broken", "team/broken: GitLab returned 500 for deployments."),
        ("team/svc", "team/svc: GitLab returned 502 for deployments."),
    ]
    assert next_cache.current.pipelines["1"] == cache.current.pipelines["1"]


def test_forbidden_deployments_fail_only_that_service_and_say_where_to_look(gitlab: respx.Router) -> None:
    gitlab["group"].respond(json=[SERVICE, project(2, "team/nodeploy")])
    gitlab.get(f"{API}/projects/2/deployments").respond(403)
    settings: typing.Final = f"{ENDPOINT}/team/nodeploy/edit#js-shared-permissions"

    report: typing.Final = _collect()

    assert [item.project for item in report.services] == ["team/nodeploy", "team/svc"]
    assert report.services[0].error == (
        "team/nodeploy: GitLab denied access to deployments (403). Check that:\n"
        f"- Environments are enabled: {settings} → Visibility, project features, permissions → Environments\n"
        f"- CI/CD is enabled: {settings} → Visibility, project features, permissions → CI/CD\n"
        f"- the token's user has a role that can read them: {ENDPOINT}/team/nodeploy/-/project_members"
    )
    assert len(report.services[1].rows) == 5


@pytest.mark.httpx2(assert_all_called=False)
@pytest.mark.parametrize(
    ("route", "resource", "feature", "enabled"),
    [
        ("commits", "the repository", "Repository", "Repository is enabled"),
        ("merged_mrs", "merge requests", "Merge requests", "Merge requests are enabled"),
        ("push_pipelines", "pipelines", "CI/CD", "CI/CD is enabled"),
    ],
)
def test_forbidden_resource_lists_the_feature_that_guards_it(
    gitlab: respx.Router, route: str, resource: str, feature: str, enabled: str
) -> None:
    gitlab[route].respond(403)
    settings: typing.Final = f"{ENDPOINT}/team/svc/edit#js-shared-permissions"

    error: typing.Final = _only_service(_collect()).error

    assert error == (
        f"team/svc: GitLab denied access to {resource} (403). Check that:\n"
        f"- {enabled}: {settings} → Visibility, project features, permissions → {feature}\n"
        f"- the token's user has a role that can read them: {ENDPOINT}/team/svc/-/project_members"
    )


@pytest.mark.httpx2(assert_all_called=False)
def test_forbidden_commit_lookup_points_at_merge_requests(gitlab: respx.Router) -> None:
    gitlab["commit_mrs:head"].respond(403)

    error: typing.Final = _only_service(_collect()).error

    assert error is not None
    assert error.startswith("team/svc: GitLab denied access to merge requests (403). Check that:\n- Merge requests are")


def test_forbidden_project_stops_the_run(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{API}/projects/team%2Fsecret").respond(403)

    with pytest.raises(AuthError, match=r"GitLab denied access to project 'team/secret' \(403\)"):
        _collect(groups=(), projects=("team/secret",))


@pytest.mark.httpx2(assert_all_called=False)
def test_network_failure_names_the_project(gitlab: respx.Router) -> None:
    gitlab["tags"].mock(side_effect=httpcore2.ConnectError("down"))

    assert _only_service(_collect()).error == "team/svc: GitLab request for the repository failed (NetworkError)."


_LIB_FEATURES: typing.Final = (
    f"{ENDPOINT}/team/lib/edit#js-shared-permissions → Visibility, project features, permissions"
)


@pytest.mark.parametrize(
    ("access_levels", "warning"),
    [
        (
            {"environments_access_level": "disabled"},
            f"Environments are disabled, so it has no deployments. Enable them at {_LIB_FEATURES} → Environments.",
        ),
        (
            {"builds_access_level": "disabled"},
            f"CI/CD is disabled, so it has no pipelines or deployments. Enable it at {_LIB_FEATURES} → CI/CD.",
        ),
    ],
)
def test_project_without_deployments_is_skipped_with_a_warning(
    gitlab: respx.Router, access_levels: dict[str, str], warning: str
) -> None:
    gitlab["group"].respond(json=[SERVICE, project(2, "team/lib", **access_levels)])

    report: typing.Final = _collect()

    skipped: typing.Final = report.services[0]
    assert (skipped.project, skipped.rows, skipped.error, skipped.warnings) == ("team/lib", [], None, [warning])
    assert len(report.services[1].rows) == 5


def test_enabled_or_private_features_are_collected(gitlab: respx.Router) -> None:
    gitlab["group"].respond(
        json=[project(1, "team/svc", environments_access_level="private", builds_access_level="enabled")]
    )

    assert len(_only_service(_collect()).rows) == 5


def test_forbidden_group_stops_the_run(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{API}/groups/team/projects").respond(403)

    with pytest.raises(AuthError, match=r"GitLab denied access to group 'team' \(403\)"):
        _collect()


def test_authentication_failure_stops_the_run(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{API}/groups/team/projects").respond(401)

    with pytest.raises(AuthError, match="401"):
        _collect()


def test_unknown_project_stops_the_run(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{API}/projects/team%2Fmissing").respond(404)

    with pytest.raises(GitLabError, match="404"):
        _collect(groups=(), projects=("team/missing",))


def test_project_listed_twice_is_collected_once(gitlab: respx.Router) -> None:
    gitlab.get(f"{API}/projects/team%2Fsvc").respond(json=SERVICE)

    report: typing.Final = _collect(projects=("team/svc",))

    assert [item.project for item in report.services] == ["team/svc"]


@pytest.mark.httpx2(assert_all_called=False)
def test_service_without_production_deployment_has_no_rows(gitlab: respx.Router) -> None:
    gitlab["deploy:production"].respond(json=[])

    service: typing.Final = _only_service(_collect())

    assert service.rows == []
    assert service.warnings == ["No successful deployment to 'production'."]


@pytest.mark.httpx2(assert_all_called=False)
def test_service_without_default_branch_has_no_rows(gitlab: respx.Router) -> None:
    gitlab["group"].respond(json=[project(1, "team/svc", default_branch=None)])

    service: typing.Final = _only_service(_collect())

    assert service.rows == []
    assert service.warnings == ["Project has no default branch."]


@pytest.mark.httpx2(assert_all_called=False)
def test_service_already_on_production_has_no_rows(gitlab: respx.Router) -> None:
    gitlab["commits"].respond(json=[])

    service: typing.Final = _only_service(_collect())

    assert service.rows == []
    assert service.warnings == []


def test_range_spanning_pages_is_read_to_the_end(gitlab: respx.Router) -> None:
    gitlab["commits"].side_effect = [
        httpx.Response(200, json=COMMITS[:3], headers={"x-next-page": "2"}),
        httpx.Response(200, json=COMMITS[3:]),
    ]

    service: typing.Final = _only_service(_collect())

    assert len(service.rows) == 5
    assert [call.request.url.params["page"] for call in gitlab["commits"].calls] == ["1", "2"]


@pytest.mark.httpx2(assert_all_called=False)
def test_long_range_is_truncated_with_a_warning(gitlab: respx.Router) -> None:
    gitlab["commits"].respond(json=COMMITS[:2], headers={"x-next-page": "2"})

    service: typing.Final = _only_service(_collect(max_commits=2))

    assert [row.commits[0].sha for row in service.rows] == ["head", "c3"]
    assert service.warnings == ["Stopped after 2 commits; older changes are omitted."]
    assert gitlab["commits"].call_count == 1


@pytest.mark.httpx2(assert_all_called=False)
def test_range_page_larger_than_the_limit_is_trimmed(gitlab: respx.Router) -> None:
    service: typing.Final = _only_service(_collect(max_commits=3))

    assert [row.commits[0].sha for row in service.rows] == ["head", "c3", "c2"]
    assert service.warnings == ["Stopped after 3 commits; older changes are omitted."]
    assert gitlab["commits"].call_count == 1


@pytest.mark.httpx2(assert_all_called=False)
def test_long_tag_list_is_truncated_with_a_warning(gitlab: respx.Router) -> None:
    gitlab["tags"].respond(json=[{"name": "0.0.1", "commit": {"id": "old"}}], headers={"x-next-page": "2"})

    service: typing.Final = _only_service(_collect())

    assert service.warnings == ["Tag list was truncated; some tags may be missing from rows."]
    assert gitlab["tags"].call_count == 50


def test_commit_without_message_uses_its_title_for_jira_keys(gitlab: respx.Router) -> None:
    gitlab["commits"].respond(
        json=[commit("head", "SHOP-77 fix", date="2026-09-25T00:00:00Z", message=""), *COMMITS[1:]]
    )

    rows: typing.Final = _only_service(_collect()).rows

    assert [key.key for key in rows[0].jira_keys] == ["SHOP-77"]
