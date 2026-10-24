# The page

`collect` writes `index.html` and its script next to `report.json`. They come from the installed package and change
only with it, so the page always matches the report schema. The page loads `report.json` from next to itself, so it
needs a web server; a `file://` URL will not work. The [demo](https://modern-python.github.io/release-scope/) shows
everything below on made-up data.

## Language, theme, and time

Switches at the top pick the language (English or Russian) and the theme (system, light, or dark). The page starts
in the browser's language and remembers both choices. The copied lists, the release post, and the warnings and
errors from `collect` follow the language. Texts from GitLab and Jira, such as titles, statuses, and Jira's own error
details, stay as written.

Times show in the browser's time zone. Hover over one to see the value the report holds.

## Services

Each service is one line, named by its repository, such as `api` for `shop/api`. When two projects on the page share
a name, each keeps as many parent groups as it takes to tell them apart, such as `shop/admin` and `legacy/admin`.
Hover over a name to see the full path. It shows:

- what production runs and the picked tag;
- how many merge requests or commits and Jira tasks the pick ships;
- the failed jobs of the picked tag, or of the newest tag before a pick, counting the jobs allowed to fail apart.
  These are the failures of the tag's pipeline and of the main pipeline of its commit. Failures in other rows show
  only when the line is opened;
- how many rows have no tag yet, with a `+` when the range was cut at `RELEASE_SCOPE_MAX_COMMITS` and holds no tag,
  so more untagged rows may lie below;
- a mark when the range was cut.

A service whose production runs the head of the default branch is marked green as fully deployed. The page lists
every service with a production deployment or with rows, and every service that failed to collect. Services with
neither are left out.

Opening a line shows:

- the environments, with when each was deployed;
- warnings, and merge requests that are not merged yet;
- a link to create the next tag on the head, when rows have no tag yet;
- the rows, each with its tags and their pipelines, its merge requests or commits with when they were merged or
  committed, Jira keys with their status, the time each environment first ran it, and failed jobs. Rows out of scope
  are dimmed. A key the merge request or commit does not mention, which the row carries only because the Jira
  issue links to the change, is underlined with a dashed line and marked `via Jira`; hover over it for the reason.

Links open in a new tab, including the GitLab settings pages that warnings and errors point to.

## Picking tags

Each tag has a **pick** button. Picking a tag highlights the rows it ships and closes the line, which then shows the
tag as a blue chip. The chip's `×` clears the pick without opening the line. A `--jira` report starts with each
service's release tag picked.

The address keeps the picks after `#`, as `team/api=2.4.0&team/web=5.12.0`, so sharing or reloading the page keeps
them. An address with picks replaces the release tags of a `--jira` report. Picks the report does not have, such as a
tag a later run no longer lists, are skipped with a warning. Clearing every pick empties the address, so a reload
starts from the release tags again.

## Choosing issues

When the report has Jira issues, the **Issues** list at the top of the Release column picks tags from issues instead.
It lists every issue in the report, Done first and the rest after, by Jira's status category. Related issues, which
the report holds only because another issue relates to them, come last in a group of their own. Hover over a key to
see its relations, such as `is blocked by SHOP-44`. You can filter it by
key or summary, or show only the chosen issues.

Under each issue are the services it touches, each with one of:

| Label | Meaning |
|---|---|
| a tag | The tag that ships the issue |
| `no tag yet` | The issue's rows sit above the newest tag |
| `not in this report` | The issue links to a project the report does not cover |
| `failed to collect` | The service failed |
| `not merged` | A linked merge request is still open |
| `in prod` | A linked merge request was merged into the default branch and is already deployed |
| `older than the range` | Shown instead of `in prod` when the range was cut |
| `merged into <branch>` | A linked merge request was merged into another branch |
| `closed` | A linked merge request was closed |
| `in prod or not merged` | A linked commit, or a merge request GitLab would not return |

Ticking an issue picks, in every service it touches, the tag a `--jira` run would make its release tag: the nearest
tag at or above the newest row the issue links to or names. When several chosen issues touch a service, the newest
of their tags wins. When one of them has no tag yet, the service gets no pick, and its line links to create the next
tag.

Each touched service names the chosen issues it is picked for and the other Jira keys its tag also ships. Those
issues are marked `ships anyway` in the list. A chosen issue that links only to changes outside the range shows why
it has nothing to ship there, such as `SHOP-150 not merged`. Services no chosen issue touches are dimmed, and
projects the issues link to that are not in the report are listed under the services.

Unticking an issue clears the picks only it needed. It works the other way too: clearing a pick, or picking an older
tag that does not ship a chosen issue, unticks that issue, and the picks only it needed in other services go with it.
An address whose picks miss a chosen issue loads with the issue unticked. The address keeps the issues before the
picks, as `issues=SHOP-140,SHOP-141&team/api=2.5.0`.

## Release

The **Release** column sits next to the services and stays in view while they scroll, or goes below them on a narrow
screen. While a service is open, the column folds into a strip with the number of picked tags and tasks, so the rows
get the full width. Clicking the strip closes the service.

Above the tabs, **Left behind by these picks** lists what the picked tags leave out, grouped by each Jira task they
ship. A group opens with the task's key, linked to Jira, and its summary. Under it come the services the task still
misses, then each issue the task depends on: one that blocks it through Jira's `Blocks` link type, and its subtasks.
Those issues show their key and summary too, and the services they miss sit under them.

- a service where the task or an issue it depends on has changes that no pick covers, with the tag it needs or why
  there is none: `no tag yet`, `not merged`, `merged into <branch>`, `in prod or not merged`, `not in this report`, or
  `failed to collect`;
- an issue the task depends on with no changes at all that is not done in Jira, with its status.

A service that needs a tag has a **Pick** button for it, which picks the tag without opening the service. `no tag yet`
links to create the next tag, and `not merged`, `merged into <branch>`, and `in prod or not merged` link to the merge
requests or commits. When any line needs a tag, a button next to the title picks every needed tag at once, the newest
one per service. A newer pick can ship more tasks, and the list then shows what those leave behind.

Changes already in production and closed merge requests are not listed. Other relations, such as `blocks`,
`relates to`, or a parent, do not hold a release back; they show only when you hover over the issue's key.

It turns the picked tags into four tabs. Each has a copy button and a text box to copy from by hand, since browsers
allow the copy button only over HTTPS.

- **Jira tasks**: the keys of every in-scope row from each picked tag down to production, without duplicates, with
  summary, a status badge (grey for to do, blue for in progress, green for done), and the merge requests or commits
  that bring each one, such as `from api !57, web !120`. Copy them one per line, or as a
  JQL `key in (...)` clause.
- **Tag pipelines**: the pipeline of each picked tag, as a Markdown list.
- **Compare**: a GitLab compare link per service from production to the picked tag, as a Markdown list. A service
  never deployed to production gets the tag's commit history instead.
- **Release post**: one Markdown text with a line per picked tag, holding its compare link and pipeline, followed by
  the Jira tasks with their summaries.
