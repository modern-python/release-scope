import collections.abc
import contextlib
import functools
import http.server
import pathlib
import threading
import typing


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:  # noqa: A002, ANN401
        pass


@contextlib.contextmanager
def serve(directory: pathlib.Path) -> collections.abc.Generator[str, None, None]:
    server: typing.Final = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(directory))
    )
    thread: typing.Final = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
