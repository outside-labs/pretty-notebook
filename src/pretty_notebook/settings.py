"""Typed notebook configuration and explicit, recoverable initialization."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit


class SettingsError(ValueError):
	"""Invalid or ambiguous configuration, reported without its values."""


_BOOL_KEYS = {"PUB_LNK_ONLY", "HIDE_COMMIT_TAG", "darkmode"}
_OPTIONAL_KEYS = {"IMG_PATH", "HTML_PATH", "VENV_PATH", "API_BASE"}
_MIXED_CASE_KEYS = {"darkmode", "hljs_light", "hljs_dark", "merm_light", "merm_dark"}
_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_CREDENTIAL_KEY = re.compile(r"(?:^|_)(?:token|secret|password|api_key)(?:_|$)", re.IGNORECASE)


def _config_key(name):
	return name if name in _MIXED_CASE_KEYS else name.upper()


def _contains_credentials(value):
	if isinstance(value, dict):
		return any(
			(isinstance(key, str) and bool(_CREDENTIAL_KEY.search(key)))
			or (key != "NAV_PAGES" and _contains_credentials(item))
			for key, item in value.items()
		)
	if isinstance(value, list):
		return any(_contains_credentials(item) for item in value)
	return False


def _validate_config(config):
	if _contains_credentials(config):
		raise SettingsError("Use api_token, the API_TOKEN environment variable, or .pnbp/secrets.json for credentials.")
	for key, value in config.items():
		if key == "APPEARANCE":
			from .appearance import validate_appearance
			try:
				validate_appearance(value)
			except ValueError as error:
				raise SettingsError(str(error)) from error
			continue
		elif key == "PUBLICATION_ROUTES":
			if not isinstance(value, dict) or any(not isinstance(k, str) or not k.endswith(".md") or k.startswith("/") or any(part in {"", ".", ".."} for part in k.split("/")) or "\\" in k or not isinstance(v, str) for k, v in value.items()):
				raise SettingsError("PUBLICATION_ROUTES must map relative Markdown source paths to routes.")
			continue
		if key in _BOOL_KEYS and type(value) is not bool:
			raise SettingsError(f"{key} must be a boolean.")
		if key in _OPTIONAL_KEYS and value is not None and not isinstance(value, str):
			raise SettingsError(f"{key} must be a string or null.")
		if key == "NAV_PAGES":
			if not isinstance(value, dict) or any(
				not isinstance(label, str) or not (
					isinstance(target, str) or (
						isinstance(target, list) and all(
							isinstance(item, dict) and all(
								isinstance(k, str) and isinstance(v, str)
								for k, v in item.items()
							) for item in target
						)
					)
				) for label, target in value.items()
			):
				raise SettingsError("NAV_PAGES must map labels to URLs or lists of URL mappings.")
		elif key in _SETTING_NAMES and key not in _BOOL_KEYS | _OPTIONAL_KEYS:
			if not isinstance(value, str):
				raise SettingsError(f"{key} must be a string.")
	if config.get("MARKDOWN_BACKEND", "typed") not in {"typed", "python-markdown"}:
		raise SettingsError("MARKDOWN_BACKEND must be typed or python-markdown.")
	if config.get("NOTE_NESTED", "flat") not in {"flat", "single", "recurs", "all"}:
		raise SettingsError("NOTE_NESTED must be flat, single, recurs, or all.")
	from pretty_notebook._internal.routes import SEGMENT, validate_prefix, validate_route
	mode = config.get("ROUTE_MODE", "flat")
	if mode not in {"flat", "hierarchical", "namespaced"}:
		raise SettingsError("ROUTE_MODE must be flat, hierarchical, or namespaced.")
	if not SEGMENT.fullmatch(config.get("SERVER_NOTEBOOK", "default")):
		raise SettingsError("SERVER_NOTEBOOK must be a lowercase notebook slug.")
	if config.get("SERVER_NOTEBOOK", "default") != "default" and (mode != "namespaced" or config.get("NOTEBOOK_SLUG") != config["SERVER_NOTEBOOK"]):
		raise SettingsError("Independent notebooks require matching SERVER_NOTEBOOK, NOTEBOOK_SLUG and namespaced routes.")
	if mode == "namespaced" and not SEGMENT.fullmatch(config.get("NOTEBOOK_SLUG", "")):
		raise SettingsError("Namespaced routes require a lowercase NOTEBOOK_SLUG.")
	try:
		validate_prefix(config.get("URL_PREFIX", ""))
		for route in config.get("PUBLICATION_ROUTES", {}).values():
			validate_route(route, allow_namespace=mode == "namespaced")
	except ValueError as error:
		raise SettingsError(str(error)) from error
	for key in ("COMMIT_TAG", "EXCLUDE_TAG"):
		if key in config and not re.fullmatch(r"#[^\s#]+", config[key]):
			raise SettingsError(f"{key} must be a nonempty #tag without whitespace.")
	if config.get("API_BASE"):
		try:
			url = urlsplit(config["API_BASE"])
			valid = url.scheme in {"http", "https"} and url.hostname and not (
				url.username or url.password or url.query or url.fragment
			)
			url.port
		except ValueError:
			valid = False
		if not valid:
			raise SettingsError("API_BASE must be an HTTP(S) URL without credentials, query, or fragment.")


@dataclass(frozen=True)
class NotebookSettings:
	"""Core settings; JSON uses the established uppercase keys (and theme keys)."""

	img_path: str | None = None
	html_path: str | None = None
	venv_path: str | None = None
	api_base: str | None = None
	markdown_backend: Literal["typed", "python-markdown"] = "typed"
	note_nested: Literal["flat", "single", "recurs", "all"] = "flat"
	route_mode: Literal["flat", "hierarchical", "namespaced"] = "flat"
	notebook_slug: str = ""
	server_notebook: str = "default"
	url_prefix: str = ""
	publication_routes: dict[str, str] = field(default_factory=dict)
	pub_lnk_only: bool = False
	commit_tag: str = "#public"
	exclude_tag: str = "#private"
	hide_commit_tag: bool = False
	title: str = ""
	nav_brand: str = ""
	nav_pages: dict[str, str | list[dict[str, str]]] = field(default_factory=dict)
	footer: str = ""
	appearance: dict = field(default_factory=dict)
	darkmode: bool = False
	hljs_light: str = "default"
	hljs_dark: str = "xt256"
	merm_light: str = "default"
	merm_dark: str = "dark"
	moc_tag: str = "#moc"
	cont_tag: str = "#cont"
	tasks_tag: str = "#tasks"
	tasks_note: str = "tasks"
	compl_tag: str = "#complete"
	compl_note: str = "_complete"
	sched_tag: str = "#schedule"
	terms_note: str = "TERMS"
	extras: dict = field(default_factory=dict, repr=False)

	def __post_init__(self):
		_validate_config(self.to_dict())

	def to_dict(self):
		"""Return an independent portable mapping, including extension settings."""
		return copy.deepcopy({
			**self.extras,
			**{_config_key(f.name): getattr(self, f.name) for f in fields(self) if f.name != "extras"},
		})

	@classmethod
	def from_dict(cls, config):
		if not isinstance(config, Mapping) or any(not isinstance(k, str) for k in config):
			raise SettingsError("Settings must be an object with string keys.")
		_validate_config(config)
		return cls(
			**{name: copy.deepcopy(config[key]) for key, name in _SETTING_NAMES.items() if key in config},
			extras=copy.deepcopy({k: v for k, v in config.items() if k not in _SETTING_NAMES}),
		)


_SETTING_NAMES = {_config_key(f.name): f.name for f in fields(NotebookSettings) if f.name != "extras"}


def _read_json(path):
	try:
		value = json.loads(path.read_text(encoding="utf-8"))
	except (ValueError, UnicodeError) as error:
		raise SettingsError(f"Invalid JSON in {path.name}.") from error
	if not isinstance(value, dict):
		raise SettingsError(f"{path.name} must contain a JSON object.")
	return value


def _portable_and_token(config, *, legacy=False):
	config = dict(config)
	token = config.pop("API_TOKEN", None) if legacy else None
	if token is not None and not isinstance(token, str):
		raise SettingsError("API_TOKEN must be a string.")
	NotebookSettings.from_dict(config)
	return config, token


def _profiles_path(environ):
	if environ.get("PNBP_PROFILES"):
		return Path(environ["PNBP_PROFILES"]).expanduser().resolve()
	base = Path(environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).expanduser()
	return base / "pnbp" / "profiles.json"


def _profiles(environ):
	path = _profiles_path(environ)
	if not path.exists():
		return path, {}
	data = _read_json(path)
	profiles = data.get("profiles")
	if data.get("version") != 1 or not isinstance(profiles, dict) or any(
		not isinstance(name, str) or not _PROFILE_NAME.fullmatch(name)
		or not isinstance(root, str) or not Path(root).is_absolute()
		for name, root in profiles.items()
	):
		raise SettingsError("Invalid profile registry; expected version 1 and named absolute paths.")
	return path, profiles


def resolve_notebook_path(path=None, *, profile=None, environ=None):
	environ = os.environ if environ is None else environ
	if path is not None and profile is not None:
		raise SettingsError("Choose an explicit notebook path or profile, not both.")
	if profile is None and path is None and not environ.get("NOTE_PATH"):
		profile = environ.get("PNBP_PROFILE")
	if profile is not None:
		_, profiles = _profiles(environ)
		if profile not in profiles:
			raise SettingsError("Unknown notebook profile; register it with pnbp init PATH --profile NAME.")
		path = profiles[profile]
	if path is None:
		path = environ.get("NOTE_PATH")
	if not path:
		raise ImportError("Set NOTE_PATH or pass a notebook path/profile to open a Notebook.")
	return Path(path).expanduser().resolve()


@dataclass(frozen=True)
class LoadedSettings:
	root: Path
	settings: NotebookSettings
	settings_file: str | Literal[False]
	config: dict = field(repr=False)
	api_token: str | None = field(repr=False)
	credentials_file: Path | None


def load_settings(path=None, settings=None, *, profile=None, settings_file=None, api_token=None, environ=None):
	"""Load without writes: explicit settings > environment > file > defaults."""
	environ = os.environ if environ is None else environ
	root = resolve_notebook_path(path, profile=profile, environ=environ)
	if not root.is_dir():
		raise FileNotFoundError(f"Notebook directory does not exist: {root}")
	selection = settings_file if settings_file is not None else environ.get("PNBP_SETTINGS")
	config, file_token = {}, None
	selected = None
	credentials = None if selection == "off" else root / ".pnbp" / "secrets.json"
	if selection != "off":
		if selection:
			selected = Path(selection).expanduser()
			if not selected.is_absolute():
				selected = root / selected
		else:
			modern, legacy = root / ".pnbp" / "settings.json", root / "pnbp_settings.json"
			if modern.exists() and legacy.exists():
				raise SettingsError("Both settings files exist; select one explicitly with settings_file or PNBP_SETTINGS.")
			selected = modern if modern.exists() else legacy if legacy.exists() else None
		if selected is not None:
			config, file_token = _portable_and_token(_read_json(selected), legacy=selected.name == "pnbp_settings.json")
		if credentials.exists():
			secret = _read_json(credentials)
			if set(secret) != {"API_TOKEN"} or not isinstance(secret["API_TOKEN"], str):
				raise SettingsError("secrets.json must contain only a string API_TOKEN.")
			file_token = secret["API_TOKEN"]
	for key in _SETTING_NAMES:
		if key in environ:
			value = environ[key]
			if key in _BOOL_KEYS:
				if value.lower() not in {"true", "false", "1", "0"}:
					raise SettingsError(f"{key} must be true, false, 1, or 0 in the environment.")
				value = value.lower() in {"true", "1"}
			elif key == "NAV_PAGES":
				try:
					value = json.loads(value)
				except ValueError as error:
					raise SettingsError("NAV_PAGES must be JSON in the environment.") from error
			config[key] = value
	if settings is not None:
		explicit = settings.to_dict() if isinstance(settings, NotebookSettings) else settings
		NotebookSettings.from_dict(explicit)
		config.update(explicit)
	config.setdefault("NOTE_NESTED", "flat")
	model = NotebookSettings.from_dict(config)
	token = api_token if api_token is not None else environ.get("API_TOKEN", file_token)
	if token is not None and not isinstance(token, str):
		raise SettingsError("API_TOKEN must be a string.")
	return LoadedSettings(root, model, str(selected) if selected else False, config, token, credentials)


def _json_bytes(value):
	return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _private_directory(path):
	if path.is_symlink():
		raise SettingsError("Refusing to write state through a symlinked directory.")
	path.mkdir(parents=True, exist_ok=True, mode=0o700)


def _write_exclusive(path, content):
	fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
	try:
		with os.fdopen(fd, "wb") as stream:
			stream.write(content)
			stream.flush()
			os.fsync(stream.fileno())
	except BaseException:
		path.unlink(missing_ok=True)
		raise


def save_api_token(path, token):
	"""Atomically replace private credentials, never the portable settings."""
	if not isinstance(token, str) or not token:
		raise SettingsError("Token refresh must return a nonempty string access_token.")
	_private_directory(path.parent)
	if path.is_symlink():
		raise SettingsError("Refusing to replace symlinked credentials.")
	fd, temporary = tempfile.mkstemp(prefix=".secrets-", suffix=".tmp", dir=path.parent)
	try:
		with os.fdopen(fd, "wb") as stream:
			stream.write(_json_bytes({"API_TOKEN": token}))
			stream.flush()
			os.fsync(stream.fileno())
		os.replace(temporary, path)
	finally:
		Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class InitializationPlan:
	root: Path
	action: str
	stores_credentials: bool
	profile: str | None

	def to_dict(self):
		return {
			"path": str(self.root), "action": self.action,
			"settings_file": str(self.root / ".pnbp" / "settings.json"),
			"stores_credentials": self.stores_credentials, "profile": self.profile,
			"legacy_backup": str(self.root / ".pnbp" / "legacy-settings.json") if self.action == "migrate" else None,
		}


def initialize_notebook(path, *, migrate=False, dry_run=False, profile=None, environ=None):
	"""Create settings explicitly; migration retains a private original backup."""
	environ = os.environ if environ is None else environ
	root = Path(path).expanduser().resolve()
	state = root / ".pnbp"
	modern, legacy = state / "settings.json", root / "pnbp_settings.json"
	secrets, backup = state / "secrets.json", state / "legacy-settings.json"
	if state.is_symlink():
		raise SettingsError("Refusing to initialize a symlinked .pnbp directory.")
	if modern.exists() and legacy.exists():
		raise SettingsError("Both settings files exist; resolve the ambiguity before initialization.")
	source = None
	if modern.exists():
		config, token = _portable_and_token(_read_json(modern))
		action = "unchanged"
	elif legacy.exists():
		if not migrate:
			raise SettingsError("Legacy settings exist; preview with pnbp init PATH --migrate --dry-run.")
		source = legacy.read_bytes()
		config, token = _portable_and_token(_read_json(legacy), legacy=True)
		action = "migrate"
		if backup.exists():
			raise SettingsError("A legacy backup already exists; resolve it before retrying migration.")
	else:
		if migrate:
			raise SettingsError("No legacy settings to migrate.")
		config, token = NotebookSettings(api_base="http://127.0.0.1:8000").to_dict(), None
		action = "initialize"
	if secrets.exists():
		secret = _read_json(secrets)
		if set(secret) != {"API_TOKEN"} or not isinstance(secret["API_TOKEN"], str):
			raise SettingsError("secrets.json must contain only a string API_TOKEN.")
		token = secret["API_TOKEN"]
	profile_path, profiles = _profiles(environ) if profile else (None, {})
	if profile is not None:
		if not isinstance(profile, str) or not _PROFILE_NAME.fullmatch(profile):
			raise SettingsError("Profile names must be 1-64 letters, digits, underscores, or hyphens.")
		if profile in profiles and Path(profiles[profile]).resolve() != root:
			raise SettingsError("Profile already names another notebook; choose a different name.")
	plan = InitializationPlan(root, action, bool(token), profile)
	if dry_run:
		return plan
	_private_directory(state)
	created = []
	try:
		if action != "unchanged":
			for destination, content in (
				([(secrets, _json_bytes({"API_TOKEN": token}))] if token is not None and not secrets.exists() else [])
				+ [(modern, _json_bytes(config))]
				+ ([(backup, source)] if source is not None else [])
			):
				_write_exclusive(destination, content)
				created.append(destination)
			verified, _ = _portable_and_token(_read_json(modern))
			if verified != config or (token is not None and _read_json(secrets) != {"API_TOKEN": token}):
				raise SettingsError("Initialization verification failed; original settings were retained.")
			if source is not None:
				if legacy.read_bytes() != source or backup.read_bytes() != source:
					raise SettingsError("Legacy settings changed during migration; original settings were retained.")
				legacy.unlink()
	except BaseException:
		for destination in reversed(created):
			destination.unlink(missing_ok=True)
		raise
	if profile is not None and profiles.get(profile) != str(root):
		profiles[profile] = str(root)
		_private_directory(profile_path.parent)
		fd, temporary = tempfile.mkstemp(prefix=".profiles-", suffix=".tmp", dir=profile_path.parent)
		try:
			with os.fdopen(fd, "wb") as stream:
				stream.write(_json_bytes({"version": 1, "profiles": profiles}))
			os.replace(temporary, profile_path)
		finally:
			Path(temporary).unlink(missing_ok=True)
	return plan
