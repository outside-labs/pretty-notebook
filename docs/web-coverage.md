# Web coverage audit (0.10)

Coverage measures executed code, not a percentage of security or correctness.
The former 95–96% figure did not mean that 4–5% of the site was exposed. Missing
lines included storage failures, invalid configuration, corrupted state and
deployment-only paths. The earlier CI measurement also omitted `web_config` and
did not measure branches.

The current measurement includes `api`, `views`, `main`, `assets`,
`install_assets` and `web_config`, with **branch coverage enabled** and no excluded
lines. It excludes templates, JavaScript, vendored libraries and dependency
internals. Browser behavior has a separate Node suite and responsive checks;
real Gunicorn worker processes have integration tests. Their child-process code
is not silently counted as parent-process Python coverage.

## Measured results

| Local Python 3.14 run | Statements | Missing statements | Statement coverage | Branch coverage | Combined coverage |
| --- | --- | --- | --- | --- | --- |
| Before this block, with configuration/branches measured | 1,753 | 51 | 97.09% | 92.98% | 96.08% |
| New 0.10 features, before the final audit tests | 1,853 | 59 | 96.82% | 92.88% | 95.87% |
| After the audit tests (345 web tests) | 1,853 | 32 | 98.27% | 95.25% | 97.54% |
| After the startup follow-up (347 web tests) | 1,862 | 30 | 98.39% | 95.25% | 97.63% |

The final branch denominator is 590, with 562 covered and 28 missing branches.
`coverage report` rounds the combined result to **98%**. Reports can vary when
code, Python or dependency behavior changes; the reproduction command below is
the current source of truth. CI enforces a **95% combined floor**, rather than
suppressing difficult paths to obtain 100%.

The added tests exercise blank account names, unsupported login passwords,
account removal after authentication, oversized/unsafe navigation groups,
stylesheet write failures and symlinks, invalid host configuration, nonregular
worker lock files, tampered migration history, redirected/corrupt asset
responses, staging-file cleanup, and read-only asset checks. Authentication,
worker coordination, site identity/stylesheets and configuration reach 100% of
measured statements/branches in this run. That does not replace their behavioral
contracts or establish coverage of every possible threat.

## Remaining gaps and support boundaries

The 30 residual statements are concentrated in these paths:

| Area | Remaining paths |
| --- | --- |
| Atomic storage | Existing-file permission races and a mode-preservation branch |
| Publication catalog | Symlink storage/legacy pages, an immutable-blob link race, legacy files changing during import, ambiguous routes and missing revision rows |
| Public index | Malformed/oversized extraction limits and a duplicate/empty signature branch |
| Publishing paths | Defensive path/name/type branches and oversized stored images |
| Migrations | Backup integrity failure, unsupported backend and malformed/incompatible history structures |
| Browser asset validation | Inconsistent manifest/version/license metadata |
| Program startup | Direct development `__main__` entry points |
| URL-prefix redirect | A return path inconsistent with the configured prefix |

These guards remain enabled. Several represent manual corruption or filesystem
races that normal validated writes cannot produce; others are deployment-only
entry points. The [deployment tests](vps-deployment.md) and
[server-state contract](server-state.md) remain necessary evidence alongside the
report. A 100% report would not make network filesystems, multiple hosts,
untrusted editors, independent notebook ownership or mixed-version rolling
upgrades supported. Those require their own implementation and acceptance gates.

The supported four-worker profile is now tested on fresh and legacy SQLite
state, concurrent owner claims/stale writes, reads through every worker, and
restart. TLS/DNS, operating-system permissions, free space, backup retention and
target-host provisioning still need operational verification. The
[0.11 ownership/access tasks](https://github.com/wispsy/pretty-notebook/issues/97)
remain separate product scope.

## Reproduce

From `apps/web`, with the declared application/test dependencies installed:

```bash
python -m coverage run --branch \
  --source=api,views,main,assets,install_assets,web_config -m pytest tests
python -m coverage report --show-missing --fail-under=95
python -m coverage json -o coverage.json
node --test tests/*.test.cjs
```

The suite starts temporary loopback-only Gunicorn workers using synthetic data.
Run it in an environment permitting local socket binds. Inspect the JSON's
statement, branch and combined percentages separately; a rounded headline loses
that distinction.
