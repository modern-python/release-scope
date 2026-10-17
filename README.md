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

`release-scope` shows what each of your GitLab services would ship if you released it now. For every service it
lists the merge requests and commits between production and the default branch, the tags you could release, their
pipelines, and the Jira issues they carry. Pick a tag per service, or tick Jira issues and let it pick the tags, then
copy the release post.

It writes a static page with a `report.json`, built to run on a schedule and publish with GitLab Pages.
[Try the demo](https://modern-python.github.io/release-scope/): a made-up shop with four services and six Jira issues.

[![The release-scope page with one Jira issue chosen and the tags it needs picked in two services](https://modern-python.github.io/release-scope/screenshot.png)](https://modern-python.github.io/release-scope/)

## Quickstart

```sh
export RELEASE_SCOPE_GITLAB__ENDPOINT=https://gitlab.example.com
export RELEASE_SCOPE_GITLAB__TOKEN=glpat-...          # read_api scope
export RELEASE_SCOPE_ENVIRONMENTS='["prod", "preview"]'
export RELEASE_SCOPE_PRODUCTION_ENVIRONMENT=prod

uvx release-scope collect --group team/backend --output public --cache cache.json
python3 -m http.server --directory public
```

Then open http://localhost:8000. The page reads `report.json` over HTTP, so a `file://` URL will not work.

- `--group` and `--project` are repeatable and can be mixed. `--include-subgroups` adds the projects of subgroups.
- `--exclude` (`-x`) skips every project whose path matches a glob like `team/*-sandbox`. It is repeatable, and `*`
  also matches `/`. A skipped project is never queried, including when a Jira issue links to it.
- `--cache` saves requests between runs; see [Cache](#cache).

## Publish with GitLab Pages

Run `collect` from a scheduled pipeline in a project of its own, such as `team/release-report`. Pages serves only the
site of the project that runs the job, and that project's members are the ones who can view it. `collect` reads the
services through the API, so they need no change.

```yaml
release-report:
  image: ghcr.io/astral-sh/uv:python3.13-trixie-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  script:
    - uvx --from 'release-scope>=0.9,<0.10' release-scope collect --group team/backend --output public || [ $? -eq 1 ]
  pages: true
```

`|| [ $? -eq 1 ]` keeps the job green when only some services failed, since GitLab deploys Pages only from a
successful job, and the page shows their errors. Any other failure still fails the job and keeps the previous site.
`pages: true` needs GitLab 17.6 and publishes `public` from 17.10. On older versions, name the job `pages` and add
`artifacts: {paths: [public]}`.

Set `RELEASE_SCOPE_GITLAB__ENDPOINT`, a masked `RELEASE_SCOPE_GITLAB__TOKEN`, and the other settings as CI/CD
variables of the project, then add a pipeline schedule.

A Pages site is public to anyone who can reach it, even for a private project, unless an administrator of a
self-managed instance turns on [Pages access control](https://docs.gitlab.com/administration/pages/#access-control).
With it on, set **Settings > General > Visibility > Pages** to *Only project members*.

## Choosing a release

Open a service and press **pick** on the tag to release. It ships every row from that tag down to production. Or
tick Jira issues in the **Issues** list, and the page picks, in every service they touch, the nearest tag that ships
them, and marks other issues those tags ship anyway. The address keeps the picks, so a link shares them.

The **Release** column turns the picks into the Jira task list, the tag pipelines, compare links, and a Markdown
release post to copy. [The page](https://github.com/modern-python/release-scope/blob/main/docs/page.md) describes
every label and rule.

## Jira

Set `RELEASE_SCOPE_JIRA_ENDPOINT` and `RELEASE_SCOPE_JIRA_TOKEN` to add Jira. `collect` then reads the summary and
status of every key the rows mention, and the GitLab merge requests and commits linked to each issue through GitLab's
Jira integration.

`--jira` collects only the services some Jira issues link to, instead of a group or project:

```sh
uvx release-scope collect --jira SHOP-140 --jira SHOP-141 --output public --cache cache.json
```

The report then starts with each service's release tag picked: the nearest tag at or above the issues' latest
change. `--jira` is repeatable and cannot be combined with `--group` or `--project`.
[How collection works](https://github.com/modern-python/release-scope/blob/main/docs/how-it-works.md) has the details.

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

## Failures and exit codes

One service failing does not stop the run. A service GitLab denies access to fails alone, and its error names the
project settings and member page to check. A project with CI/CD or Environments disabled gets a warning and no rows,
without being queried.

| Exit code | When |
|---|---|
| `0` | Everything was collected |
| `1` | Some services failed, the Jira search failed, or Jira has no issue passed to `--jira`. The report is still written and names each error |
| `2` | A setting or option is invalid, or the GitLab token is missing |
| `3` | GitLab rejected the token, or denied access to a group or project passed on the command line |
| `4` | GitLab failed to return a group or project passed on the command line |

## Cache

`--cache` names a JSON file that is read if present and rewritten atomically after the run. It holds only facts that do not
change once settled: which merge requests a commit belongs to, merged merge requests, and the failed jobs of finished
pipelines. A retried job changes its pipeline's `updated_at`, which invalidates the entry. Entries a run did not use
are dropped for the projects it collected, so one file serves both group and `--jira` runs. A missing, corrupt, or
older cache is ignored with a warning. The cache never changes the report.

## Agent skill

[`skills/release-scope`](https://github.com/modern-python/release-scope/tree/main/skills/release-scope) is an agent
skill that runs `release-scope` and answers release questions from the report. Ask your coding agent what in the
current repository has not reached production, what a group will ship with the next tag, or whether a Jira issue is
released and which services it touches. For the current repository it takes `--project` from the git remote,
and it keeps the report and cache outside the repository. Install it with [skills](https://github.com/vercel-labs/skills):

```sh
npx skills add modern-python/release-scope
```

The agent reads the same environment variables as the CLI, so set them first. The skill runs
`release-scope>=0.9,<0.10`, the range whose flags and report schema it describes.

## More

- [How collection works](https://github.com/modern-python/release-scope/blob/main/docs/how-it-works.md): the range,
  rows, Jira links, and `--jira` release states.
- [The page](https://github.com/modern-python/release-scope/blob/main/docs/page.md): every part of the page and what
  its labels mean.
- [Report](https://github.com/modern-python/release-scope/blob/main/docs/report.md): the `report.json` fields, for
  scripts and agents.

## Links

- [PyPI](https://pypi.org/project/release-scope)
- [License](https://github.com/modern-python/release-scope/blob/main/LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python); see the org profile for the categorized index.
