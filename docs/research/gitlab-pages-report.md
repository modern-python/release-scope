# GitLab Pages report with interactive version picking

Research date: 2026-10-06. GitLab docs were read from `gitlab-org/gitlab` master (`VERSION` = `19.5.0-pre`).
Source code links point to the same branch. Release dates come from the GitHub, npm and PyPI APIs on the research date.

Legend: **[src]** is GitLab source code, **[doc]** is official docs. "Unverified" means no primary source was found.

## 1. GitLab Pages mechanics

### Which job publishes

| Mechanism | Status | Version | Source |
|---|---|---|---|
| A job **named** `pages` | Deprecated but still works (legacy branch in code). No removal milestone is listed on the deprecations page. | Long-standing | [doc](https://docs.gitlab.com/ci/yaml/deprecated_keywords/#publish-keyword-and-pages-job-name-for-gitlab-pages), [src `Ci::Build#pages_generator?`](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/models/ci/build.rb) |
| `pages: true` or `pages: {...}` on **any** job name | Current way | 17.5 behind flag `customizable_pages_job_name`, **GA in 17.6** | [doc](https://docs.gitlab.com/user/project/pages/#user-defined-job-names) |
| A job named `pages` with `pages: false` | Does not deploy | 17.6+ | same |
| Job-level `publish: dir` | Deprecated in **17.9** | Introduced 16.1 (flag), on by default for self-managed in **16.2** | [doc](https://docs.gitlab.com/user/project/pages/introduction/#customize-the-default-folder) |
| `pages.publish: dir` | Current. Variables allowed. | **17.9** | [doc](https://docs.gitlab.com/ci/yaml/#pagespublish) |
| `publish` and `pages.publish` together | Deployment fails validation | n/a | [src `DeploymentValidations`](https://gitlab.com/gitlab-org/gitlab/-/blob/master/lib/gitlab/pages/deployment_validations.rb) |

The code decides it like this ([src](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/models/ci/build.rb)). Pages must be enabled on the instance first:

```ruby
return false unless Gitlab.config.pages.enabled
return true if options[:pages].is_a?(Hash) || options[:pages] == true
options[:pages] != false && name == 'pages' # Legacy behaviour
```

On an instance where Pages is disabled, the job runs as an ordinary job and nothing is deployed.

### The `public/` artifact

- The default content directory is `public`, and it needs a non-empty `index.html` at its root ([doc](https://docs.gitlab.com/ci/yaml/#pages)).
- From **17.10**, `public` (or `pages.publish`) is appended to `artifacts:paths` automatically ([doc](https://docs.gitlab.com/ci/yaml/#artifactspaths)). Before 17.10 you must list it yourself.
- The deploy runs only after the job reaches `success` (`after_transition any => [:success]` enqueues `PagesWorker`, see [src](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/models/ci/build.rb)). A failed job, including one with `allow_failure`, does **not** deploy. A job allowed to fail still shows as failed with a warning ([doc](https://docs.gitlab.com/ci/yaml/#allow_failure)). This matters because `collect` exits `1` when a service fails.
- The deploy appears in the pipeline as an extra `pages:deploy` status in the `deploy` stage ([src `UpdatePagesService`](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/services/projects/update_pages_service.rb)).

### Scheduled pipelines

- No Pages-specific restriction on pipeline source was found in the docs or in `UpdatePagesService` / `DeploymentValidations`. A schedule deploys like any other pipeline. Gate the job with `rules: - if: $CI_PIPELINE_SOURCE == "schedule"` ([doc](https://docs.gitlab.com/ci/jobs/job_rules/#run-jobs-for-scheduled-pipelines)).
- Caveat ([src `validate_outdated_sha`](https://gitlab.com/gitlab-org/gitlab/-/blob/master/lib/gitlab/pages/deployment_validations.rb)): a deploy is rejected with "build SHA is outdated for this ref" in one case. This happens when the job's SHA is no longer the ref's HEAD **and** a newer pipeline already deployed to the same `path_prefix`. If only the schedule deploys, this can only hit two overlapping scheduled runs.
- If several Pages jobs share a `path_prefix`, the last one to finish wins ([doc](https://docs.gitlab.com/user/project/pages/#user-defined-job-names)).
- A schedule runs with its owner's permissions, and a manual "Run" uses the clicker's ([doc](https://docs.gitlab.com/ci/pipelines/schedules/#run-manually)). Unverified: whether a manual run of a schedule has `CI_PIPELINE_SOURCE == "schedule"`. The doc only says it triggers the schedule.

### Access control (self-managed)

- **Admin switch:** `gitlab_pages['access_control'] = true` in `gitlab.rb`, which is off by default ([doc](https://docs.gitlab.com/administration/pages/#access-control)).
- **Without that switch, every Pages site is public, even for a private project.** In `ProjectFeature#public_pages?`, the first line is `return true unless Gitlab.config.pages.access_control` ([src](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/models/project_feature.rb)). "Public" here means anyone who can reach the Pages host. The site can still be firewalled: Pages behind a private network is reachable only from inside it ([doc](https://docs.gitlab.com/administration/pages/#prerequisites)).
- **With the switch on:** set per project in **Settings > General > Visibility > Pages** ([doc](https://docs.gitlab.com/user/project/pages/pages_access_control/)):
  - Private project: "Only project members" or "Everyone".
  - Internal project: "Only project members", "Everyone with access" (any logged-in non-external user), or "Everyone".
  - Public project: "Only project members" or "Everyone with access".
  - A member needs at least the Guest role.
- **Reuses GitLab auth:** yes. The Pages daemon is registered as an OAuth application. Unauthenticated users are redirected to GitLab to sign in, and the token is kept in a signed cookie. Each request is checked against the GitLab API ([doc](https://docs.gitlab.com/administration/pages/#access-control)). Since 17.10, scripts can also send `Authorization: Bearer <token>` with `read_api` scope ([doc](https://docs.gitlab.com/user/project/pages/pages_access_control/#authenticate-with-an-access-token)).
- Admins can force non-public sites instance-wide: "Disable public access to Pages sites" ([doc](https://docs.gitlab.com/administration/pages/#disable-public-access-to-all-pages-sites)). A group Owner can do the same for a group, from **17.9** ([doc](https://docs.gitlab.com/user/project/pages/pages_access_control/#remove-public-access-for-group-pages)).
- All of the above is **Free** tier.

### Limits

| Limit | Default | Tier | Source |
|---|---|---|---|
| Max site size (instance) | 100 MB, admin-configurable | Free | [doc](https://docs.gitlab.com/administration/pages/#set-global-maximum-size-of-each-gitlab-pages-site) |
| Per-group / per-project size override | n/a | Premium | same page |
| Files per site | 200,000 | Free | [doc](https://docs.gitlab.com/administration/instance_limits/#number-of-files-per-gitlab-pages-website) |
| Parallel deployments per top-level namespace | 1000 | Premium | [doc](https://docs.gitlab.com/administration/instance_limits/#number-of-parallel-pages-deployments) |

The size is measured on the extracted publish directory ([src `total_size`](https://gitlab.com/gitlab-org/gitlab/-/blob/master/lib/gitlab/pages/deployment_validations.rb)). One HTML file with inline JSON is far below the limit unless the report is huge.

### Parallel deployments and `path_prefix`

- **Tier: Premium/Ultimate.** Experiment in 16.7 behind flag `pages_multiple_versions_setting`. Enabled by default in 17.4, project setting removed in 17.7, periods allowed in 17.8, **GA in 17.9** ([doc](https://docs.gitlab.com/user/project/pages/parallel_deployments/), [doc](https://docs.gitlab.com/ci/yaml/#pagespath_prefix)).
- `path_prefix` is lowercased, cut to 63 bytes, and characters other than `[a-z0-9.]` become `-`. The site is then served at `<site>/<prefix>/`.
- **Parallel deployments expire after 24 h by default.** For long-lived per-group reports, set `pages.expire_in: never` (Premium, 17.4+) ([doc](https://docs.gitlab.com/ci/yaml/#pagesexpire_in)). An admin can change the default ([doc](https://docs.gitlab.com/administration/pages/#configure-the-default-expiry-for-parallel-deployments)).
- A prefix that matches a folder of the main deployment shadows it ([doc](https://docs.gitlab.com/user/project/pages/parallel_deployments/#path-clash)).
- **Free-tier alternatives for one report per group:**
  - Render all groups into subfolders (`public/backend/`, `public/frontend/`) in **one** job, because each deploy replaces the whole site.
  - Or use one Pages project per group.

### Single `index.html` with inline JS and JSON

Yes. Pages serves static files, including "plain HTML, CSS, JavaScript, and Wasm"; server-side processing is not supported ([doc](https://docs.gitlab.com/user/project/pages/)). Notes:

- Project sites are served under `/<project-path>/`, and URLs ending in `/` break relative links ([doc](https://docs.gitlab.com/user/project/pages/introduction/#broken-relative-links)). A single file with everything inline avoids this.
- Admins can add response headers such as CSP via `gitlab_pages['headers']` ([doc](https://docs.gitlab.com/administration/pages/#global-settings)). No default CSP header was found in the docs (unverified that none is set). A strict CSP without `unsafe-eval` breaks standard Alpine.js, which then needs its CSP build ([doc](https://github.com/alpinejs/alpine/blob/main/packages/docs/src/en/advanced/csp.md)).

### Hosting in a different project

- A Pages site belongs to the project whose pipeline ran the Pages job. The deployment is created on `build.project` ([src](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/services/projects/update_pages_service.rb)). A job **cannot** publish into another project's Pages.
- So the design is: a dedicated "docs" or "release-report" project holds `.gitlab-ci.yml`, the schedule, the CI variables and the Pages site. `collect` reads the service projects through the REST API with `RELEASE_SCOPE_GITLAB__TOKEN` (`read_api`), as the current README already describes. The service projects need no changes.
- Viewer access is governed by membership of the **docs project** when access control is "Only project members". Readers must be added there, or the docs project should be internal with "Everyone with access".

## 2. Building an interactive page from Python-produced JSON

Requirement recap: per-service radio groups with a "none" option, three derived lists (union of Jira keys, pipelines, compare links) that update live, copy-friendly output, and a static overview.

### Options

| Option | CI build needs | Runtime weight | Derived state | License | Latest release (verified) | Fit for `release-scope render --output public/` |
|---|---|---|---|---|---|---|
| **Python template + vanilla JS** (stdlib `string.Template`/`str.replace`, `json.dumps`) | Python only | ~0 KB library; your own JS | Hand-written: a `change` handler recomputes 3 lists | n/a (your code) | n/a | Best: no new runtime dependency |
| **Python template + Alpine.js, vendored** | Python only | `cdn.min.js` 3.17.4: 55.9 KB raw / 19.9 KB gzip (measured) | `x-data` getters act as computed properties, uncached ([doc](https://github.com/alpinejs/alpine/blob/main/packages/docs/src/en/directives/data.md)) | MIT | 3.17.4, 2026-09-21 (npm, GitHub) | Very good: ship one `.js` file as package data |
| Python template + Preact + htm standalone (ESM) | Python only | `htm/preact/standalone.mjs`: 13.2 KB raw / 5.3 KB gzip | Hooks/`useMemo` | MIT / Apache-2.0 | preact 11.0.0, 2026-09-30; **htm 3.1.1, 2022-04-26** | Good, but the htm bundle is stale and the code is more verbose than Alpine |
| Python template + petite-vue | Python only | 16.9 KB raw / 7.1 KB gzip | Vue-like reactivity | MIT | **0.4.1, 2022-01-18**; last push 2024-07-13 | Not recommended: effectively unmaintained |
| Jinja2 instead of stdlib templating | Adds `jinja2` (BSD-3-Clause) dependency | none | n/a (server side only) | BSD-3-Clause | 3.1.6, 2025-03-05 (PyPI) | Useful only if the overview is rendered server-side as HTML. Autoescaping helps; otherwise unnecessary |
| Observable Framework | **Node >= 18** ([doc](https://github.com/observablehq/framework/blob/main/docs/getting-started.md)); `npm:` imports downloaded from **jsDelivr at build time** ([doc](https://github.com/observablehq/framework/blob/main/docs/imports.md)) | Multi-file site, Observable runtime + Inputs | Excellent: reactive cells, `Inputs.radio([... , null])` supports "none" ([doc](https://github.com/observablehq/framework/blob/main/docs/inputs/radio.md)) | ISC | 1.13.4, 2026-03-02; last commit 2026-05-15 (slowing) | Poor: the CLI would shell out to `npx`; a Node image is needed in CI; build-time CDN access breaks behind a firewall |
| Evidence | Node toolchain; the repo now distributes a new CLI via `curl ... install.sh` and Evidence Studio ([README](https://github.com/evidence-dev/evidence/blob/main/README.md)) | SvelteKit site + DuckDB-wasm (unverified size) | Input components exist (e.g. `ButtonGroup`), SQL-driven | MIT | npm `@evidence-dev/evidence` 40.1.8, 2026-02-06; repo active (commits 2026-10-02), product in transition | Poor: SQL/BI-oriented, heavy, distribution in flux |
| Quarto + OJS | `quarto` binary. The PyPI `quarto-cli` is an sdist that **downloads the binary from GitHub at install time** (read in `setup.py`) | OJS runtime; `embed-resources: true` gives one file ([doc](https://github.com/quarto-dev/quarto-web/blob/main/docs/output-formats/html-basics.qmd)) | Excellent: `viewof` + Inputs, reactive ([doc](https://github.com/quarto-dev/quarto-web/blob/main/docs/interactive/ojs/index.qmd)) | MIT | 1.10.19, 2026-10-06 | Poor: a large external binary, GitHub download behind firewall; whether OJS pulls libraries from a CDN at runtime is unverified |
| Streamlit via stlite | None at build time (HTML embeds Python source) | Loads Pyodide + Streamlit wheels in the browser. `@stlite/browser` is 110 MB unpacked on npm; Pyodide comes **from a CDN by default**, and self-hosting needs the full Pyodide distribution ([README](https://github.com/whitphx/stlite/blob/main/README.md)) | Yes (Streamlit reruns) | Apache-2.0 | `@stlite/browser` 1.9.2, 2026-09-23 | Poor: seconds-to-load page, CDN dependency, heavy self-hosting |
| Datasette-lite | None (hosted app at lite.datasette.io) | Pyodide + Datasette | No picker UI; it is a SQL explorer. Data must be on a CORS-enabled URL ([README](https://github.com/simonw/datasette-lite/blob/main/README.md)) | Apache-2.0 | No releases (deployed app); last push 2026-08-09 | Not a fit |
| Panel (`panel convert` to Pyodide) | Python | Pyodide-based (unverified size) | Yes | BSD-3-Clause | 1.9.4, 2026-08-17 (PyPI) | Same Pyodide weight and CDN issue as stlite; listed for completeness, not deeply evaluated |

### Vendor or CDN

**Vendor the library into the wheel.**

- `uv_build` packages everything under the module root, so `release_scope/_static/alpine.min.js` ships in the wheel with no config. Only `__pycache__`, `*.pyc` and `*.pyo` are excluded by default ([doc](https://github.com/astral-sh/uv/blob/main/docs/concepts/build-backend.md#file-inclusion-and-exclusion)). Read it with `importlib.resources.files("release_scope")` (stdlib).
- **Inline** it into `index.html` rather than copying it next to it. One file works opened from `file://`, as a CI artifact download, or on Pages. It is immune to the trailing-slash relative-link issue and has no runtime CDN dependency behind a firewall.
- A CDN `<script src>` fails silently on air-gapped networks. Alpine's own docs recommend pinning an exact version if a CDN is used ([doc](https://github.com/alpinejs/alpine/blob/main/packages/docs/src/en/essentials/installation.md)).
- Cost of vendoring: about 56 KB in the wheel, plus updating the file by hand. Keep the MIT license text next to it.

### Implementation notes that affect the choice

- **Inline JSON safely:** put it in `<script type="application/json" id="data">`, which the HTML spec defines as a "data block" ([spec](https://html.spec.whatwg.org/multipage/scripting.html#data-block)). Escape `<` as `<` so a Jira summary containing `</script>` cannot end the element ([spec](https://html.spec.whatwg.org/multipage/scripting.html#restrictions-for-contents-of-script-elements)). Parse it with `JSON.parse`.
- **Keep the logic in Python:** precompute a view model in Python. For each service with a production deploy, list the candidate tags. For each tag, store the **cumulative** Jira keys from that tag's row down to the oldest row, the tag pipeline (`TagRef.pipeline`), and the compare URL. The current `_compare` in `_render.py` builds that link.
  - JS then only takes a union in pick order and renders. The derivation stays under pytest and 100% coverage, and the JS stays at a few dozen lines regardless of framework.
- **Copy buttons:** `navigator.clipboard` is `[SecureContext]`, which means HTTPS or localhost only ([spec](https://w3c.github.io/clipboard-apis/)). If the instance serves Pages over plain HTTP, the API is missing. Always render each list in a `<textarea readonly>` or `<pre>` as well, so select-and-copy works.
  - Useful formats: one key per line, a comma-separated list for JQL `key in (...)`, and Markdown links for the release post.
- **Overview tables:** these can be rendered server-side as static HTML with `html.escape` (readable without JS) or client-side from the same JSON. Server-side keeps Python testable; client-side keeps one renderer.

## 3. `.gitlab-ci.yml`

Two jobs. Pages deploys only on `success`, and `collect` exits `1` on a partial failure. So the first job records the exit code and still succeeds, and the second job turns it back into a red pipeline after the deploy is queued. Only scheduled pipelines create either job.

Version for GitLab **17.10+** (`pages: true` needs 17.6; automatic `public` artifact needs 17.10):

```yaml
release-report:
  stage: build
  image: python:3.13-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  script:
    - pip install 'release-scope==<version>'
    - release-scope collect --group team/backend --output report.json; echo "$?" > collect.status
    - release-scope render report.json --output public/
  pages: true
  artifacts:
    paths:
      - report.json
      - collect.status

collect-status:
  stage: test
  image: python:3.13-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  needs: [release-report]
  script:
    - exit "$(cat collect.status)"
```

Changes for **GitLab < 17.6**:

- Name the first job `pages` and drop `pages: true`. This is the legacy branch in `pages_generator?`.
- Add `public` to `artifacts:paths`.

The legacy form still works on current versions but is deprecated ([doc](https://docs.gitlab.com/ci/yaml/deprecated_keywords/#publish-keyword-and-pages-job-name-for-gitlab-pages)).

Syntax references:

- `pages` ([doc](https://docs.gitlab.com/ci/yaml/#pages)) and `artifacts:paths` with automatic append in 17.10 ([doc](https://docs.gitlab.com/ci/yaml/#artifactspaths)).
- Default stages `.pre, build, test, deploy, .post` ([doc](https://docs.gitlab.com/ci/yaml/#stages)) and `rules:if` on `CI_PIPELINE_SOURCE` ([doc](https://docs.gitlab.com/ci/jobs/job_rules/#run-jobs-for-scheduled-pipelines)).
- `$CI_PAGES_URL` is available in the job to print the site URL ([doc](https://docs.gitlab.com/ci/variables/predefined_variables/)).

If `render` fails, the job fails and the previous site stays live.

Optional additions:

- Premium, one site per group: add `pages: {path_prefix: backend, expire_in: never}` per job.
- Free: render several groups into `public/<group>/` in one job.
- Air-gapped runners: install from an internal PyPI mirror. The image must be pullable.

## 4. Recommendation

1. **Python-rendered single `index.html` + vendored, inlined Alpine.js (recommended).**
   - Pros: Python-only CI. No new Python dependency if stdlib templating is used. Declarative radios and getters fit "picks drive computed lists" directly. Small (20 KB gzip). Actively maintained, MIT. Works offline and from `file://`.
   - Cons: an `x-` attribute DSL inside HTML strings that Python tests do not exercise. Needs the CSP build if the admin sets a strict CSP. One file to bump by hand.
2. **Same, but vanilla JS (no library).**
   - Pros: zero third-party code and zero supply-chain or vendoring work. The interactivity is small (radio `change` leads to recomputing three lists from precomputed data).
   - Cons: manual DOM updates and more code to write. Fine if the precomputed view model keeps the JS to about 100 lines. Pick this over Alpine if the dependency-free property matters more than terseness.
3. **Observable Framework** only if the page will grow into a real dashboard with charts.
   - Pros: best-in-class reactivity and `Inputs.radio` with `null`.
   - Cons: a Node toolchain in CI, build-time jsDelivr access, a multi-file output, and the CLI could no longer emit the site by itself. Release cadence slowed in 2026.

Rejected: Quarto (external binary fetched from GitHub), stlite and Panel (Pyodide weight plus CDN), Datasette-lite (no picker UI), Evidence (BI/SQL-oriented, distribution in transition), petite-vue (unmaintained since 2022).

In every option, precompute the cumulative Jira keys, pipeline and compare URL per candidate tag in Python. Then the browser only does a union.

## Open questions for the user

1. GitLab version and tier of the instance? `pages: true` needs **17.6**, automatic `public` artifact needs **17.10**, and `path_prefix` / `expire_in` need **Premium** (GA 17.9).
2. Is Pages enabled on the instance (`Gitlab.config.pages.enabled`), and what is the Pages domain? Is it served over **HTTPS**? This matters for the clipboard API.
3. Is Pages **access control** on (`gitlab_pages['access_control']`)? If not, the site is public to anyone who reaches the Pages host, regardless of project visibility. Is that acceptable for Jira summaries and internal URLs?
4. Who should see the page? Members of the docs project only, or every logged-in user (internal project + "Everyone with access")?
5. One report or several (per group)? On Free, use subfolders in one deploy or one project per group. On Premium, use `path_prefix` with `expire_in: never`.
6. Does the instance set a CSP header on Pages (`gitlab_pages['headers']`)? This decides standard Alpine versus its CSP build.
7. Are rows guaranteed newest-first, so that "picked tag down to the oldest row" is a suffix of `Service.rows`? Can one row carry several tags, and if so which tag represents it?
8. Should `render` keep a Markdown mode and `publish` stay, or are both removed? There are no users, so both can go.
9. Is a new runtime dependency (Jinja2) acceptable, or must the site use stdlib templating only?
10. Copy formats wanted for the Jira release and the release post (plain keys, JQL list, Markdown, Jira wiki markup)?
