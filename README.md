<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"  srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/release-scope/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/release-scope/lockup-light.svg">
    <img alt="release-scope" src="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/release-scope/lockup.png" width="420">
  </picture>
</p>

[![PyPI version](https://img.shields.io/pypi/v/release-scope.svg)](https://pypi.org/project/release-scope/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/release-scope.svg)](https://pypi.org/project/release-scope/)
[![Downloads](https://static.pepy.tech/badge/release-scope/month)](https://pepy.tech/projects/release-scope)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/release-scope/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/release-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/release-scope/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/release-scope.svg)](https://github.com/modern-python/release-scope/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/release-scope)](https://github.com/modern-python/release-scope/stargazers)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

`release-scope` collects what sits between production and the default branch across GitLab services: tags, MRs,
Jira issues, failed jobs.

For every service it reads the latest successful production deployment, walks the default branch down to that
commit, or down to its first commit when the service was never deployed to production, and writes a static site with
one JSON report: a row per merge request or direct commit, newest first, with the tags that point into it, the
environments running it, the Jira keys its MR mentions, and the failed jobs of its main-branch and tag pipelines. With a Jira token, it also reads the summary and status of every key in one batched search,
and the GitLab merge requests and commits linked to each issue. GitLab's Jira integration adds those links to the
issue's Web links whenever a commit or MR mentions it; a link counts only if it starts with
`RELEASE_SCOPE_GITLAB__ENDPOINT`. The projects they point to are the issue's related services.

## Quickstart

```sh
export RELEASE_SCOPE_GITLAB__ENDPOINT=https://gitlab.example.com
export RELEASE_SCOPE_GITLAB__TOKEN=glpat-...          # read_api scope
export RELEASE_SCOPE_ENVIRONMENTS='["prod", "preview"]'
export RELEASE_SCOPE_PRODUCTION_ENVIRONMENT=prod

uvx release-scope collect --group team/backend --output public --cache cache.json
```

`--output` is a directory: `collect` writes `report.json` there, next to the page that shows it (see Site).
`--group` and `--project` are repeatable and can be mixed. `--exclude` (`-x`) skips every project whose path
matches a glob like `team/*-sandbox`. It is repeatable, `*` also matches `/`, and a skipped project is left out of
the report without being queried. The command exits `1` when any service failed to collect; the report is still written and names the error on that service. A service GitLab denies access to fails
alone, and its error lists the project settings and member page to check. A project with CI/CD or Environments
disabled is reported with a warning and no rows, without querying it. Only a rejected token, or a group or project
passed on the command line that the token cannot see, stops the run. A failed Jira search is recorded in the report
and also exits `1`; the GitLab part is still written.

## Jira issues

`--jira` scopes the report to Jira issues instead of groups or projects, and needs the Jira settings:

```sh
uvx release-scope collect --jira SHOP-140 --jira SHOP-141 --output public --cache cache.json
```

It reads the issues and their GitLab links, then collects every project they link to. In each project the rows from
the production baseline up to the latest linked change are in scope: they show everything that ships with the issues.
Rows above that change are kept with `in_scope: false`, so their tags can still be picked, but their Jira keys are
neither looked up nor counted as tasks of a release. The service
records the release state: `pending` with the nearest tag at or above that change (or none, when a new tag is
needed), `in_production` when every linked merge request is already deployed, `not_merged` when only open merge
requests link to it, or `not_found`. Open merge requests and merges into other branches are listed either way.
`--exclude` drops linked projects the same way.
`--jira` is repeatable and cannot be combined with `--group` or `--project`; an issue Jira does not return exits `1`.

## Configuration

Every setting is an environment variable; nothing about a GitLab or Jira instance is built in.

| Variable | Default | Meaning |
|---|---|---|
| `RELEASE_SCOPE_GITLAB__ENDPOINT` | `https://gitlab.com` | GitLab base URL |
| `RELEASE_SCOPE_GITLAB__TOKEN` or `GITLAB_TOKEN` | required | Token with `read_api` |
| `RELEASE_SCOPE_ENVIRONMENTS` | `["production"]` | Environments shown per service, as a JSON list |
| `RELEASE_SCOPE_PRODUCTION_ENVIRONMENT` | `production` | Environment whose deployed commit starts the range |
| `RELEASE_SCOPE_JIRA_ENDPOINT` | unset | When set, Jira keys link to `<endpoint>/browse/<KEY>` |
| `RELEASE_SCOPE_JIRA_TOKEN` or `JIRA_TOKEN` | unset | Jira Server/Data Center personal access token; when set, issues are fetched |
| `RELEASE_SCOPE_JIRA_PROJECT_KEYS` | `[]` | Keep only keys of these Jira projects; empty keeps all |
| `RELEASE_SCOPE_MAX_COMMITS` | `1000` | Stop walking a service's range after this many commits |
| `RELEASE_SCOPE_REQUEST_TIMEOUT` | `10` | Per-request timeout in seconds |

## Report

The report is versioned by `schema_version`; the models live in
[`release_scope/_report.py`](https://github.com/modern-python/release-scope/blob/main/release_scope/_report.py).
Top-level `jira` is `null` without a Jira token; otherwise it holds `issues` by key (summary, status, status category,
issue type, linked GitLab changes), the `missing` keys Jira did not return, and an `error` if a Jira request failed.
Warnings and errors, on services and in `jira`, are messages: a `code`, its `params`, and the English `text`.
Each service lists its `candidates`: the tags a release could ship, newest first, each with its pipeline, the number of
rows it ships, the in-scope Jira keys of those rows, and the compare link from production, or the tag's commit history
when the service has no production deployment. When rows sit above the newest tag, `untagged` counts them and gives
the head commit, the next tag (the highest `X.Y.Z` tag with its minor version bumped, or `null` when no tag has that
form), and `create_url`, GitLab's new-tag form filled in with both. One row, trimmed:

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

## Site

Besides `report.json`, `collect` writes `index.html` and its script into the output directory. They come from the
installed package and change only with it, so the page always matches the report schema. The page loads
`report.json` from next to itself; it needs a web server, not a `file://` URL.

Switches at the top pick the language, English or Russian, and the theme: as in the system, light, or dark. The page
starts in the browser's language and remembers both choices in the browser. The copied lists and release post follow
the language, and so do warnings and errors from `collect`; texts from GitLab and Jira, such as titles, statuses and
Jira's own error details, stay as written.

**Services** lists every service with a production deployment or with rows, and every service that failed to collect,
as one line: what production runs, the picked tag, how many merge requests or commits and Jira tasks it ships, failed jobs
with the ones allowed to fail counted apart, a mark when the range was cut at `RELEASE_SCOPE_MAX_COMMITS`, and how
many rows have no tag yet.
Opening a line shows the service's environments, warnings, a link to create the next tag on the head when rows have no
tag yet, merge requests that are not merged yet, and its rows with
tags and their pipelines, merge requests or commits, Jira keys with their status, environments, and failed jobs; rows
out of scope are dimmed. Links, including the GitLab settings pages that warnings and errors point to, open in a new
tab. Each tag has a **pick** button: picking it highlights the rows it ships and closes the line again. A `--jira`
report starts with each service's release tag picked. Services with neither a production deployment nor rows are left
out of the page.

The address keeps the picks after `#`, as `team/api=2.4.0&team/web=5.12.0`, so sharing or reloading the page keeps
them. An address with picks replaces the release tags of a `--jira` report; picks that are not in the report, such as
a tag that a later run no longer lists, are skipped with a warning. Clearing every pick empties the address, so a
reload starts from the release tags again.

**Release** at the bottom turns the picked tags into three lists and a release post, each with a copy button and a
text box to copy from by hand, since browsers allow the copy button only over HTTPS:

- **Jira tasks**: the keys of every in-scope row from each picked tag down to production, without duplicates, with
  summary and a status badge: grey to do, blue in progress, green done. Copy them one per line or as a JQL
  `key in (...)` clause, each in its own box.
- **Tag pipelines**: the pipeline of each picked tag, as a Markdown list.
- **Compare**: a GitLab compare link per service from production to the picked tag, as a Markdown list. A service
  never deployed to production gets the commit history of the tag instead.
- **Release post**: one Markdown text with a line per picked tag, holding its compare link and pipeline, followed by
  the Jira tasks with their summaries.

## GitLab Pages

A scheduled pipeline publishes the site with [GitLab Pages](https://docs.gitlab.com/user/project/pages/). Keep it in
a project of its own, such as `team/release-report`: Pages serves only the site of the project that runs the job,
and its members are who can view it. `collect` reads the services through the API, so they need no change.

```yaml
release-report:
  image: ghcr.io/astral-sh/uv:python3.13-trixie-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  script:
    - uvx --from 'release-scope>=0.7,<0.8' release-scope collect --group team/backend --output public || [ $? -eq 1 ]
  pages: true
```

`|| [ $? -eq 1 ]` keeps the job green when only some services failed: the page shows their errors, and GitLab deploys
Pages only from a successful job. A configuration error, a rejected token, or an unreachable group still fails the
job and keeps the previous site. `pages: true` needs GitLab 17.6 and publishes `public` as the job artifact from 17.10;
on older versions name the job `pages` and add `artifacts: {paths: [public]}`.

Set `RELEASE_SCOPE_GITLAB__ENDPOINT` and a masked `RELEASE_SCOPE_GITLAB__TOKEN` as CI/CD variables of the project,
along with the other settings, then add a pipeline schedule. Without [Pages access
control](https://docs.gitlab.com/administration/pages/#access-control), which an administrator of a self-managed
instance turns on, a Pages site is public to anyone who can reach it, even for a private project. With it, set
**Settings > General > Visibility > Pages** to *Only project members*.

## Cache

`--cache` names a JSON file that is read if present and rewritten atomically after the run. It holds only facts
that do not change once settled: which merge requests a commit belongs to, a merged merge request, and the failed
jobs of a finished pipeline keyed by its `updated_at`, so a retried job invalidates the entry. Within each project
the run collected, entries it did not use are dropped; other projects keep theirs, so one cache file serves both
group and `--jira` runs. A missing, corrupt, or older-schema cache is ignored with a warning; the cache only saves
requests and never changes the report.

## Agent skill

[`skills/release-scope`](https://github.com/modern-python/release-scope/tree/main/skills/release-scope) is an agent
skill that runs `release-scope` through `uvx` and answers release questions from the report. Ask your coding agent
what in the current repository has not reached production, what a group will ship with the next tag, or whether a
Jira issue is released and which services it touches. For the current repository the skill takes `--project` from
the git remote. It keeps the report and cache outside the repository.

Install it with [skills](https://github.com/vercel-labs/skills):

```sh
npx skills add modern-python/release-scope
```

The agent reads the same environment variables as the CLI, so set them first as described under Configuration.
The skill runs `release-scope>=0.7,<0.8`, the range whose flags and report schema it describes.
