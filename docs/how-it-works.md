# How collection works

## The range

For every service, `collect` reads the latest successful deployment to the production environment and walks the
default branch down to that commit. A service never deployed to production is walked down to its first commit. The
walk stops after `RELEASE_SCOPE_MAX_COMMITS` commits, and the report marks a range cut that way.

## Rows

The range becomes one row per merge request or direct commit, newest first. A row has:

- the tags that point into it;
- the environments running it;
- the Jira keys its merge request mentions in the title, source branch, or description, or that its commit message
  mentions;
- the failed jobs of its main-branch pipeline and of its tag pipelines;
- its first deployment to each environment other than production: when the first deploy job that shipped this row,
  or a newer one, finished.

## Jira issues

With a Jira token, `collect` reads the summary and status of every key in one batched search, and the GitLab merge
requests and commits linked to each issue. GitLab's Jira integration adds those links to the issue's Web links
whenever a commit or merge request mentions it. A link counts only if it starts with `RELEASE_SCOPE_GITLAB__ENDPOINT`.
The projects the links point to are the issue's related services.

The same search returns each issue's relations: its Jira issue links with their type and direction, its parent, and
its subtasks. Issues the report does not hold yet are read once more, with their GitLab links, and marked as related
issues. Their own relations are recorded but not followed, and no project is collected for them. Relations to keys
outside `RELEASE_SCOPE_JIRA_PROJECT_KEYS` are dropped.

An issue also joins the Jira keys of every row its links point to. A key named only in a commit message inside a
merge request still counts for that row and for the tags that ship it.

A linked merge request in a collected service gets its `state` (`opened`, `closed`, `locked`, or `merged`) and
`target_branch`. When a row holds it, it was merged into the default branch and costs no request. Otherwise it is
read from GitLab, and a merged one is cached. The state stays `null` for a commit, for a project outside the report,
and for a merge request GitLab would not return.

## Scoping by issues

`--jira` reads the issues and their GitLab links, then collects every project they link to. In each project, the
rows from the production baseline up to the latest linked change are in scope: they are everything that ships with
the issues. Rows above that change stay in the report with `in_scope: false`, so their tags can still be picked, but
their Jira keys are not looked up and do not count as tasks of a release.

Each service records its release state:

| State | Meaning |
|---|---|
| `pending` | A linked change is in the range. Holds the nearest tag at or above the latest one, or none when a new tag is needed |
| `in_production` | Every linked merge request is already deployed |
| `not_merged` | Only open merge requests link to the service |
| `not_found` | None of the above |

Open merge requests and merges into other branches are listed in every state.

## Next tag

When rows sit above the newest tag, the service's `untagged` counts them and suggests the next tag: the highest
`X.Y.Z` tag with its minor version bumped, or none when no tag has that form. When the tag list was cut short, one
more request fetches the highest versions to work it out.
