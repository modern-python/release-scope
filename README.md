[![PyPI version](https://img.shields.io/pypi/v/release-scope.svg)](https://pypi.org/project/release-scope/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/release-scope.svg)](https://pypi.org/project/release-scope/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/release-scope/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/release-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/release-scope/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/release-scope.svg)](https://github.com/modern-python/release-scope/blob/main/LICENSE)

`release-scope` collects what sits between production and the default branch across GitLab services: tags, MRs,
Jira keys, failed jobs.

For every service it reads the latest successful production deployment, walks the default branch down to that
commit, and writes one JSON report: a row per merge request or direct commit, newest first, with the tags that
point into it, the environments running it, the Jira keys its MR mentions, and the failed jobs of its main-branch
and tag pipelines.

## Quickstart

```sh
export RELEASE_SCOPE_GITLAB__ENDPOINT=https://gitlab.example.com
export RELEASE_SCOPE_GITLAB__TOKEN=glpat-...          # read_api scope
export RELEASE_SCOPE_ENVIRONMENTS='["prod", "preview"]'
export RELEASE_SCOPE_PRODUCTION_ENVIRONMENT=prod

uvx release-scope collect --group team/backend --output report.json --cache cache.json
```

`--group` and `--project` are repeatable and can be mixed. The command exits `1` when any service failed to
collect; the report is still written and names the error on that service. A service GitLab denies access to fails
alone, and its error lists the project settings and member page to check. A project with CI/CD or Environments
disabled is reported with a warning and no rows, without querying it. Only a rejected token, or a group or project
passed on the command line that the token cannot see, stops the run.

## Configuration

Every setting is an environment variable; nothing about a GitLab or Jira instance is built in.

| Variable | Default | Meaning |
|---|---|---|
| `RELEASE_SCOPE_GITLAB__ENDPOINT` | `https://gitlab.com` | GitLab base URL |
| `RELEASE_SCOPE_GITLAB__TOKEN` or `GITLAB_TOKEN` | required | Token with `read_api` |
| `RELEASE_SCOPE_ENVIRONMENTS` | `["production"]` | Environments shown per service, as a JSON list |
| `RELEASE_SCOPE_PRODUCTION_ENVIRONMENT` | `production` | Environment whose deployed commit starts the range |
| `RELEASE_SCOPE_JIRA_ENDPOINT` | unset | When set, Jira keys link to `<endpoint>/browse/<KEY>` |
| `RELEASE_SCOPE_JIRA_PROJECT_KEYS` | `[]` | Keep only keys of these Jira projects; empty keeps all |
| `RELEASE_SCOPE_MAX_COMMITS` | `1000` | Stop walking a service's range after this many commits |
| `RELEASE_SCOPE_REQUEST_TIMEOUT` | `10` | Per-request timeout in seconds |

## Report

The report is versioned by `schema_version`; the models live in
[`release_scope/_report.py`](https://github.com/modern-python/release-scope/blob/main/release_scope/_report.py).
One row, trimmed:

```json
{
  "kind": "merge_request",
  "tags": [{"name": "1.2.0", "url": "...", "pipeline": {"id": 201, "status": "success", "failed_jobs": []}}],
  "merge_requests": [{"iid": 12, "title": "SHOP-12 new endpoint", "url": "..."}],
  "commits": [{"sha": "c3...", "title": "Merge branch 'feature/SHOP-12'"}],
  "jira_keys": [{"key": "SHOP-12", "url": "https://jira.example.com/browse/SHOP-12"}],
  "environments": ["preview"],
  "main_pipeline": {"id": 103, "status": "failed", "failed_jobs": [{"kind": "job", "name": "lint", "allow_failure": false}]}
}
```

## Page

`render` turns a report into a Markdown page for a GitLab wiki, without calling GitLab:

```sh
uvx release-scope collect --group team/backend --output report.json --cache cache.json; \
  uvx release-scope render report.json --output report.md
```

The page opens with a table of the services that have pending changes or problems, with the ref each environment runs;
services already up to date collapse into one expandable table. Each service with changes then has a collapsible table
of its rows: the tag linked to its pipeline, the merge requests or direct commit, Jira keys, where the change is
deployed, and the failed jobs of its main-branch and tag pipelines.

Chain the two commands with `;`, not `&&`: `collect` exits `1` when a service failed, which is exactly when the page
should show it. Alert on the exit code of `collect`, not on whether to render. `render` fails only when it cannot
read the report or write the page.

## Cache

`--cache` names a JSON file that is read if present and rewritten atomically after the run. It holds only facts
that do not change once settled: which merge requests a commit belongs to, and the failed jobs of a finished
pipeline keyed by its `updated_at`, so a retried job invalidates the entry. Entries the run did not use are
dropped. A missing, corrupt, or older-schema cache is ignored with a warning; the cache only saves requests and
never changes the report.
