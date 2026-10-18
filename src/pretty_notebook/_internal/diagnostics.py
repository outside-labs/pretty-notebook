"""Bounded notebook diagnostics that return no private configuration or content."""

from importlib import metadata, util
import os
from pathlib import Path


def diagnose_notebook(selection):
    from pretty_notebook.models import Notebook
    checks = []

    def record(name, status, message):
        checks.append({'check': name, 'status': status, 'message': message})

    for distribution, module in (('expose-interface', 'expose_interface'), ('requests', 'requests'), ('rich', 'rich')):
        try:
            version = metadata.version(distribution)
            if util.find_spec(module) is None:
                raise metadata.PackageNotFoundError(distribution)
            record(distribution, 'ok', 'Installed version ' + version[:64])
        except (metadata.PackageNotFoundError, ValueError, ImportError):
            record(distribution, 'error', 'Required runtime package is unavailable.')
    try:
        notebook = Notebook(**selection)
    except (ValueError, OSError, RuntimeError, ImportError, KeyError):
        record('settings', 'error', 'Notebook settings or source could not be loaded; inspect local configuration.')
    else:
        record('settings', 'ok', 'Settings loaded without initialization writes.')
        root = Path(notebook.NOTE_PATH)
        readable = root.is_dir() and os.access(root, os.R_OK | os.X_OK)
        record('notebook-path', 'ok' if readable else 'error', 'Notebook directory is readable.' if readable else 'Notebook directory is unavailable.')
        record('notebook-write', 'ok' if os.access(root, os.W_OK) else 'warning', 'Directory access checked without writing a probe file.')
        credentials = notebook.credentials_file
        if credentials and Path(credentials).exists():
            private = not Path(credentials).is_symlink() and not Path(credentials).stat().st_mode & 0o077
            record('credentials-permissions', 'ok' if private else 'error', 'Credential files must be private regular files.')
        try:
            identity = notebook.identity_status(limit=1)
            state = identity['state']
            status = ('error' if state == 'invalid' else 'warning' if state != 'initialized' or identity.get('missing_count') or identity.get('unindexed_count') else 'ok')
            record('identities', status, 'Identity index checked; use identity status for repair details.' if state != 'missing' else 'Optional identity index is absent; initialize it explicitly when needed.')
        except (ValueError, OSError, RuntimeError):
            record('identities', 'error', 'Identity metadata could not be verified.')
        if (root / '.pnbp/metadata.lock').exists():
            record('identity-operation', 'warning', 'An identity operation lock exists; inspect it before changing identities.')
        backend = notebook.settings.markdown_backend
        available = backend != 'python-markdown' or util.find_spec('markdown') is not None
        record('renderer', 'ok' if available else 'error', 'Configured renderer: ' + backend)
    return {'ok': not any(check['status'] == 'error' for check in checks), 'checks': checks}
