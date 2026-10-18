import pytest

from pretty_notebook import Notebook
from pretty_notebook._internal.routes import validate_route
from pretty_notebook.settings import NotebookSettings, SettingsError


def notebook_at(root, sources, **settings):
	for name, text in sources.items():
		path = root / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(text, encoding="utf-8")
	return Notebook(root, settings={"NOTE_NESTED": "all", **settings})


@pytest.mark.parametrize("route", ["/a/../b", "/a//b", "/a/", "/a%2fb", "/a%252fb", "/A", "/研究", "/api/note", "/static/note", "/contact", "/n/books/note", "/a\\b", "//evil.example", "/a?b", "/a#b", "/a\x00b"])
def test_route_validation_rejects_hostile_or_reserved_paths(route):
	with pytest.raises(ValueError):
		validate_route(route)


def test_nested_route_preview_preserves_identity_and_reports_flat_collisions(tmp_path):
	nb = notebook_at(tmp_path, {"a/b.md": "#public", "a-b.md": "#public"}, ROUTE_MODE="hierarchical")
	plan = nb.publication_routes()
	assert [entry["route"] for entry in plan["routes"]] == ["/a-b", "/a/b"]
	assert plan["legacy_collisions"] == {"/a-b": ["a-b.md", "a/b.md"]}
	assert all(not entry["aliases"] for entry in plan["routes"])
	assert not (tmp_path / ".pnbp").exists()


def test_canonical_collision_stops_local_publication_before_writes(tmp_path):
	output = tmp_path / "output"
	output.mkdir()
	nb = notebook_at(tmp_path, {"A B.md": "#public", "A-B.md": "#public"}, HTML_PATH=str(output), ROUTE_MODE="hierarchical")
	with pytest.raises(ValueError, match="duplicate publication slug"):
		nb.write_commits_to_local_html()
	assert list(output.iterdir()) == []


def test_unicode_title_uses_explicit_route_override(tmp_path):
	nb = notebook_at(tmp_path, {"研究.md": "#public"}, ROUTE_MODE="hierarchical")
	with pytest.raises(ValueError, match="PUBLICATION_ROUTES"):
		nb.publication_routes()
	nb = Notebook(tmp_path, settings={"PUBLICATION_ROUTES": {"研究.md": "/research"}})
	entry = nb.publication_routes()["routes"][0]
	assert entry["route"] == "/research"
	assert entry["title"] == "研究"


def test_nested_wiki_links_headings_images_and_literals_use_prefix(tmp_path):
	nb = notebook_at(tmp_path, {
		"python/Function Definitions.md": "#public\n# Call Arguments\n",
		"index.md": "#public\n[[python/Function Definitions#Call Arguments|Call]] ![[photo.png]]\n\n`[[python/Function Definitions]]`\n",
	}, ROUTE_MODE="hierarchical", URL_PREFIX="/notes")
	rendered = nb.convert_to_html(nb.notes["index"])
	assert "href='/notes/python/function-definitions#call-arguments'>Call</a>" in rendered
	assert "src='/notes/static/imgs/photo.png'" in rendered
	assert "<code>[[python/Function Definitions]]</code>" in rendered


def test_namespaced_mode_remains_a_single_notebook_route_mapping(tmp_path):
	nb = notebook_at(tmp_path, {"python/example.md": "#public"}, ROUTE_MODE="namespaced", NOTEBOOK_SLUG="field-notes")
	assert nb.publication_routes()["routes"][0]["route"] == "/n/field-notes/python/example"
	with pytest.raises(SettingsError, match="NOTEBOOK_SLUG"):
		NotebookSettings(route_mode="namespaced")


def test_nested_local_export_is_contained(tmp_path):
	output = tmp_path / "output"
	output.mkdir()
	nb = notebook_at(tmp_path / "notes", {"python/example.md": "#public\nHello"}, ROUTE_MODE="hierarchical", HTML_PATH=str(output))
	nb.write_commits_to_local_html()
	assert "Hello" in (output / "python/example.html").read_text()
	outside = tmp_path / "outside"
	outside.mkdir()
	(output / "python/example.html").unlink()
	(output / "python").rmdir()
	(output / "python").symlink_to(outside, target_is_directory=True)
	with pytest.raises(ValueError, match="escapes HTML_PATH"):
		nb.write_commits_to_local_html()
	assert list(outside.iterdir()) == []


@pytest.mark.parametrize("settings", [{"URL_PREFIX": "/notes/"}, {"PUBLICATION_ROUTES": {"../note.md": "/note"}}, {"PUBLICATION_ROUTES": {"note.md": "/api/note"}}, {"ROUTE_MODE": "unknown"}])
def test_invalid_route_settings_fail_when_loading(settings):
	with pytest.raises(SettingsError):
		NotebookSettings.from_dict(settings)


def test_remote_collision_preview_stops_before_uploads_or_prune(tmp_path, monkeypatch):
	from types import SimpleNamespace
	nb = notebook_at(tmp_path, {"python/example.md": "#public"}, ROUTE_MODE="hierarchical", API_BASE="https://notebook.example")
	requests = []
	def preview(url, **kwargs):
		requests.append((url, kwargs))
		return SimpleNamespace(json=lambda: {"valid": False, "conflicts": [{"name": "python/example"}]}, raise_for_status=lambda: None)
	def unexpected(*args, **kwargs):
		raise AssertionError("No uploads or inventory/prune requests after a route conflict")
	monkeypatch.setattr("pnbp._publishing.requests.post", preview)
	monkeypatch.setattr("pnbp._publishing.requests.get", unexpected)
	monkeypatch.setattr("pnbp._publishing.requests.delete", unexpected)
	with pytest.raises(ValueError, match="Remote route preview"):
		nb.post_commits_to_web_api(prune=True, mode="legacy")
	assert len(requests) == 1 and requests[0][0].endswith("/api/routes/preview")
	assert requests[0][1]["json"] == [{"name": "python/example", "aliases": ("/python-example",)}]


def test_independent_notebook_client_scopes_routes_headers_and_images(tmp_path):
    nb = notebook_at(tmp_path, {'same.md': '#public\n![[photo.png]]'}, ROUTE_MODE='namespaced', NOTEBOOK_SLUG='alpha', SERVER_NOTEBOOK='alpha')
    entry = nb.publication_routes()['routes'][0]
    assert entry['route'] == '/n/alpha/same' and not entry['aliases']
    assert nb.get_headers()['X-PNBP-Notebook'] == 'alpha'
    assert "src='/static/imgs/n/alpha/photo.png'" in nb.convert_to_html(nb.notes['same'])
    with pytest.raises(SettingsError, match='matching SERVER_NOTEBOOK'):
        NotebookSettings(server_notebook='alpha')
    with pytest.raises(SettingsError, match='SERVER_NOTEBOOK'):
        NotebookSettings(server_notebook='../escape')
