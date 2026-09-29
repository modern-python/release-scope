import typing


ENDPOINT: typing.Final = "https://gitlab.example.test"
API: typing.Final = f"{ENDPOINT}/api/v4"
SERVICE_API: typing.Final = f"{API}/projects/1"
JIRA_ENDPOINT: typing.Final = "https://jira.example.test"
JIRA_SEARCH: typing.Final = f"{JIRA_ENDPOINT}/rest/api/2/search"


def project(
    project_id: int,
    path: str,
    *,
    default_branch: str | None = "main",
    **fields: typing.Any,  # noqa: ANN401
) -> dict[str, typing.Any]:
    return {
        "id": project_id,
        "path_with_namespace": path,
        "web_url": f"{ENDPOINT}/{path}",
        "default_branch": default_branch,
        **fields,
    }


def commit(sha: str, title: str, *, date: str, message: str | None = None) -> dict[str, typing.Any]:
    return {
        "id": sha,
        "short_id": sha[:8],
        "title": title,
        "message": message if message is not None else title,
        "author_name": "Dev",
        "committed_date": date,
        "web_url": f"{ENDPOINT}/team/svc/-/commit/{sha}",
    }


def merge_request(iid: int, title: str, **fields: typing.Any) -> dict[str, typing.Any]:  # noqa: ANN401
    return {
        "iid": iid,
        "title": title,
        "description": None,
        "source_branch": f"branch-{iid}",
        "target_branch": "main",
        "state": "merged",
        "web_url": f"{ENDPOINT}/team/svc/-/merge_requests/{iid}",
        "merged_at": "2026-09-20T10:00:00Z",
        "author": {"username": "dev", "name": "Dev"},
        **fields,
    }


def pipeline(pipeline_id: int, sha: str, ref: str, status: str, *, updated_at: str) -> dict[str, typing.Any]:
    return {
        "id": pipeline_id,
        "sha": sha,
        "ref": ref,
        "status": status,
        "web_url": f"{ENDPOINT}/team/svc/-/pipelines/{pipeline_id}",
        "updated_at": updated_at,
    }


def job(name: str, *, allow_failure: bool = False, **fields: typing.Any) -> dict[str, typing.Any]:  # noqa: ANN401
    return {
        "name": name,
        "stage": "test",
        "status": "failed",
        "allow_failure": allow_failure,
        "web_url": f"{ENDPOINT}/team/svc/-/jobs/{name}",
        "failure_reason": "script_failure",
        **fields,
    }


SERVICE: typing.Final = project(1, "team/svc")
PRODUCTION_DEPLOYMENT: typing.Final = {
    "id": 7,
    "ref": "1.0.0",
    "sha": "prod",
    "created_at": "2026-09-01T00:00:00Z",
    "deployable": {"web_url": f"{ENDPOINT}/team/svc/-/jobs/70"},
}
PREVIEW_DEPLOYMENT: typing.Final = {
    "id": 8,
    "ref": "1.2.0",
    "sha": "c3",
    "created_at": "2026-09-22T00:00:00Z",
    "deployable": None,
}
COMMITS: typing.Final = [
    commit("head", "SHOP-9 hotfix typo", date="2026-09-25T00:00:00Z"),
    commit("c3", "Merge branch 'branch-12'", date="2026-09-22T00:00:00Z"),
    commit("c2", "Merge branch 'branch-11'", date="2026-09-21T00:00:00Z"),
    commit("c1", "Feature ten", date="2026-09-20T00:00:00Z"),
    commit("c0b", "Part two", date="2026-09-19T00:00:00Z"),
    commit("c0a", "Part one", date="2026-09-18T00:00:00Z"),
]
TAGS: typing.Final = [
    {"name": "1.2.0", "commit": {"id": "c3"}},
    {"name": "1.1.0", "commit": {"id": "c1"}},
    {"name": "1.0.0", "commit": {"id": "prod"}},
]
MERGED_MERGE_REQUESTS: typing.Final = [
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
]
COMMIT_MERGE_REQUESTS: typing.Final = {
    "head": [merge_request(40, "Open elsewhere", state="opened", target_branch="feature")],
    "c0b": [merge_request(9, "Two-part change", sha="c0b")],
    "c0a": [merge_request(9, "Two-part change", sha="c0b")],
}
PUSH_PIPELINES: typing.Final = [
    pipeline(104, "head", "main", "running", updated_at="2026-09-25T01:00:00Z"),
    pipeline(103, "c3", "main", "failed", updated_at="2026-09-22T01:00:00Z"),
    pipeline(102, "c2", "main", "success", updated_at="2026-09-21T02:00:00Z"),
    pipeline(101, "c2", "main", "failed", updated_at="2026-09-21T01:00:00Z"),
]
TAG_PIPELINES: typing.Final = {
    "1.2.0": [pipeline(201, "c3", "1.2.0", "success", updated_at="2026-09-22T02:00:00Z")],
    "1.1.0": [],
}
FAILED_JOBS: typing.Final = {
    104: [job("unit")],
    103: [job("lint")],
    102: [job("flaky", allow_failure=True)],
    201: [],
}
FAILED_BRIDGES: typing.Final = {
    104: [],
    103: [
        job("appsec", stage="security", downstream_pipeline={"web_url": f"{ENDPOINT}/team/svc/-/pipelines/9"}),
        job("docs", downstream_pipeline=None),
    ],
    102: [],
    201: [],
}


def jira_issue(
    key: str, summary: str, *, status: str = "In Progress", category: str = "indeterminate"
) -> dict[str, typing.Any]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status, "statusCategory": {"key": category}},
            "issuetype": {"name": "Task"},
        },
    }


def jira_page(*issues: dict[str, typing.Any], start_at: int = 0, total: int | None = None) -> dict[str, typing.Any]:
    return {
        "startAt": start_at,
        "maxResults": 100,
        "total": len(issues) if total is None else total,
        "issues": list(issues),
    }


JIRA_ISSUES: typing.Final = [
    jira_issue("SHOP-9", "Fix typo", status="Done", category="done"),
    jira_issue("SHOP-12", "New endpoint"),
]
