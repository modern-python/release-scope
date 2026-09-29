# release-scope

A CLI that reports, per GitLab service, every change between the commit running in production and the head of the
default branch, as one JSON report.

## Language

**Service**:
One GitLab project in the report. Not "repo" or "app": a service is whatever project a `--group` or `--project`
selected, deployable or not.

**Production baseline**:
The commit of the latest successful deployment to the production environment. The range starts there, not at a
tag. Avoid "current version", which suggests a tag.

**Range**:
The first-parent commits of the default branch that the production baseline does not contain, newest first.

**Row**:
One unit of the range: a merged merge request (its merge, squash, or fast-forwarded commits) or a single direct
commit. Not "change" or "entry". A row carries the tags pointing into it; a row without a tag is still a row.

**Main pipeline**:
The latest `push` pipeline on the default branch for a row's newest commit. Distinct from the **tag pipeline**, the
latest pipeline whose ref is a tag in the row.

**Failed job**:
A job or bridge whose status is `failed`, including those with `allow_failure`; the flag is reported, not filtered.

**Not done**:
A Jira issue whose status category is anything but `done`. Jira's category, not the status name, which each workflow
names differently.

**Related service**:
A GitLab project that a Jira issue's Web links point to through a merge request or commit, other than the service
the row belongs to. It need not be in the report.

**Settled fact**:
Data GitLab will not change for the same key, and so the only data the cache may hold.
