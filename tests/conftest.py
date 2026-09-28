import dataclasses
import typing

import pytest
import respx

from tests.gitlab_mock import (
    ENDPOINT,
    Paging,
    ServiceData,
    commit,
    fail_service,
    job,
    merge_request,
    mock_group,
    mock_service,
    pipeline,
)


_SETTINGS_ENV: typing.Final = (
    "GITLAB_TOKEN",
    "RELEASE_SCOPE_GITLAB__TOKEN",
    "RELEASE_SCOPE_GITLAB__ENDPOINT",
    "RELEASE_SCOPE_JIRA_ENDPOINT",
    "RELEASE_SCOPE_JIRA_PROJECT_KEYS",
    "RELEASE_SCOPE_ENVIRONMENTS",
    "RELEASE_SCOPE_PRODUCTION_ENVIRONMENT",
    "RELEASE_SCOPE_REQUEST_TIMEOUT",
    "RELEASE_SCOPE_MAX_COMMITS",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV:
        monkeypatch.delenv(name, raising=False)


def build_service() -> ServiceData:
    return ServiceData(
        id=1,
        path="team/svc",
        deployments={
            "production": {
                "id": 7,
                "ref": "1.0.0",
                "sha": "prod",
                "created_at": "2026-09-01T00:00:00Z",
                "deployable": {"web_url": f"{ENDPOINT}/team/svc/-/jobs/70"},
            },
            "preview": {"id": 8, "ref": "1.2.0", "sha": "c3", "created_at": "2026-09-22T00:00:00Z", "deployable": None},
        },
        commits=[
            commit("head", "SHOP-9 hotfix typo", date="2026-09-25T00:00:00Z"),
            commit("c3", "Merge branch 'branch-12'", date="2026-09-22T00:00:00Z"),
            commit("c2", "Merge branch 'branch-11'", date="2026-09-21T00:00:00Z"),
            commit("c1", "Feature ten", date="2026-09-20T00:00:00Z"),
            commit("c0b", "Part two", date="2026-09-19T00:00:00Z"),
            commit("c0a", "Part one", date="2026-09-18T00:00:00Z"),
        ],
        tags=[
            {"name": "1.2.0", "commit": {"id": "c3"}},
            {"name": "1.1.0", "commit": {"id": "c1"}},
            {"name": "1.0.0", "commit": {"id": "prod"}},
        ],
        merged_merge_requests=[
            merge_request(
                12,
                "SHOP-12 new endpoint",
                merge_commit_sha="c3",
                sha="x12",
                source_branch="feature/SHOP-12_endpoint",
                description="Relates to SHOP-13 and OPS-1",
            ),
            merge_request(11, "Bump UTF-8 handling", merge_commit_sha="c2", sha="x11"),
            merge_request(10, "Feature ten", squash_commit_sha="c1", sha="x10", author=None),
        ],
        commit_merge_requests={
            "head": [merge_request(40, "Open elsewhere", state="opened", target_branch="feature")],
            "c0b": [merge_request(9, "Two-part change", sha="c0b")],
            "c0a": [merge_request(9, "Two-part change", sha="c0b")],
        },
        push_pipelines=[
            pipeline(104, "head", "main", "running"),
            pipeline(103, "c3", "main", "failed"),
            pipeline(102, "c2", "main", "success"),
            pipeline(101, "c2", "main", "failed"),
        ],
        tag_pipelines={"1.2.0": pipeline(201, "c3", "1.2.0", "success")},
        failed_jobs={103: [job("lint")], 102: [job("flaky", allow_failure=True)], 104: [job("unit")]},
        failed_bridges={
            103: [
                job("appsec", stage="security", downstream_pipeline={"web_url": f"{ENDPOINT}/team/svc/-/pipelines/9"}),
                job("docs", downstream_pipeline=None),
            ]
        },
    )


@dataclasses.dataclass(kw_only=True)
class GitLab:
    router: respx.Router
    service: ServiceData
    group: list[ServiceData]
    paging: Paging

    def add_failing_service(self, data: ServiceData, status: int) -> None:
        self.group.append(data)
        mock_service(self.router, data, self.paging)
        fail_service(self.router, data, status)


@pytest.fixture
def gitlab(httpx2_mock: respx.Router) -> GitLab:
    paging: typing.Final = Paging()
    service: typing.Final = build_service()
    group: typing.Final = [service]
    mock_group(httpx2_mock, "team", group, paging)
    mock_service(httpx2_mock, service, paging)
    return GitLab(router=httpx2_mock, service=service, group=group, paging=paging)
