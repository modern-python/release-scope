import datetime
import typing

from release_scope._render import render_markdown
from release_scope._report import (
    CommitRef,
    EnvironmentState,
    FailedJob,
    JiraKeyRef,
    MergeRequestRef,
    PipelineState,
    Report,
    Row,
    Service,
    TagRef,
)


_COLLECTED_AT: typing.Final = datetime.datetime(2026, 9, 29, 10, 15, tzinfo=datetime.UTC)
_WARNING: typing.Final = (
    "Environments are disabled, so it has no deployments. Enable them at "
    "https://g.test/acme/utils/edit#js-shared-permissions → Visibility, project features, permissions → Environments."
)


def _environment(name: str, ref: str, url: str | None = None) -> EnvironmentState:
    return EnvironmentState(
        name=name, ref=ref, sha=f"sha-{ref}", deployed_at="2026-09-20T00:00:00Z", deployment_url=url
    )


def _job(name: str, *, allow_failure: bool = False, downstream: str | None = None) -> FailedJob:
    return FailedJob(
        kind="bridge" if downstream else "job",
        name=name,
        stage="test",
        status="failed",
        allow_failure=allow_failure,
        url=f"https://g.test/j/{name}",
        failure_reason="script_failure",
        downstream_pipeline_url=downstream,
    )


def _pipeline(pipeline_id: int, status: str, *jobs: FailedJob) -> PipelineState:
    return PipelineState(id=pipeline_id, status=status, url=f"https://g.test/p/{pipeline_id}", failed_jobs=list(jobs))


def _merge_request(iid: int, title: str, author: str | None) -> MergeRequestRef:
    return MergeRequestRef(
        iid=iid, title=title, url=f"https://g.test/mr/{iid}", author=author, merged_at="2026-09-26T00:00:00Z"
    )


def _commit(sha: str, title: str) -> CommitRef:
    return CommitRef(
        sha=sha,
        short_sha=sha[:7],
        title=title,
        url=f"https://g.test/c/{sha}",
        author="J. Doe",
        committed_at=_COLLECTED_AT,
    )


def _report(*services: Service) -> Report:
    return Report(collected_at=_COLLECTED_AT, production_environment="prod", services=list(services))


_API: typing.Final = Service(
    project="acme/api",
    project_url="https://g.test/acme/api",
    default_branch="main",
    environments=[_environment("prod", "2.3.0", "https://g.test/d1"), _environment("preview", "2.4.0")],
    rows=[
        Row(
            kind="commit",
            tags=[],
            merge_requests=[],
            commits=[_commit("9ac01f2aaaa", "fix | <b>typo</b>")],
            jira_keys=[JiraKeyRef(key="SHOP-9", url="https://j.test/browse/SHOP-9")],
            environments=[],
            main_pipeline=_pipeline(5130, "running"),
        ),
        Row(
            kind="merge_request",
            tags=[
                TagRef(
                    name="2.4.0",
                    url="https://g.test/t/2.4.0",
                    pipeline=_pipeline(5120, "failed", _job("smoke")),
                )
            ],
            merge_requests=[
                _merge_request(311, "SHOP-140 [refund] endpoint", "jdoe"),
                _merge_request(312, "Second\nline", None),
            ],
            commits=[_commit("b72e41daaaa", "Merge branch 'feature/SHOP-140'")],
            jira_keys=[
                JiraKeyRef(key="SHOP-140", url="https://j.test/browse/SHOP-140"),
                JiraKeyRef(key="OPS-1", url=None),
            ],
            environments=["preview"],
            main_pipeline=_pipeline(
                5118,
                "failed",
                _job("lint", allow_failure=True),
                _job("appsec", downstream="https://g.test/p/9"),
            ),
        ),
        Row(
            kind="merge_request",
            tags=[TagRef(name="2.3.2", url="https://g.test/t/2.3.2", pipeline=None)],
            merge_requests=[_merge_request(305, "Old change", "asmith")],
            commits=[_commit("c0ffee0aaaa", "Old change")],
            jira_keys=[],
            environments=[],
            main_pipeline=None,
        ),
    ],
)
_BILLING: typing.Final = Service(
    project="acme/billing",
    project_url="https://g.test/acme/billing",
    default_branch="main",
    environments=[_environment("prod", "1.8.1", "https://g.test/d2")],
)
_BROKEN: typing.Final = Service(
    project="acme/broken",
    project_url="https://g.test/acme/broken",
    error=(
        "acme/broken: GitLab denied access to deployments (403). Check that:\n"
        "- Environments are enabled: https://g.test/acme/broken/edit\n"
        "- the token's user has a role that can read them: https://g.test/acme/broken/-/project_members"
    ),
)
_UTILS: typing.Final = Service(project="acme/utils", project_url="https://g.test/acme/utils", warnings=[_WARNING])


def test_page_lists_attention_first_and_collapses_up_to_date_services() -> None:
    page: typing.Final = render_markdown(_report(_API, _BILLING, _BROKEN, _UTILS))

    assert page.splitlines() == [
        "# Release scope",
        "",
        "Collected 2026-09-29 10:15 UTC. Changes run from the commit on `prod` to the head of the default branch.",
        "",
        "Legend: ✅ success · ❌ failed · 🔄 running · ⏭ canceled or skipped · ⚠️ needs attention",
        "",
        "| Service | prod | preview | Pending | Failed jobs |",
        "|---|---|---|---|---|",
        "| [acme/broken](https://g.test/acme/broken) | — | — | ❌ failed to collect |  |",
        "| [acme/utils](https://g.test/acme/utils) | — | — | ⚠️ see below |  |",
        (
            "| [acme/api](https://g.test/acme/api) | [2.3.0](https://g.test/d1) | 2.4.0 "
            "| 3 changes · untagged head | ❌ 2 |"
        ),
        "",
        "<details>",
        "<summary>1 service up to date</summary>",
        "",
        "| Service | prod |",
        "|---|---|",
        "| [acme/billing](https://g.test/acme/billing) | [1.8.1](https://g.test/d2) |",
        "",
        "</details>",
        "",
        "## acme/broken",
        "",
        "❌ acme/broken: GitLab denied access to deployments (403). Check that:",
        "- Environments are enabled: https://g.test/acme/broken/edit",
        "- the token's user has a role that can read them: https://g.test/acme/broken/-/project_members",
        "",
        "## acme/utils",
        "",
        f"⚠️ {_WARNING}",
        "",
        "## acme/api",
        "",
        "prod [2.3.0](https://g.test/d1) · preview 2.4.0 · 3 merge requests, 1 direct commit",
        "",
        "<details>",
        "<summary>3 changes since 2.3.0</summary>",
        "",
        "| Tag | Change | Jira | Deployed to | Failed jobs |",
        "|---|---|---|---|---|",
        (
            "|  | [`9ac01f2`](https://g.test/c/9ac01f2aaaa) fix \\| &lt;b&gt;typo&lt;/b&gt; · J. Doe "
            "| [SHOP-9](https://j.test/browse/SHOP-9) |  | main 🔄 [5130](https://g.test/p/5130) |"
        ),
        (
            "| [2.4.0](https://g.test/p/5120) ❌ "
            "| [!311](https://g.test/mr/311) SHOP-140 \\[refund\\] endpoint · @jdoe"
            "<br>[!312](https://g.test/mr/312) Second<br>line "
            "| [SHOP-140](https://j.test/browse/SHOP-140), OPS-1 "
            "| preview "
            "| main ❌ [5118](https://g.test/p/5118): [lint](https://g.test/j/lint) (allowed), "
            "[appsec](https://g.test/j/appsec) → [child](https://g.test/p/9)"
            "<br>tag 2.4.0: [smoke](https://g.test/j/smoke) |"
        ),
        (
            "| [2.3.2](https://g.test/t/2.3.2) ⚠️ no pipeline "
            "| [!305](https://g.test/mr/305) Old change · @asmith |  |  |  |"
        ),
        "",
        "</details>",
    ]


def test_page_without_changes_or_problems_says_so() -> None:
    page: typing.Final = render_markdown(_report(_BILLING))

    assert "All services are up to date." in page.splitlines()
    assert "| Service | prod | Pending | Failed jobs |" not in page
    assert "<summary>1 service up to date</summary>" in page


def test_empty_report_says_nothing_was_collected() -> None:
    assert render_markdown(_report()).splitlines()[-1] == "No services were collected."


def test_services_up_to_date_are_counted_in_plural() -> None:
    other: typing.Final = _BILLING.model_copy(update={"project": "acme/zeta"})

    assert "<summary>2 services up to date</summary>" in render_markdown(_report(_BILLING, other))


def test_service_with_changes_keeps_its_warnings_above_the_table() -> None:
    warned: typing.Final = _API.model_copy(update={"warnings": ["Stopped after 3 commits; older changes are omitted."]})

    lines: typing.Final = render_markdown(_report(warned)).splitlines()

    assert lines.index("⚠️ Stopped after 3 commits; older changes are omitted.") < lines.index("<details>")


def test_link_targets_cannot_break_out_of_markdown() -> None:
    odd: typing.Final = _BILLING.model_copy(
        update={"project": "acme/odd", "project_url": "https://g.test/a b)c", "rows": _API.rows[:1]}
    )

    assert "[acme/odd](https://g.test/a%20b%29c)" in render_markdown(_report(odd))


def test_single_change_and_single_merge_request_are_singular() -> None:
    single: typing.Final = _API.model_copy(update={"rows": _API.rows[2:]})

    page: typing.Final = render_markdown(_report(single))

    assert "<summary>1 change since 2.3.0</summary>" in page
    assert "prod [2.3.0](https://g.test/d1) · preview 2.4.0 · 1 merge request" in page
    assert "| 1 change |" in page
