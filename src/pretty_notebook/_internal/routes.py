"""Publication routes are independent of source paths and persistent identities."""

import re
from urllib.parse import quote
from collections import defaultdict
from dataclasses import asdict, dataclass

SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
RESERVED = {"api", "static", "assets", "forms", "theme", "appearance", "contact", "healthz", "docs", "redoc", "openapi", "favicon", "n"}


def validate_route(route, *, allow_namespace=False, reserved=True):
	"""Accept canonical decoded paths only; never normalize hostile encodings."""
	if not isinstance(route, str) or not route.startswith("/") or len(route) > 500:
		raise ValueError("A publication route must be an absolute path of at most 500 characters.")
	parts = route[1:].split("/")
	if any(not SEGMENT.fullmatch(part) for part in parts):
		raise ValueError("Invalid publication route segment; use lowercase ASCII letters, digits, and hyphens.")
	if reserved and parts[0] in RESERVED:
		if not (allow_namespace and parts[0] == "n" and len(parts) >= 3):
			raise ValueError("Publication route uses a reserved prefix.")
	return route


def validate_prefix(prefix):
	if prefix == "":
		return prefix
	return validate_route(prefix, reserved=False)


def public_url(prefix, path):
	return validate_prefix(prefix) + path


def public_image_url(config, name):
	slug = config.get("SERVER_NOTEBOOK", "default")
	return public_url(config.get("URL_PREFIX", ""), "/static/imgs/" + ("n/" + slug + "/" if slug != "default" else "") + quote(name, safe=""))


def _slug(value):
	value = re.sub(r"[^a-zA-Z0-9\s_-]+", "", value)
	value = re.sub(r"[\s_-]+", "-", value.lower())
	return value.strip("-")


@dataclass(frozen=True)
class PublicationRoute:
	source_path: str
	note_id: str | None
	title: str
	route: str
	aliases: tuple[str, ...] = ()


def route_for(note, config):
	path = note.source_path or note.name + ".md"
	mode = config.get("ROUTE_MODE", "flat")
	override = config.get("PUBLICATION_ROUTES", {}).get(path)
	if override is not None:
		route = override
	else:
		parts = [note.slugname] if mode == "flat" else [_slug(part) for part in path[:-3].split("/")]
		if any(not part for part in parts):
			raise ValueError(f"Note {note.name!r} has an empty publication slug; set PUBLICATION_ROUTES for its source path.")
		route = "/" + "/".join(parts)
		if mode == "namespaced":
			route = "/n/" + config["NOTEBOOK_SLUG"] + route
	validate_route(route, allow_namespace=mode == "namespaced")
	identity = getattr(note, "_identity_record", None)
	return PublicationRoute(path, getattr(identity, "id", None), getattr(identity, "title", None) or note.name, route)


def plan_routes(notebook, notes):
	"""Preview canonical routes and omit ambiguous legacy aliases without writes."""
	routes = [route_for(note, notebook.config) for note in notes]
	owners, legacy = {}, defaultdict(list)
	for note, entry in zip(notes, routes):
		if entry.route in owners:
			raise ValueError(f"Notes {owners[entry.route]!r} and {note.name!r} share duplicate publication slug/route {entry.route!r}.")
		owners[entry.route] = note.name
		if note.slugname and SEGMENT.fullmatch(note.slugname) and note.slugname not in RESERVED:
			legacy["/" + note.slugname].append(entry.source_path)
	ambiguous = {alias: paths for alias, paths in legacy.items() if len(paths) > 1 or (alias in owners and any(entry.route != alias for entry in routes if entry.source_path in paths))}
	result = []
	for entry in routes:
		aliases = tuple(alias for alias, paths in legacy.items() if notebook.config.get("SERVER_NOTEBOOK", "default") == "default" and paths == [entry.source_path] and alias != entry.route and alias not in ambiguous)
		result.append(PublicationRoute(entry.source_path, entry.note_id, entry.title, entry.route, aliases))
	return {"routes": [asdict(entry) for entry in result], "legacy_collisions": ambiguous}
