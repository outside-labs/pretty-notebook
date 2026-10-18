"""Generate reviewed VPS setup/upgrade bundles without activating a remote host."""

from dataclasses import MISSING, fields
import inspect
import json
from pathlib import Path

from expose_interface import CommandError, Interface, flag, option
from pretty_notebook._internal.deployment import DeploySpec, bundle, write_bundle, check_deployment


def options(function):
    """Expose the shared deployment schema as typed, named program inputs."""
    signature = inspect.signature(function)
    parameters = [p for p in signature.parameters.values() if p.kind is not inspect.Parameter.VAR_KEYWORD]
    annotations = dict(function.__annotations__)
    for field in fields(DeploySpec):
        default = inspect.Parameter.empty if field.default is MISSING else field.default
        parameters.append(inspect.Parameter(field.name, inspect.Parameter.KEYWORD_ONLY,
                                            default=default, annotation=field.type))
        annotations[field.name] = field.type
        function = option('--' + field.name.replace('_', '-'))(function)
    function.__signature__ = signature.replace(parameters=parameters)
    function.__annotations__ = annotations
    return function


def report(action):
    try:
        result = action()
    except (ValueError, OSError) as error:
        raise CommandError(str(error)) from error
    print(json.dumps(result, indent=2))


deploy = Interface('deploy', description='Plan Linux VPS setup, inspect local state, and prepare stopped-site upgrades.')


@deploy.program(name='plan')
@options
@option('--operation', choices=['init', 'upgrade'])
@option('--profile', choices=['vps', 'container'])
def plan(*, operation: str = 'init', profile: str = 'vps', **kwargs):
    """Print an inspectable service/proxy/environment/script plan; write nothing."""
    report(lambda: json.loads(bundle(DeploySpec(**kwargs), operation, profile=profile)['plan.json']))


@deploy.program(name='init')
@options
@option('--output', required=True)
@option('--profile', choices=['vps', 'container'])
def initialize(*, output: Path, profile: str = 'vps', **kwargs):
    """Write an idempotent setup bundle; secrets and live services remain untouched."""
    report(lambda: write_bundle(DeploySpec(**kwargs), output, profile=profile))


@deploy.program(name='upgrade')
@options
@option('--output', required=True)
@option('--profile', choices=['vps', 'container'])
def upgrade(*, output: Path, profile: str = 'vps', **kwargs):
    """Write a pinned upgrade and rollback bundle with a stopped-state checkpoint."""
    report(lambda: write_bundle(DeploySpec(**kwargs), output, operation='upgrade', profile=profile))


@deploy.program(name='check')
@options
@flag('--health', help='Also check the planned loopback health endpoint.')
@flag('--require-bootstrap', help='Require an initial owner-claim secret.')
@option('--profile', choices=['vps', 'container'])
def check(*, health: bool = False, require_bootstrap: bool = False, profile: str = 'vps', **kwargs):
    """Check private configuration, revision, dependencies, local assets and health."""
    if profile == 'container':
        from pretty_notebook._internal.containers import check_container
        report(lambda: check_container(DeploySpec(**kwargs), health=health, require_bootstrap=require_bootstrap))
    else:
        report(lambda: check_deployment(DeploySpec(**kwargs), health=health, require_bootstrap=require_bootstrap))


def recovery_report(action):
    """Keep private filesystem/database failures out of console reports."""
    import sqlite3
    def guarded():
        try:
            return action()
        except (OSError, sqlite3.Error, UnicodeError):
            raise CommandError('Recovery could not verify private files; preserve the original and any incomplete output.') from None
    report(guarded)


@deploy.program(name='backup')
@options
@option('--output', required=True)
@option('--profile', choices=['vps', 'container'])
@flag('--apply', help='Write the backup after verifying that the managed service is stopped.')
def backup(*, output: Path, profile: str = 'vps', apply: bool = False, **kwargs):
    """Preview or create a complete private stopped-site checkpoint in a new location."""
    from pretty_notebook._internal.backups import backup_site
    recovery_report(lambda: backup_site(DeploySpec(**kwargs), output, profile=profile, apply=apply))


@deploy.program(name='restore')
@options
@option('--backup', dest='backup_path', required=True)
@option('--output', required=True)
@option('--profile', choices=['vps', 'container'])
@flag('--apply', help='Restore into a new location after stopped-service and compatibility checks.')
def restore(*, backup_path: Path, output: Path, profile: str = 'vps', apply: bool = False, **kwargs):
    """Verify a checkpoint and prepare new state; never switch or start a service."""
    from pretty_notebook._internal.backups import restore_site
    recovery_report(lambda: restore_site(DeploySpec(**kwargs), backup_path, output, profile=profile, apply=apply))
