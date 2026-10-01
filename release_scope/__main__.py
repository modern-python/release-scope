import importlib.metadata
import json
import pathlib
import typing

import modern_di_typer
import typer

from release_scope import ioc
from release_scope._cache import Cache
from release_scope._errors import ConfigError, ReleaseScopeError
from release_scope._files import write_text_atomic
from release_scope._jira_keys import JIRA_KEY_PATTERN
from release_scope._publish import PublishUseCase
from release_scope._render import render_markdown
from release_scope._report import SCHEMA_VERSION, Report
from release_scope._settings import Settings, load_settings
from release_scope._use_case import CollectUseCase


_PACKAGE_NAME: typing.Final = "release-scope"


MAIN_APP: typing.Final = typer.Typer(
    name="release-scope",
    help="Collect what sits between production and the default branch across GitLab services.",
    no_args_is_help=True,
    add_completion=False,
)

modern_di_typer.setup_di(MAIN_APP, ioc.container)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(importlib.metadata.version(_PACKAGE_NAME))
    raise typer.Exit


@MAIN_APP.callback()
def _main_callback(
    _version: typing.Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    pass


@modern_di_typer.inject
def _resolve_use_case(
    use_case: typing.Annotated[CollectUseCase, modern_di_typer.FromDI(CollectUseCase)],
) -> CollectUseCase:
    return use_case


@modern_di_typer.inject
def _resolve_publish_use_case(
    use_case: typing.Annotated[PublishUseCase, modern_di_typer.FromDI(PublishUseCase)],
) -> PublishUseCase:
    return use_case


@MAIN_APP.command("collect", help="Collect pending changes per service into a JSON report.")
def _collect_command(  # noqa: PLR0913, PLR0917
    ctx: typer.Context,
    output: typing.Annotated[pathlib.Path, typer.Option("--output", "-o", help="Where to write the report JSON.")],
    group: typing.Annotated[
        list[str] | None, typer.Option("--group", "-g", help="GitLab group path; repeatable.")
    ] = None,
    project: typing.Annotated[
        list[str] | None, typer.Option("--project", "-p", help="GitLab project path; repeatable.")
    ] = None,
    include_subgroups: typing.Annotated[
        bool, typer.Option("--include-subgroups", help="Also collect projects in subgroups of each --group.")
    ] = False,
    cache_path: typing.Annotated[
        pathlib.Path | None,
        typer.Option("--cache", help="Cache JSON; read if present, rewritten in place after the run."),
    ] = None,
    jira: typing.Annotated[
        list[str] | None,
        typer.Option("--jira", "-j", help="Jira issue key; collect only the services it links to. Repeatable."),
    ] = None,
) -> None:
    try:
        _check_selection(groups=group or [], projects=project or [], keys=jira or [])
        settings = load_settings({})
        modern_di_typer.fetch_di_container(ctx).set_context(Settings, settings)
        cache, cache_warning = Cache.load(cache_path) if cache_path else (Cache(), None)
        if cache_warning:
            typer.echo(f"Warning: {cache_warning}", err=True)
        use_case = _resolve_use_case(ctx=ctx)
        if jira:
            report = use_case.for_issues(keys=list(dict.fromkeys(jira)), cache=cache)
        else:
            report = use_case(
                groups=group or [], projects=project or [], include_subgroups=include_subgroups, cache=cache
            )
    except ReleaseScopeError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err

    write_text_atomic(output, report.model_dump_json(indent=2))
    if cache_path:
        cache.save(cache_path)
    failed: typing.Final = [service for service in report.services if service.error]
    rows: typing.Final = sum(len(service.rows) for service in report.services)
    typer.echo(f"{len(report.services)} services, {rows} rows, {len(failed)} failed -> {output}", err=True)
    for service in failed:
        typer.echo(f"Error: {service.error}", err=True)
    jira_errors: typing.Final = _jira_errors(report)
    for message in jira_errors:
        typer.echo(f"Error: {message}", err=True)
    if failed or jira_errors:
        raise typer.Exit(code=1)


def _check_selection(
    *, groups: typing.Sequence[str], projects: typing.Sequence[str], keys: typing.Sequence[str]
) -> None:
    if keys and (groups or projects):
        msg = "Pass either --jira or --group/--project, not both."
        raise ConfigError(msg)
    if not keys and not groups and not projects:
        msg = "Pass --jira, or at least one --group or --project."
        raise ConfigError(msg)
    for key in keys:
        if not JIRA_KEY_PATTERN.fullmatch(key):
            msg = f"Not a Jira issue key: {key}."
            raise ConfigError(msg)


def _jira_errors(report: Report) -> list[str]:
    if report.jira is None:
        return []
    errors: typing.Final = [f"Jira has no issue {key}." for key in report.jira_scope if key in report.jira.missing]
    if report.jira.error:
        errors.append(report.jira.error)
    return errors


@MAIN_APP.command("render", help="Render a JSON report as a Markdown page for a GitLab wiki.")
def _render_command(
    report_path: typing.Annotated[pathlib.Path, typer.Argument(help="Report JSON written by `collect`.")],
    output: typing.Annotated[pathlib.Path, typer.Option("--output", "-o", help="Where to write the Markdown page.")],
) -> None:
    try:
        raw = json.loads(report_path.read_bytes())
        version = raw.get("schema_version") if isinstance(raw, dict) else None
        if isinstance(version, int) and version < SCHEMA_VERSION:
            typer.echo(
                f"Error: Cannot read report {report_path}: schema_version {version} is not supported; "
                "run collect again.",
                err=True,
            )
            raise typer.Exit(code=ConfigError.exit_code)
        report = Report.model_validate(raw)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: Cannot read report {report_path}: {type(exc).__name__}.", err=True)
        raise typer.Exit(code=ConfigError.exit_code) from exc
    try:
        write_text_atomic(output, render_markdown(report))
    except OSError as exc:
        typer.echo(f"Error: Cannot write page {output}: {type(exc).__name__}.", err=True)
        raise typer.Exit(code=ReleaseScopeError.exit_code) from exc
    typer.echo(f"{len(report.services)} services -> {output}", err=True)


@MAIN_APP.command("publish", help="Replace the content of an existing GitLab wiki page with a rendered page.")
def _publish_command(
    ctx: typer.Context,
    page_path: typing.Annotated[pathlib.Path, typer.Argument(help="Markdown page written by `render`.")],
    project: typing.Annotated[str, typer.Option("--project", "-p", help="GitLab project path that holds the wiki.")],
    page: typing.Annotated[str, typer.Option("--page", help="Slug of the wiki page, such as releases/backend.")],
) -> None:
    try:
        content = page_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: Cannot read page {page_path}: {type(exc).__name__}.", err=True)
        raise typer.Exit(code=ConfigError.exit_code) from exc
    try:
        settings = load_settings({})
        modern_di_typer.fetch_di_container(ctx).set_context(Settings, settings)
        published = _resolve_publish_use_case(ctx=ctx)(project=project, slug=page, content=content)
    except ReleaseScopeError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err
    typer.echo(f"{'Updated' if published.updated else 'Unchanged'} {published.url}", err=True)


def main() -> None:
    with ioc.container:
        MAIN_APP()


if __name__ == "__main__":
    main()
