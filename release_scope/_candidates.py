from urllib.parse import quote

from release_scope._report import Candidate, EnvironmentState, Service


def build_candidates(service: Service, production: EnvironmentState | None) -> list[Candidate]:
    base: str | None = None
    if production is not None:
        base = quote(production.ref if production.tag else production.sha)
    candidates: list[Candidate] = []
    for index, row in enumerate(service.rows):
        shipped = service.rows[index:]
        keys = {key.key: key for item in shipped if item.in_scope for key in item.jira_keys}
        candidates.extend(
            Candidate(
                tag=tag,
                compare_url=f"{service.project_url}/-/compare/{base}...{quote(tag.name)}"
                if base
                else f"{service.project_url}/-/commits/{quote(tag.name)}",
                rows=len(shipped),
                jira_keys=list(keys.values()),
            )
            for tag in row.tags
        )
    return candidates
