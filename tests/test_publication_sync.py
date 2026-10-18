import os
import time

import pytest
import requests
from cli_runner import CliRunner

from pretty_notebook import Notebook
from pretty_notebook.cli import cli
from pretty_notebook.commands.correct import _touch_all_public
from pretty_notebook.helpers import _convert_datetime


class FakeResponse:
	def __init__(self, payload=None, status_code=200):
		self.payload = [] if payload is None else payload
		self.status_code = status_code

	def json(self):
		return self.payload

	def raise_for_status(self):
		if self.status_code >= 400:
			raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

	def __str__(self):
		return f"<FakeResponse [{self.status_code}]>"


@pytest.fixture
def publication_root(monkeypatch, tmp_path):
	note_path = tmp_path / "notes"
	image_path = tmp_path / "images"
	html_path = tmp_path / "html"
	for path in (note_path, image_path, html_path):
		path.mkdir()

	monkeypatch.setenv("NOTE_PATH", str(note_path))
	monkeypatch.setenv("IMG_PATH", str(image_path))
	monkeypatch.setenv("HTML_PATH", str(html_path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	return note_path, image_path


def remote_inventory(publications=None, images=None, calls=None):
	publications = [] if publications is None else publications
	images = [] if images is None else images

	def fake_get(url, **kwargs):
		if calls is not None:
			calls.append(("get", url, kwargs))
		if url.endswith("/api/publishing/capabilities"):
			return FakeResponse(status_code=404)
		if url.endswith("/api/publishments"):
			return FakeResponse(publications)
		if url.endswith("/api/images"):
			return FakeResponse(images)
		raise AssertionError(f"Unexpected GET: {url}")

	return fake_get


def test_failed_page_upload_aborts_pruning(
	publication_root,
	monkeypatch,
) -> None:
	note_path, _ = publication_root
	(note_path / "public.md").write_text("#public\n", encoding="utf-8")
	notebook = Notebook()
	notebook.API_BASE = "https://publish.example"
	calls = []
	deleted = []
	publications = [
		{"pub_name": "public.html", "mod_date": "2000-01-01T00:00:00"},
		{"pub_name": "stale.html", "mod_date": "2000-01-01T00:00:00"},
	]

	monkeypatch.setattr(
		"pnbp.models.notebook.requests.get",
		remote_inventory(publications=publications, calls=calls),
	)

	def failed_post(url, **kwargs):
		calls.append(("post", url, kwargs))
		return FakeResponse(status_code=500)

	def record_delete(url, **kwargs):
		deleted.append(url)
		return FakeResponse({"pub_name": url.rsplit("/", 1)[-1]})

	monkeypatch.setattr("pnbp.models.notebook.requests.post", failed_post)
	monkeypatch.setattr("pnbp.models.notebook.requests.delete", record_delete)

	with pytest.raises(requests.HTTPError, match="500"):
		notebook.post_commits_to_web_api(prune=True)

	assert deleted == []
	assert calls
	assert all(
		kwargs["timeout"] == Notebook.REQUEST_TIMEOUT
		for _, _, kwargs in calls
	)


def test_failed_image_upload_aborts_pruning(
	publication_root,
	monkeypatch,
) -> None:
	note_path, image_path = publication_root
	(note_path / "public.md").write_text(
		"#public\n![[photo.png]]\n",
		encoding="utf-8",
	)
	(image_path / "photo.png").write_bytes(b"png")
	notebook = Notebook()
	notebook.API_BASE = "https://publish.example"
	deleted = []

	monkeypatch.setattr(
		"pnbp.models.notebook.requests.get",
		remote_inventory(
			publications=[
				{"pub_name": "stale.html", "mod_date": "2000-01-01T00:00:00"},
			],
		),
	)

	def post(url, **kwargs):
		status_code = 500 if url.endswith("/api/image") else 201
		return FakeResponse(status_code=status_code)

	def record_delete(url, **kwargs):
		deleted.append(url)
		return FakeResponse({"pub_name": url.rsplit("/", 1)[-1]})

	monkeypatch.setattr("pnbp.models.notebook.requests.post", post)
	monkeypatch.setattr("pnbp.models.notebook.requests.delete", record_delete)

	with pytest.raises(requests.HTTPError, match="500"):
		notebook.post_commits_to_web_api(prune=True)

	assert deleted == []


def test_empty_notebook_does_not_prune_by_default(
	publication_root,
	monkeypatch,
) -> None:
	note_path, _ = publication_root
	(note_path / "private.md").write_text("Not public.\n", encoding="utf-8")
	notebook = Notebook()
	notebook.API_BASE = "https://publish.example"
	deleted = []

	monkeypatch.setattr(
		"pnbp.models.notebook.requests.get",
		remote_inventory(
			publications=[
				{"pub_name": "existing.html", "mod_date": "2000-01-01T00:00:00"},
			],
		),
	)
	monkeypatch.setattr(
		"pnbp.models.notebook.requests.delete",
		lambda url, **kwargs: deleted.append(url),
	)

	notebook.post_commits_to_web_api()

	assert deleted == []


def test_explicit_prune_deletes_unlisted_pages(
	publication_root,
	monkeypatch,
) -> None:
	note_path, _ = publication_root
	(note_path / "private.md").write_text("Not public.\n", encoding="utf-8")
	notebook = Notebook()
	notebook.API_BASE = "https://publish.example"
	deleted = []

	monkeypatch.setattr(
		"pnbp.models.notebook.requests.get",
		remote_inventory(
			publications=[
				{"pub_name": "existing.html", "mod_date": "2000-01-01T00:00:00"},
			],
		),
	)

	def record_delete(url, **kwargs):
		deleted.append(url)
		return FakeResponse({"pub_name": "existing.html"})

	monkeypatch.setattr("pnbp.models.notebook.requests.delete", record_delete)

	notebook.post_commits_to_web_api(prune=True)

	assert deleted == [
		"https://publish.example/api/publishment/existing.html",
	]


def test_failed_prune_response_is_reported(
	publication_root,
	monkeypatch,
) -> None:
	note_path, _ = publication_root
	(note_path / "private.md").write_text("Not public.\n", encoding="utf-8")
	notebook = Notebook()
	notebook.API_BASE = "https://publish.example"

	monkeypatch.setattr(
		"pnbp.models.notebook.requests.get",
		remote_inventory(
			publications=[
				{"pub_name": "existing.html", "mod_date": "2000-01-01T00:00:00"},
			],
		),
	)
	monkeypatch.setattr(
		"pnbp.models.notebook.requests.delete",
		lambda *args, **kwargs: FakeResponse(status_code=500),
	)

	with pytest.raises(requests.HTTPError, match="500"):
		notebook.post_commits_to_web_api(prune=True)


def test_refresh_images_is_explicit_and_independent_of_page_freshness(
	publication_root,
	monkeypatch,
) -> None:
	note_path, image_path = publication_root
	(note_path / "public.md").write_text(
		"#public\n![[photo.png]]\n",
		encoding="utf-8",
	)
	(image_path / "photo.png").write_bytes(b"png")
	notebook = Notebook()
	notebook.API_BASE = "https://publish.example"
	posts = []

	monkeypatch.setattr(
		"pnbp.models.notebook.requests.get",
		remote_inventory(
			publications=[
				{"pub_name": "public.html", "mod_date": "2999-01-01T00:00:00"},
			],
			images=[
				{"img_name": "photo.png", "mod_date": "2999-01-01T00:00:00"},
			],
		),
	)

	def record_post(url, **kwargs):
		posts.append((url, kwargs))
		return FakeResponse(status_code=201)

	monkeypatch.setattr("pnbp.models.notebook.requests.post", record_post)

	notebook.post_commits_to_web_api(refresh_images=True)

	assert [url for url, _ in posts] == ["https://publish.example/api/image"]
	assert posts[0][1]["timeout"] == Notebook.REQUEST_TIMEOUT


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset unavailable")
def test_mtime_conversion_is_utc_and_timezone_independent() -> None:
	epoch = 1_700_000_000
	previous_tz = os.environ.get("TZ")

	try:
		os.environ["TZ"] = "UTC"
		time.tzset()
		utc_value = _convert_datetime(epoch, as_mtime=True)

		os.environ["TZ"] = "America/Los_Angeles"
		time.tzset()
		pacific_value = _convert_datetime(epoch, as_mtime=True)
	finally:
		if previous_tz is None:
			os.environ.pop("TZ", None)
		else:
			os.environ["TZ"] = previous_tz
		time.tzset()

	assert utc_value == pacific_value
	assert utc_value.utcoffset().total_seconds() == 0
	assert _convert_datetime("2023-11-14T22:13:20+00:00") == utc_value


def test_touch_all_public_touches_real_note_paths(publication_root) -> None:
	note_path, _ = publication_root
	public_path = note_path / "alpha.md"
	uppercase_path = note_path / "Upper.MD"
	excluded_path = note_path / "excluded.md"
	public_path.write_text("#public\n", encoding="utf-8")
	uppercase_path.write_text("#public\n", encoding="utf-8")
	excluded_path.write_text("#public #private\n", encoding="utf-8")
	os.utime(public_path, (1, 1))
	os.utime(uppercase_path, (1, 1))
	os.utime(excluded_path, (1, 1))
	notebook = Notebook()

	_touch_all_public(nb=notebook)

	assert public_path.stat().st_mtime > 1
	assert uppercase_path.stat().st_mtime > 1
	assert excluded_path.stat().st_mtime == 1
	assert not (note_path / "alphamd").exists()
	assert "Upper.md" not in {path.name for path in note_path.iterdir()}


def test_commit_remote_reports_http_failure_with_nonzero_status(
	publication_root,
	monkeypatch,
) -> None:
	def fail(*args, **kwargs):
		raise requests.HTTPError("HTTP 500")

	monkeypatch.setattr(Notebook, "post_commits_to_web_api", fail)
	result = CliRunner().invoke(cli, ["commit-remote"])

	assert result.exit_code != 0
	assert "Publication failed" in result.output
