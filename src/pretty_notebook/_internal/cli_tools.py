"""Small application-specific CLI converters and editor support."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from expose_interface import CommandError


def limit_value(value):
    result = int(value)
    if not 1 <= result <= 200:
        raise ValueError("expected an integer from 1 to 200")
    return result


def offset_value(value):
    result = int(value)
    if result < 0:
        raise ValueError("expected a nonnegative integer")
    return result


def existing_file(value):
    path = Path(value)
    if not path.is_file():
        raise ValueError("expected an existing file")
    return path


def edit_text(text):
    """Edit private temporary Markdown using VISUAL, EDITOR, or the platform editor."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    with tempfile.TemporaryDirectory(prefix="pnbp-edit-") as temporary:
        path = Path(temporary) / "note.md"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        try:
            command = shlex.split(editor)
            if not command:
                raise ValueError("The editor command is empty.")
            subprocess.run([*command, str(path)], check=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise CommandError("The editor could not complete; the note was not changed.") from error
        edited = path.read_text(encoding="utf-8")
        return None if edited == text else edited
