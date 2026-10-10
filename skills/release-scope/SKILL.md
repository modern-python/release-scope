---
name: release-scope
description: >
  Run the release-scope CLI through uvx to find what sits between production and the default branch of GitLab
  services: pending merge requests and commits, tags, environments, failed jobs, and Jira issues with their status.
  Use when the user asks what is not in production yet, what will ship with the next release or tag, whether a Jira
  issue is released or which services it touches, or which Jira issues a set of tags would release, for the current
  repository, a GitLab group, or a list of projects, even if they do not name release-scope.
---

# release-scope

`release-scope` is a CLI on PyPI. `collect` only reads GitLab and Jira, so it needs no approval to run. Always run it
through uvx with this version range; it matches the flags and report schema described here:

```bash
uvx --from 'release-scope>=0.6,<0.7' release-scope --help
```

## Check the settings

Every setting is an environment variable. List which ones are set without printing their values:

```bash
env | cut -d= -f1 | grep -E '^(RELEASE_SCOPE_|GITLAB_TOKEN$|JIRA_TOKEN$)' | sort
```

| Variable | Needed for |
|---|---|
| `RELEASE_SCOPE_GITLAB__ENDPOINT` | Any run; defaults to `https://gitlab.com` |
| `RELEASE_SCOPE_GITLAB__TOKEN` or `GITLAB_TOKEN` | Any run; `read_api` scope |
| `RELEASE_SCOPE_ENVIRONMENTS` | Environments to show, a JSON list such as `'["prod", "preview"]'` |
| `RELEASE_SCOPE_PRODUCTION_ENVIRONMENT` | The environment whose deployment starts the range; defaults to `production` |
| `RELEASE_SCOPE_JIRA_ENDPOINT` and `RELEASE_SCOPE_JIRA_TOKEN` (or `JIRA_TOKEN`) | Jira summaries and statuses; required for `--jira` |

If a required variable is missing, tell the user which one and stop; do not guess a value or ask them to paste a
token into the chat. Never echo a token.

## Choose the scope

- The current repository: pass its GitLab path as `--project`. Take it from `git remote get-url origin`, drop the
  host and the trailing `.git`: `git@gitlab.example.com:team/backend/shop.git` and
  `https://gitlab.example.com/team/backend/shop.git` both give `team/backend/shop`. If the remote host is not the
  host of `RELEASE_SCOPE_GITLAB__ENDPOINT`, say so and ask for the project path.
- Groups or projects the user names: `--group` and `--project`, both repeatable and combinable.
  `--include-subgroups` also collects subgroups of each group.
- Jira issue keys: `--jira KEY`, repeatable. It collects only the projects the issues link to, from production up to
  the latest linked change. It cannot be combined with `--group` or `--project`.

## Collect

Keep the files outside the repository so they never land in its git tree. `--output` is a directory; `collect`
writes `report.json` there, next to a static page for GitLab Pages that you do not need. One cache file serves every
run and only saves requests:

```bash
out="${XDG_CACHE_HOME:-$HOME/.cache}/release-scope"
mkdir -p "$out"
uvx --from 'release-scope>=0.6,<0.7' release-scope collect --project team/backend/shop \
  --output "$out/site" --cache "$out/cache.json"
```

Exit codes of `collect`:

- `0`: every service collected.
- `1`: the report is written, but some service failed or a Jira request failed or a `--jira` key does not exist.
  The messages are on stderr and in the report; summarize the rest and name what failed.
- `2`: a configuration or usage error, such as a missing token or bad flags.
- `3`: GitLab rejected the token.
- `4`: a GitLab request for a group or project passed on the command line failed, for example one the token cannot see.

For `2` to `4` nothing was written; show the message and stop.

## Summarize the report

Read `$out/site/report.json` and answer the user's question from it, briefly.

- `services[]`: `project`, `environments` (what each environment runs), `rows` (newest first, from the default
  branch head down to production), `warnings`, `error`. Warnings and errors are messages: read their `text`;
  `code` and `params` carry the same facts in structured form.
- A row is one merged merge request or a direct commit: `merge_requests`, `commits`, `tags` pointing into it,
  `environments` already running it, `jira_keys`, and `main_pipeline` with `failed_jobs`. Tag pipelines carry their
  own `failed_jobs`.
- A service with no rows is up to date with production.
- A service never deployed to production has a `no_production` warning; its rows run down to the first commit of the
  default branch and its `compare_url` lists the tag's commits.
- `truncated: true`: the walk stopped at `RELEASE_SCOPE_MAX_COMMITS`, so the oldest candidates miss rows and keys.
- `candidates` (newest first): the tags a release could ship, each with `tag` and its `pipeline`, `rows` (how many
  rows run from that tag down to production), `jira_keys` (the in-scope keys of those rows, without duplicates), and
  `compare_url`.
  To answer which issues a set of tags releases, merge the `jira_keys` of the picked candidates.
- `jira.issues` by key: `summary`, `status`, `status_category` (anything but `done` is not done), `links` to GitLab
  merge requests and commits. `jira.missing` lists keys Jira did not return; `jira.error` a failed request, as a message. `jira` is
  `null` without a Jira token.
- In a `--jira` report, `jira_scope` lists the issues, rows with `linked: true` are the ones the issues point to,
  rows with `in_scope: false` sit above the latest linked change and do not ship with the issues, and each service
  has a `release`:
  - `pending` with `tag`: that tag ships the issue; without `tag`, a new tag is needed.
  - `in_production`: every linked merge request is already deployed.
  - `not_merged`: only open merge requests link to it.
  - `not_found`: the linked change is not on the default branch within the range.
  - `pending_merge_requests`: open or merged-elsewhere merge requests, listed in every state.

Lead with what needs attention: failed services, failed jobs without `allow_failure`, Jira issues that are not done,
and releases that need a new tag or are not merged. Deployment data comes from GitLab environments; it shows what was
deployed, not proof of what serves traffic.
