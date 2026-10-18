"""Capture the public console entry point using only standard-library tools."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from unittest.mock import patch


@dataclass
class Result:
    exit_code: int
    output: str
    exception: BaseException | None = None


class CliRunner:
    def invoke(self, cli, args, *, input=""):
        output = StringIO()
        exception = None
        status = 0
        with redirect_stdout(output), redirect_stderr(output), patch("sys.stdin", StringIO(input)):
            try:
                cli(args)
            except SystemExit as error:
                status = error.code or 0
            except Exception as error:
                status, exception = 1, error
        return Result(status, output.getvalue(), exception)
