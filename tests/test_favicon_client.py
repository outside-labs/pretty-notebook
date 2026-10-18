"""The favicon client sends checked, bounded requests and reports CLI errors."""

import pytest
import requests
from cli_runner import CliRunner

from pretty_notebook import Notebook
from pretty_notebook.cli import cli


@pytest.fixture
def notebook(tmp_path, monkeypatch):
    monkeypatch.setenv("PNBP_SETTINGS", "off")
    monkeypatch.setenv("API_TOKEN", "private-site-token")
    return Notebook(tmp_path, {"API_BASE": "https://example.com/notes"})


class Response:
    def raise_for_status(self):
        pass

    def json(self):
        return {"url": "/notes/static/favicon/version.png"}


def test_favicon_client_uses_configured_prefix_auth_timeout_and_png_file(notebook, tmp_path, monkeypatch):
    image = tmp_path / "site.PNG"
    image.write_bytes(b"png bytes")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("pnbp._publishing.requests.post", post)
    assert notebook.post_favicon(image).json()["url"] == "/notes/static/favicon/version.png"
    url, kwargs = calls[0]
    assert url == "https://example.com/notes/api/favicon"
    assert kwargs["headers"]["authorization"] == "Bearer private-site-token"
    assert kwargs["timeout"] == Notebook.REQUEST_TIMEOUT
    assert kwargs["files"] == {"file": ("site.PNG", b"png bytes", "image/png")}


@pytest.mark.parametrize("filename,content,message", [
    ("site.ico", b"ico", "PNG format"),
    ("site.png", b"x" * (1024 * 1024 + 1), "1 MiB limit"),
])
def test_invalid_client_file_never_sends_request(notebook, tmp_path, monkeypatch, filename, content, message):
    image = tmp_path / filename
    image.write_bytes(content)

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid file should not be uploaded")

    monkeypatch.setattr("pnbp._publishing.requests.post", unexpected)
    with pytest.raises(ValueError, match=message):
        notebook.post_favicon(image)


def test_client_propagates_rejected_upload(notebook, tmp_path, monkeypatch):
    image = tmp_path / "site.png"
    image.write_bytes(b"png")

    class Rejected(Response):
        def raise_for_status(self):
            raise requests.HTTPError("Rejected upload")

    monkeypatch.setattr("pnbp._publishing.requests.post", lambda *args, **kwargs: Rejected())
    with pytest.raises(requests.HTTPError):
        notebook.post_favicon(image)


@pytest.mark.parametrize("local", [False, True])
def test_favicon_cli_reports_new_url_and_optional_local_server(notebook, tmp_path, monkeypatch, local):
    image = tmp_path / "site.png"
    image.write_bytes(b"png")
    calls = []
    monkeypatch.setattr("pnbp.cli._open_notebook", lambda context: notebook)

    def post(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr("pnbp._publishing.requests.post", post)
    result = CliRunner().invoke(cli, ["favicon", str(image)] + (["--local"] if local else []))
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "/notes/static/favicon/version.png"
    assert calls == [("http://127.0.0.1:8000" if local else "https://example.com/notes") + "/api/favicon"]
    assert "private-site-token" not in result.output


def test_favicon_cli_reports_failure_without_credentials(notebook, tmp_path, monkeypatch):
    image = tmp_path / "site.png"
    image.write_bytes(b"png")
    monkeypatch.setattr("pnbp.cli._open_notebook", lambda context: notebook)

    def failed(*args, **kwargs):
        raise requests.ConnectionError("private-site-token")

    monkeypatch.setattr("pnbp._publishing.requests.post", failed)
    result = CliRunner().invoke(cli, ["favicon", str(image)])
    assert result.exit_code != 0
    assert "Could not update the site favicon" in result.output
    assert "private-site-token" not in result.output
