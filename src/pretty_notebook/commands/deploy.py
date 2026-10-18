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
