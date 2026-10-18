import json
from dataclasses import replace

import pytest
from cli_runner import CliRunner

from pretty_notebook import Notebook, SearchHit
from pretty_notebook.cli import cli


@pytest.fixture
def notebook(monkeypatch, tmp_path):
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	monkeypatch.delenv("NOTE_NESTED", raising=False)
	(tmp_path / "b.md").write_text("Saved [CAFÉ] #food #work\n", encoding="utf-8")
	(tmp_path / "a.md").write_text("Saved café #food\n", encoding="utf-8")
	return Notebook(tmp_path)


def test_literal_unicode_search_is_quiet_and_preserves_pending_edits(notebook, capsys):
	note = notebook.notes["b"]
	note.md_out = "Pending [café] #food #work"
	hits = notebook.search("[CAFÉ]")
	assert hits == [SearchHit("b", 8, 14, note.current_md)]
	assert note.current_md[hits[0].start:hits[0].end] == "[café]"
	assert note.md == "Saved [CAFÉ] #food #work\n"
	assert note.md_out == "Pending [café] #food #work"
	assert capsys.readouterr().out == ""


def test_fields_select_metadata_title_source_name_and_current_tags(notebook):
	notebook.initialize_identities()
	notebook.notes["b"]._identity_record = replace(notebook.notes["b"].identity, title="Café guide")
	assert notebook.search("guide", field="title")[0].field == "title"
	assert notebook.search("guide", field="title")[0].excerpt == "Café guide"
	assert notebook.search("guide") == []
	assert notebook.search("a", field="title") == [SearchHit("a", 0, 1, "a", "title"), SearchHit("b", 1, 2, "Café guide", "title")]
	tag_hit = notebook.search("WORK", field="tag")[0]
	assert tag_hit == SearchHit("b", 7, 11, "#food #work", "tag")
	notebook.notes["b"].md_out = "#new"
	assert notebook.search("work", field="tag") == []
	assert notebook.search("new", field="tag")[0].name == "b"


def test_any_returns_one_hit_per_note_with_deterministic_field_priority(notebook):
	notebook.notes["a"].md_out = "#work"
	hits = notebook.search("a", field="any")
	assert [hit.name for hit in hits] == ["a", "b"]
	assert [hit.field for hit in hits] == ["title", "content"]
	assert [hit.name for hit in notebook.search("food", field="any")] == ["b"]


def test_exact_tag_filters_are_anded_before_pagination_and_use_current_content(notebook):
	assert [hit.name for hit in notebook.search("café", tags=("FOOD", "#WORK"))] == ["b"]
	assert notebook.search("café", tags="foo") == []
	notebook.notes["a"].md_out = "Pending café #work #food"
	assert [hit.name for hit in notebook.search("café", tags=("food", "work"), offset=1)] == ["b"]
	notebook.notes["b"].md_out = "Pending café #food\n```\n#work\n```"
	assert [hit.name for hit in notebook.search("café", tags="work")] == ["a"]


def test_pagination_order_and_excerpt_bounds_are_stable(notebook):
	notebook.notes["a"].md_out = "x" * 180 + "café" + "y" * 180
	first = notebook.search("café", limit=1)
	second = notebook.search("café", limit=1, offset=1)
	assert [hit.name for hit in first + second] == ["a", "b"]
	assert first == notebook.search("café", limit=1)
	assert first[0].start == 180 and first[0].end == 184
	assert len(first[0].excerpt) == 160 and "café" in first[0].excerpt
	assert notebook.search("café", offset=200) == []


def test_explicit_local_regex_and_legacy_find_preserve_their_source_contracts(notebook, capsys):
	notebook.notes["a"].md_out = "Pending changed"
	assert [hit.name for hit in notebook.search(r"c.fé", regex=True)] == ["b"]
	assert notebook.search(r"c.fé") == []
	assert notebook.find("Saved") == list(notebook.notes.values())
	assert "regex: Saved" in capsys.readouterr().out
	with pytest.raises(ValueError, match=r"Invalid search regular expression:.*unterminated"):
		notebook.search("[", regex=True)


@pytest.mark.parametrize("query,options", [
	("", {}), ("x" * 513, {}), (None, {}), (1, {}),
	("x", {"field": "unknown"}), ("x", {"field": []}),
	("x", {"regex": 1}), ("x", {"regex": "yes"}),
	("x", {"limit": 0}), ("x", {"limit": 201}), ("x", {"limit": True}),
	("x", {"offset": -1}), ("x", {"offset": True}), ("x", {"offset": 1.5}),
	("x", {"tags": None}), ("x", {"tags": True}), ("x", {"tags": (1,)}),
	("x", {"tags": ("food",) * 17}), ("x", {"tags": "#"}),
	("x", {"tags": "f" * 65}), ("x", {"tags": "two words"}),
	("x", {"tags": "##work"}), ("x", {"tags": "café"}),
])
def test_invalid_search_options_fail_clearly(notebook, query, options):
	with pytest.raises(ValueError, match="Search"):
		notebook.search(query, **options)


def test_boundary_query_and_zero_width_regex_are_supported(notebook):
	notebook.notes["a"].md_out = "x" * 512
	assert notebook.search("x" * 512)[0].end == 512
	notebook.notes["a"].md_out = ""
	assert notebook.search("^", regex=True)[0].end == 0
	assert notebook.search("^", regex=True, limit=200)[0].name == "a"


def test_cli_field_tag_filters_json_and_invalid_regex(notebook):
	runner = CliRunner()
	base = ["--notebook", notebook.NOTE_PATH, "search"]
	result = runner.invoke(cli, [*base, "CAFÉ", "--field", "content", "--tag", "food", "--tag", "work", "--json"])
	assert result.exit_code == 0, result.output
	payload = json.loads(result.output)
	assert [hit["name"] for hit in payload["hits"]] == ["b"]
	assert payload["hits"][0]["field"] == "content"
	assert payload["limit"] == 50 and payload["offset"] == 0
	titles = runner.invoke(cli, [*base, "b", "--field", "title"])
	assert titles.exit_code == 0 and titles.output == "b: b\n"
	error = runner.invoke(cli, [*base, "[", "--regex"])
	assert error.exit_code == 1 and "Invalid search regular expression" in error.output
	assert "Traceback" not in error.output
