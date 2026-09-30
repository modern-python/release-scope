import datetime
import typing

from release_scope._render import render_markdown
from release_scope._report import (
    CommitRef,
    EnvironmentState,
    FailedJob,
    JiraIssue,
    JiraKeyRef,
    JiraState,
    LinkedChange,
    MergeRequestRef,
    PipelineState,
    Release,
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


def _environment(name: str, ref: str, url: str | None = None, *, tag: bool = False) -> EnvironmentState:
    return EnvironmentState(
        name=name, ref=ref, sha=f"sha-{ref}", deployed_at="2026-09-20T00:00:00Z", deployment_url=url, tag=tag
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


def _report(*services: Service, jira: JiraState | None = None) -> Report:
    return Report(collected_at=_COLLECTED_AT, production_environment="prod", services=list(services), jira=jira)


def _issue(key: str, summary: str, status: str, category: str | None, *links: LinkedChange) -> JiraIssue:
    return JiraIssue(
        key=key, summary=summary, status=status, status_category=category, issue_type="Task", links=list(links)
    )


def _linked(project: str, iid: int) -> LinkedChange:
    return LinkedChange(
        kind="merge_request",
        project=project,
        project_url=f"https://g.test/{project}",
        url=f"https://g.test/{project}/-/merge_requests/{iid}",
        iid=iid,
    )


_JIRA: typing.Final = JiraState(
    issues={
        "SHOP-140": _issue(
            "SHOP-140",
            "Refund | endpoint",
            "In Progress",
            "indeterminate",
            _linked("acme/web", 7),
            _linked("acme/api", 311),
            _linked("acme/web", 8),
            LinkedChange(
                kind="commit",
                project="acme/worker",
                project_url="https://g.test/acme/worker",
                url="https://g.test/acme/worker/-/commit/abc",
                sha="abc",
            ),
        ),
        "SHOP-9": _issue("SHOP-9", "Typo", "Done", "done"),
    },
    missing=["OPS-1"],
)


_API: typing.Final = Service(
    project="acme/api",
    project_url="https://g.test/acme/api",
    default_branch="main",
    environments=[_environment("prod", "2.3.0", "https://g.test/d1", tag=True), _environment("preview", "2.4.0")],
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
    page: typing.Final = render_markdown(_report(_API, _BILLING, _BROKEN, _UTILS, jira=_JIRA))

    assert page.splitlines() == [
        "# Release scope",
        "",
        "Collected 2026-09-29 10:15 UTC. Changes run from the commit on `prod` to the head of the default branch.",
        "",
        "Legend: ✅ success · ❌ failed · 🔄 running · ⏭ canceled or skipped · ⚠️ warning or allowed failure",
        "",
        "| Service | prod | preview | Pending | Compare | Jira | Failed jobs |",
        "|---|---|---|---|---|---|---|",
        "| [acme/broken](https://g.test/acme/broken) | — | — | ❌ failed to collect |  |  |  |",
        "| [acme/utils](https://g.test/acme/utils) | — | — | ⚠️ see below |  |  |  |",
        (
            "| [acme/api](https://g.test/acme/api) | [2.3.0](https://g.test/d1) | 2.4.0 "
            "| 3 changes · untagged head | [2.3.0...2.4.0](https://g.test/acme/api/-/compare/2.3.0...2.4.0) "
            "| 1 not done | ❌ 2 · ⚠️ 1 allowed |"
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
        "| Tag | Change | Jira | Related services | Deployed to | Failed jobs |",
        "|---|---|---|---|---|---|",
        (
            "|  | [`9ac01f2`](https://g.test/c/9ac01f2aaaa) fix \\| &lt;b&gt;typo&lt;/b&gt; · J. Doe "
            "| [SHOP-9](https://j.test/browse/SHOP-9) Typo · Done |  |  | main 🔄 [5130](https://g.test/p/5130) |"
        ),
        (
            "| [2.4.0](https://g.test/p/5120) ❌ "
            "| [!311](https://g.test/mr/311) SHOP-140 \\[refund\\] endpoint · @jdoe"
            "<br>[!312](https://g.test/mr/312) Second<br>line "
            "| [SHOP-140](https://j.test/browse/SHOP-140) Refund \\| endpoint · In Progress<br>OPS-1 "
            "| [acme/web](https://g.test/acme/web), [acme/worker](https://g.test/acme/worker) "
            "| preview "
            "| main ❌ [5118](https://g.test/p/5118): [lint](https://g.test/j/lint) (allowed), "
            "[appsec](https://g.test/j/appsec) → [child](https://g.test/p/9)"
            "<br>tag 2.4.0: [smoke](https://g.test/j/smoke) |"
        ),
        (
            "| [2.3.2](https://g.test/t/2.3.2) ⚠️ no pipeline "
            "| [!305](https://g.test/mr/305) Old change · @asmith |  |  |  |  |"
        ),
        "",
        "</details>",
    ]


def test_page_without_changes_or_problems_says_so() -> None:
    page: typing.Final = render_markdown(_report(_BILLING))

    assert "All services are up to date." in page.splitlines()
    assert "| Service | prod | Pending | Compare | Failed jobs |" not in page
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


def test_summary_counts_allowed_failures_apart_from_blocking_ones() -> None:
    allowed_only: typing.Final = _API.model_copy(
        update={
            "rows": [
                _API.rows[0].model_copy(
                    update={"main_pipeline": _pipeline(5130, "success", _job("lint", allow_failure=True))}
                )
            ]
        }
    )

    assert "| 1 change · untagged head |  | ⚠️ 1 allowed |" in render_markdown(_report(allowed_only))


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


def test_service_with_rows_but_no_production_environment_still_renders() -> None:
    orphan: typing.Final = _API.model_copy(update={"environments": [_environment("preview", "2.4.0")]})

    page: typing.Final = render_markdown(_report(orphan))

    assert "<summary>3 changes</summary>" in page
    assert "preview 2.4.0 · 3 merge requests, 1 direct commit" in page
    assert "| 3 changes · untagged head |  | ❌ 2 · ⚠️ 1 allowed |" in page


def test_compare_starts_from_the_production_commit_when_it_was_not_deployed_from_a_tag() -> None:
    production: typing.Final = EnvironmentState(
        name="prod", ref="main", sha="0a1b2c3d4e5f", deployed_at="2026-09-20T00:00:00Z", deployment_url=None
    )
    from_branch: typing.Final = _API.model_copy(update={"environments": [production]})

    assert "| [`0a1b2c3d`...2.4.0](https://g.test/acme/api/-/compare/0a1b2c3d4e5f...2.4.0) |" in render_markdown(
        _report(from_branch)
    )


def test_compare_quotes_the_tag_but_keeps_its_slashes() -> None:
    odd_tag: typing.Final = TagRef(name="release/2.4#1", url="https://g.test/t/x", pipeline=None)
    tagged: typing.Final = _API.model_copy(
        update={"rows": [_API.rows[0].model_copy(update={"tags": [odd_tag]}), *_API.rows[1:]]}
    )

    assert "| [2.3.0...release/2.4#1](https://g.test/acme/api/-/compare/2.3.0...release/2.4%231) |" in render_markdown(
        _report(tagged)
    )


def test_pipe_in_a_link_target_does_not_split_the_cell() -> None:
    piped: typing.Final = _BILLING.model_copy(
        update={"project": "acme/piped", "project_url": "https://g.test/a|b", "rows": _API.rows[:1]}
    )

    assert "[acme/piped](https://g.test/a%7Cb)" in render_markdown(_report(piped))


def test_section_lists_production_first() -> None:
    reordered: typing.Final = _API.model_copy(update={"environments": list(reversed(_API.environments))})

    assert "prod [2.3.0](https://g.test/d1) · preview 2.4.0 · " in render_markdown(_report(reordered))


def test_page_without_jira_lists_bare_keys_and_no_jira_column() -> None:
    page: typing.Final = render_markdown(_report(_API))

    assert "| Service | prod | preview | Pending | Compare | Failed jobs |" in page
    assert "| Tag | Change | Jira | Deployed to | Failed jobs |" in page
    assert "| [SHOP-140](https://j.test/browse/SHOP-140)<br>OPS-1 |" in page


def test_jira_failure_is_shown_under_the_legend() -> None:
    lines: typing.Final = render_markdown(
        _report(_API, jira=JiraState(error="Jira rejected the token (401).")),
    ).splitlines()

    assert lines[4].startswith("Legend:")
    assert lines[6] == "❌ Jira rejected the token (401)."


def _scoped(*services: Service) -> Report:
    jira: typing.Final = JiraState(
        issues={
            "SHOP-140": _JIRA.issues["SHOP-140"].model_copy(update={"url": "https://j.test/browse/SHOP-140"}),
            "SHOP-9": _JIRA.issues["SHOP-9"],
        },
        missing=["SHOP-404"],
    )
    return _report(*services, jira=jira).model_copy(update={"jira_scope": ["SHOP-140", "SHOP-404"]})


_TAG: typing.Final = TagRef(name="2.4.0", url="https://g.test/t/2.4.0", pipeline=_pipeline(5120, "success"))
_SCOPED_API: typing.Final = _API.model_copy(
    update={
        "rows": [_API.rows[1].model_copy(update={"linked": True}), _API.rows[2]],
        "release": Release(state="pending", tag=_TAG),
    }
)


def test_scoped_page_names_the_issues_and_the_release_tag() -> None:
    lines: typing.Final = render_markdown(_scoped(_SCOPED_API)).splitlines()

    assert lines[0] == "# Release scope: SHOP-140, SHOP-404"
    assert lines[2].endswith("Changes run from the commit on `prod` to the latest change linked to the issues.")
    assert lines[4:6] == [
        "- [SHOP-140](https://j.test/browse/SHOP-140) Refund \\| endpoint · In Progress",
        "- SHOP-404 · not found in Jira",
    ]
    assert lines[7].endswith(" · 🎯 linked to the issues")
    assert (
        "| 2 changes · release [2.4.0](https://g.test/p/5120) ✅ "
        "| [2.3.0...2.4.0](https://g.test/acme/api/-/compare/2.3.0...2.4.0) | 1 not done | ❌ 2 · ⚠️ 1 allowed |"
    ) in lines[11]
    assert any(line.startswith("| [2.4.0](https://g.test/p/5120) ❌ | 🎯 [!311]") for line in lines)


def test_scoped_service_without_a_tag_needs_one() -> None:
    untagged: typing.Final = _SCOPED_API.model_copy(update={"release": Release(state="pending")})

    assert "| 2 changes · needs a new tag |  |" in render_markdown(_scoped(untagged))


def test_scoped_compare_goes_to_the_release_tag() -> None:
    later: typing.Final = _SCOPED_API.model_copy(
        update={"release": Release(state="pending", tag=_TAG.model_copy(update={"name": "2.4.1"}))}
    )

    assert "(https://g.test/acme/api/-/compare/2.3.0...2.4.1) |" in render_markdown(_scoped(later))


def test_scoped_service_with_unmerged_work_asks_for_attention() -> None:
    waiting: typing.Final = _BILLING.model_copy(
        update={
            "release": Release(
                state="not_merged",
                pending_merge_requests=[
                    MergeRequestRef(iid=7, title="WIP", url="https://g.test/mr/7", author="jdoe", merged_at=None)
                ],
            )
        }
    )
    lost: typing.Final = _BILLING.model_copy(update={"project": "acme/lost", "release": Release(state="not_found")})

    page: typing.Final = render_markdown(_scoped(waiting, lost))

    assert (
        "| [acme/billing](https://g.test/acme/billing) | [1.8.1](https://g.test/d2) | ⏳ not merged |  |  |  |" in page
    )
    assert (
        "| [acme/lost](https://g.test/acme/billing) | [1.8.1](https://g.test/d2) | ⚠️ linked change not found |  |  |  |"
        in page
    )
    assert "⏳ Not merged: [!7](https://g.test/mr/7) WIP · @jdoe" in page.splitlines()


def test_scoped_service_already_in_production_is_up_to_date() -> None:
    shipped: typing.Final = _BILLING.model_copy(update={"release": Release(state="in_production")})

    assert "<summary>1 service up to date</summary>" in render_markdown(_scoped(shipped))
