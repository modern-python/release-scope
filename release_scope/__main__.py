import importlib.metadata
import pathlib
import typing

import modern_di_typer
import typer

from release_scope import ioc
from release_scope._cache import Cache
from release_scope._errors import ConfigError, ReleaseScopeError
from release_scope._files import write_text_atomic
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
) -> None:
    try:
        if not group and not project:
            msg = "Pass at least one --group or --project."
            raise ConfigError(msg)
        settings = load_settings({})
        modern_di_typer.fetch_di_container(ctx).set_context(Settings, settings)
        cache, cache_warning = Cache.load(cache_path) if cache_path else (Cache(), None)
        if cache_warning:
            typer.echo(f"Warning: {cache_warning}", err=True)
        report = _resolve_use_case(ctx=ctx)(
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
    if failed:
        raise typer.Exit(code=1)


def main() -> None:
    with ioc.container:
        MAIN_APP()


if __name__ == "__main__":
    main()
