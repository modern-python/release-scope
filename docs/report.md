# Report

`collect` writes `report.json` next to the page. It is versioned by `schema_version`, and the models live in
[`release_scope/_report.py`](../release_scope/_report.py). [How collection works](how-it-works.md) explains where
the values come from.

## Top level

- `services`: one entry per collected service.
- `jira`: `null` without a Jira token. Otherwise it holds `issues` by key (summary, status, status category, issue
  type, and linked GitLab changes with their `state` and `target_branch`), the `missing` keys Jira did not return,
  and an `error` if a Jira request failed.
- `jira_scope`: the keys passed to `--jira`, empty for a group or project run.

Warnings and errors, on services and in `jira`, are messages: a `code`, its `params`, and the English `text`.

## Services

Besides its rows, a service lists its `candidates`: the tags a release could ship, newest first. Each has its
pipeline, the number of rows it ships, the in-scope Jira keys of those rows, and a compare link from production. A
service with no production deployment gets the tag's commit history instead of a compare link.

When rows sit above the newest tag, `untagged` counts them and gives the head commit, the next tag (or `null`), and
`create_url`: GitLab's new-tag form filled in with both.

A `--jira` run adds `release`, the state described under [Scoping by issues](how-it-works.md#scoping-by-issues).

## Rows

One row, trimmed:

```json
{
  "kind": "merge_request",
  "tags": [{"name": "1.2.0", "url": "...", "pipeline": {"id": 201, "status": "success", "failed_jobs": []}}],
  "merge_requests": [{"iid": 12, "title": "SHOP-12 new endpoint", "url": "..."}],
  "commits": [{"sha": "c3...", "title": "Merge branch 'feature/SHOP-12'"}],
  "jira_keys": [{"key": "SHOP-12", "url": "https://jira.example.com/browse/SHOP-12", "via": ["named", "linked"]}],
  "environments": ["preview"],
  "first_deployed_at": {"preview": "2026-09-22T00:00:00Z"},
  "main_pipeline": {"id": 103, "status": "failed", "failed_jobs": [{"kind": "job", "name": "lint", "allow_failure": false}]}
}
```

A Jira key's `via` says why the row carries it: `named` when the merge request or commit text names it, `linked`
when the issue's GitLab links point into the row, or both. A candidate's keys merge `via` across the rows it ships.
