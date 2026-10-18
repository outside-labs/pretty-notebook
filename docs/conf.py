"""Build the canonical Markdown documentation with strict local references."""

import sys
import tomllib
from pathlib import Path

from docutils import nodes
from sphinx.util.docutils import SphinxDirective

DOCS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DOCS_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
    release = tomllib.load(source)["project"]["version"]

project = "Pretty Notebook"
author = "Outside Labs"
copyright = "%Y, Outside Labs"
extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.doctest"]
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "roadmap.md"]
nitpicky = True
myst_heading_anchors = 5
myst_url_schemes = ["http", "https", "mailto", "file", "pnbp", "nano"]
autodoc_typehints = "none"
html_theme = "alabaster"
html_title = "Pretty Notebook documentation"
html_theme_options = {"description": "Markdown notebooks, library and CLI"}
html_sidebars = {"**": ["about.html", "navigation.html", "searchfield.html"]}


class CliHelp(SphinxDirective):
    """Render native interface help without invoking setup or program callbacks."""

    optional_arguments = 1
    final_argument_whitespace = True

    def run(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from expose_interface import UsageError
        from pretty_notebook.cli import app

        output = StringIO()
        try:
            with redirect_stdout(output):
                app.invoke([*(self.arguments[0].split() if self.arguments else []), "--help"])
        except UsageError as error:
            raise self.error(str(error)) from error
        help_text = output.getvalue()
        return [nodes.literal_block(help_text, help_text, language="console")]


def setup(app):
    app.add_directive("pnbp-cli-help", CliHelp)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
