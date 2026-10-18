from cli_runner import CliRunner

from pretty_notebook.cli import app, cli
from pretty_notebook.commands import collect


EXPECTED_COLLECTORS = (
    "_collect_all_stats",
    "_collect_all_notes",
    "_collect_all_urls",
    "_collect_all_public",
    "_collect_terms",
    "_collect_all_unlinked",
    "_collect_all_empty",
    "_collect_all_unheadered",
    "_collect_all_moc",
    "_collect_all_tags",
    "_collect_nonexistant_links",
    "_collect_code_blocked",
    "_collect_tasks_note",
    "_collect_public_graph",
    "_collect_all_graphs",
    "_collect_subl_projs",
    "_collect_git_diff",
)


def test_collect_all_has_explicit_leaf_registry():
    assert collect.COLLECTORS == EXPECTED_COLLECTORS
    assert "_collect_all" not in collect.COLLECTORS


def test_collect_all_dispatches_each_registered_leaf_once(monkeypatch):
    calls = []

    def first(nb=None):
        calls.append(("first", nb))

    def second(nb=None):
        calls.append(("second", nb))

    monkeypatch.setattr(collect, "_first", first, raising=False)
    monkeypatch.setattr(collect, "_second", second, raising=False)
    monkeypatch.setattr(collect, "COLLECTORS", ("_first", "_second"))
    notebook = object()

    collect._collect_all.__wrapped__(nb=notebook)

    assert calls == [("first", notebook), ("second", notebook)]


def test_intended_collection_commands_appear_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0, result.output
    expected = {
        "collect-code-blocked",
        "collect-tasks-note",
        "collect-public-graph",
        "collect-all-graphs",
        "collect-subl-projs",
    }
    assert expected <= ({p.name for p in app.programs} | set(app.children))
