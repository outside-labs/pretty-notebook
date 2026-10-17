"""Measure the supported Markdown workloads in bounded, isolated processes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from pretty_notebook import Notebook
from pretty_notebook.markdown import ParseLimitError, render_notebook

SAMPLES = {
    'ordinary-100k': 'ordinary text ' * 8000,
    'links-2000': '[label](https://example.com) ' * 2000,
    'code-spans-5000': 'a `literal` ' * 5000,
    'emphasis-5000': '*word* ' * 5000,
    'unclosed-brackets-40k': '[[' * 20000,
    'unclosed-html-attributes': 'x <a' + ' a=abc' * 5000,
    'unbalanced-destination': '[a](' + '(' * 50000 + ')' * 50000,
    'container-limit': '> ' * 70 + 'text',
    'character-limit': 'x' * 2_000_001,
}
EXPECTED_LIMITS = {'container-limit': 'nesting-limit', 'character-limit': 'character-limit'}


def measure(name, legacy=False):
    if name == 'repository-guides':
        root = Path(__file__).resolve().parents[1]
        source = '\n\n'.join((root / 'docs' / file).read_text() for file in ('editing.md', 'links.md', 'code-tools.md'))
    else:
        source = SAMPLES[name]
    start = perf_counter()
    try:
        result = render_notebook(source)
        assert name not in EXPECTED_LIMITS, 'Expected a configured parser limit'
        outcome, output_size = 'rendered', len(result.html)
    except ParseLimitError as error:
        assert error.diagnostic.code == EXPECTED_LIMITS.get(name), error.diagnostic
        outcome, output_size = error.diagnostic.code, 0
    report = {'case': name, 'characters': len(source), 'outcome': outcome,
              'typed_seconds': round(perf_counter() - start, 6), 'html_characters': output_size}
    if legacy and name == 'repository-guides':
        from pretty_notebook._internal.legacy_rendering import render_note
        with TemporaryDirectory() as temporary:
            Path(temporary, 'guide.md').write_text(source)
            notebook = Notebook(temporary)
            start = perf_counter()
            render_note(notebook, notebook.notes['guide'])
            report['legacy_seconds'] = round(perf_counter() - start, 6)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=[*SAMPLES, 'repository-guides'])
    parser.add_argument('--legacy', action='store_true', help='Also measure the optional legacy renderer on repository guides.')
    args = parser.parse_args()
    if args.case:
        print(json.dumps(measure(args.case, args.legacy)))
        return
    reports = []
    for name in [*SAMPLES, 'repository-guides']:
        command = [sys.executable, str(Path(__file__).resolve()), '--case', name]
        if args.legacy:
            command.append('--legacy')
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
        reports.append(json.loads(result.stdout))
    print(json.dumps({'timeout_seconds_per_case': 10, 'cases': reports}, indent=2))


if __name__ == '__main__':
    main()
