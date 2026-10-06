import importlib.resources
import os
import pathlib
import tempfile
import typing


_STATIC: typing.Final = importlib.resources.files("release_scope") / "_static"


def write_text_atomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    pathlib.Path(handle.name).replace(path)


def write_site(directory: pathlib.Path, report_json: str) -> None:
    for item in _STATIC.iterdir():
        write_text_atomic(directory / item.name, item.read_text(encoding="utf-8"))
    write_text_atomic(directory / "report.json", report_json)
