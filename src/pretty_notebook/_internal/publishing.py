"""The legacy HTTP publishing client and local HTML export."""

import getpass
import re
from pathlib import Path
import requests
from pretty_notebook.helpers import _convert_datetime
from pretty_notebook.models.components import Link
from pretty_notebook.settings import save_api_token
from pretty_notebook._internal import routes as _routes


def _remote_route_preview(notebook):
	if notebook.config.get("ROUTE_MODE", "flat") == "flat" and not notebook.config.get("PUBLICATION_ROUTES"):
		return None
	claims = [{"name": entry["route"][1:], "aliases": entry["aliases"]} for entry in notebook.publication_routes()["routes"]]
	if len(claims) > 200:
		raise ValueError("Route migration preview is limited to 200 publications; split the migration before publishing.")
	response = notebook._api_request(requests.post, "/api/routes/preview", json=claims, headers=notebook.get_headers())
	preview = response.json()
	if not isinstance(preview, dict) or preview.get("valid") is not True:
		raise ValueError("Remote route preview found collisions; inspect /api/routes/preview before publishing.")
	return preview


def publication_plan(notebook, *, prune=False, refresh_images=False, limit=200, mode="auto", accept_remote=False):
	from pretty_notebook._internal import publication_plan as _publication_plan
	if type(limit) is not int or not 1 <= limit <= 200:
		raise ValueError("Publication plan limit must be 1-200.")
	plan = _publication_plan.prepare(notebook, mode=mode, prune=prune, refresh_images=refresh_images, accept_remote=accept_remote)
	if plan is not None:
		return plan.preview(limit)
	return _legacy_publication_plan(notebook, prune=prune, refresh_images=refresh_images, limit=limit)


def _legacy_publication_plan(notebook, *, prune=False, refresh_images=False, limit=200):
	if type(limit) is not int or not 1 <= limit <= 200:
		raise ValueError("Publication plan limit must be 1-200.")
	notebook._require_clean_notes("preview remote commits")
	notebook.open_md()
	notes, images = notebook._publication_preflight(include_images=True)
	route_preview = _remote_route_preview(notebook)
	pages_remote = notebook.get_pub_commits()
	images_remote = notebook.get_img_commits()
	pages = []
	local_names = set()
	for note in notes:
		name = _routes.route_for(note, notebook.config).route[1:] + ".html"
		local_names.add(name)
		action = "create" if name not in pages_remote else "update" if pages_remote[name] < note.mtime else "unchanged"
		pages.append({"name": name, "note": note.name, "action": action})
	for name in sorted(set(pages_remote) - local_names):
		pages.append({"name": name, "action": "delete" if prune else "preserve"})
	image_actions = [
		{"name": name, "action": "create" if name not in images_remote else "update" if refresh_images else "unchanged"}
		for name in sorted(images)
	]
	return {
		"mode": "legacy-0.9", "dry_run": True, "prune": prune,
		"pages": pages[:limit], "images": image_actions[:limit],
		"page_count": len(pages), "image_count": len(image_actions),
		"truncated": len(pages) > limit or len(image_actions) > limit,
		"routes": notebook.publication_routes(), "remote_routes": route_preview,
	}


def write_local_html(notebook):
	""" a local debugging mtd
		-> notebook.HTML_PATH/.html ...
	"""
	notebook._require_clean_notes("publish local HTML")
	notebook.open_md()
	notes, _ = notebook._publication_preflight()

	print(f'\nlocal commit: {notebook.HTML_PATH}')
	for n in notes:
		html = notebook.convert_to_html(note=n)
		root = Path(notebook.HTML_PATH).resolve()
		target = root / (_routes.route_for(n, notebook.config).route[1:] + ".html")
		if not target.resolve().is_relative_to(root):
			raise ValueError("Publication path escapes HTML_PATH.")
		target.parent.mkdir(parents=True, exist_ok=True)
		with target.open('w', encoding='utf-8') as output_file:
			output_file.write(html)

		print(f'\t{n.name} ---> {notebook.HTML_PATH}')


def headers(notebook):
	""" the request headers """
	headers = {'accept': 'application/json'}
	if notebook.config.get('SERVER_NOTEBOOK', 'default') != 'default':
		headers['X-PNBP-Notebook'] = notebook.config['SERVER_NOTEBOOK']
	if notebook.API_TOKEN:
		headers['authorization'] = f'Bearer {notebook.API_TOKEN}'
	return headers


def request(notebook, method, path, **kwargs):
	"""Send one checked API request with a finite connection/read timeout."""
	kwargs.setdefault('timeout', notebook.REQUEST_TIMEOUT)
	response = method(f'{notebook.API_BASE.rstrip("/")}{path}', **kwargs)
	response.raise_for_status()
	return response


def refresh_token(notebook):
	""" request method to replace the authenticated user's bearer token
	"""
	u = input('Username: ')
	p = getpass.getpass()
	h = {
		'accept': 'application/json',
		'Content-Type': 'application/x-www-form-urlencoded',
	}
	r = requests.post(
		f'{notebook.API_BASE}/api/token',
		data={'username': u, 'password': p},
		headers=h,
		timeout=notebook.REQUEST_TIMEOUT,
	)
	print(r)

	try:
		payload = r.json()
	except ValueError:
		payload = None

	if isinstance(payload, dict):
		redacted = {
			key: ('<redacted>' if 'token' in key.lower() else value)
			for key, value in payload.items()
		}
		print(redacted)
	elif payload is not None:
		print('<response payload omitted>')

	if r.status_code == 200:
		if not isinstance(payload, dict) or 'access_token' not in payload:
			raise ValueError("Token refresh response did not include access_token.")

		token = payload['access_token']
		if not isinstance(token, str) or not token:
			raise ValueError("Token refresh response did not include a nonempty string access_token.")
		if notebook.credentials_file is not None:
			save_api_token(notebook.credentials_file, token)
		notebook.API_TOKEN = token


def get_authed_user(notebook):
	""" request method to get the authenticated user's username
	"""
	h = notebook.get_headers()
	r = notebook._api_request(requests.get, '/api/users/me', headers=h)
	print(r)
	print(r.json())
	return r


def get_api_home(notebook):
	""" request method to /api/ (testing auth)
	"""
	h = notebook.get_headers()
	r = notebook._api_request(requests.get, '/api', headers=h)
	print(r.text)
	print(r.json())
	return r


def get_pub_commits(notebook)->dict:
	""" (internal use)
		request method for a remote filepath check
		for the purpose of making smarter POST updates
		against current publishments.
	"""
	h = notebook.get_headers()
	r = notebook._api_request(requests.get, '/api/publishments', headers=h)
	pub_data = r.json()

	nameMtime = {}
	for pub in pub_data:
		pub['mod_date'] = _convert_datetime(pub['mod_date'])
		nameMtime.update({pub['pub_name']: pub['mod_date']})

	return nameMtime


def get_img_commits(notebook)->dict:
	""" (internal use)
		request method for a remote filepath check
		for the purpose of making smarter POST updates
		against current imgs.
	"""
	h = notebook.get_headers()
	r = notebook._api_request(requests.get, '/api/images', headers=h)
	img_data = r.json()

	nameMtime = {}
	for img in img_data:
		img['mod_date'] = _convert_datetime(img['mod_date'])
		nameMtime.update({img['img_name']: img['mod_date']})

	return nameMtime


def delete_unlisted_post(notebook, rname):
	""" (internal use)
		request method to remove the HTML at filepath
		of Note(s) made non- #public
	"""
	h = notebook.get_headers()
	r = notebook._api_request(
		requests.delete,
		f'/api/publishment/{rname}',
		headers=h,
	)
	print(f'(removed) {r.json()["pub_name"]} -> {r}')
	return r


def post_commits(notebook, stage_only=False, *, prune=False, refresh_images=False, mode="auto", accept_remote=False):
	from pretty_notebook._internal import publication_plan as _publication_plan, publication_execute as _publication_execute
	plan = _publication_plan.prepare(notebook, mode=mode, prune=prune, refresh_images=refresh_images, accept_remote=accept_remote)
	if plan is None:
		return _legacy_post_commits(notebook, stage_only, prune=prune, refresh_images=refresh_images)
	if stage_only:
		preview = plan.preview()
		for action in (*preview["pages"], *preview["images"]):
			print(f'{action["action"]}: {action["name"]}')
		return preview
	result = _publication_execute.execute(notebook, plan)
	for action in (*result["pages"], *result["images"]):
		print(f'{action["action"]}: {action["name"]}')
	return result


def _legacy_post_commits(
	notebook,
	stage_only=False,
	*,
	prune=False,
	refresh_images=False,
):
	""" the main POST method

	:param stage_only: if stage_only, print #public and don't commit
	:param prune: remove every remote page absent from this notebook
	:param refresh_images: resend referenced images even when names exist remotely
	"""
	notebook._require_clean_notes("preview or publish remote commits")
	notebook.open_md()
	notes, publication_images = notebook._publication_preflight(include_images=True)
	route_entries = {entry["source_path"]: entry for entry in notebook.publication_routes()["routes"]}
	_remote_route_preview(notebook)
	h = notebook.get_headers()

	pub_pub_data = notebook.get_pub_commits()
	pub_pub_names = tuple(pub_pub_data)

	pub_img_data = notebook.get_img_commits()
	pub_img_names = set(pub_img_data)

	print(f'\ncommits: (to {notebook.API_BASE})')
	post_names = []
	uploaded_images = set()
	for n in notes:
		to_post = False
		route = _routes.route_for(n, notebook.config)
		fname = route.route[1:] + '.html'

		post_names.append(fname)
		if fname in pub_pub_names:
			if pub_pub_data[fname] < n.mtime: # change has occurred
				to_post = True
		else: # it's newly #public
			to_post = True

		if stage_only:
			continue

		if to_post:
			html = notebook.convert_to_html(note=n)
			r = notebook._api_request(
				requests.post,
				'/api/publishment',
				json={
					"name": route.route[1:], "content": html,
					**({"title": route.title, "aliases": route_entries[route.source_path]["aliases"]}
						if notebook.config.get("ROUTE_MODE", "flat") != "flat" or notebook.config.get("PUBLICATION_ROUTES") else {}),
				},
				headers=h,
			)
			print(f'\t{n.name} -> {r}')

		for img in re.findall(Link.MDS_IMG_LNK, n.md):
			img = img.strip()
			if img in uploaded_images:
				continue

			if refresh_images or img not in pub_img_names:
				path, content_type = publication_images[img]
				with path.open('rb') as image_file:
					r = notebook._api_request(
						requests.post,
						'/api/image',
						files={"file": (path.name, image_file, content_type)},
						headers=h,
					)

				print(f'\t\t{img} -> {r}')
				uploaded_images.add(img)
			else:
				print(f'\t\t{img} -> EXISTS!')

	removals = [name for name in pub_pub_names if name not in post_names]

	if stage_only:
		print("\nnew pub: ")
		for p in [n for n in post_names if not n in pub_pub_names]:
			print(f'-> {p}')

		print("\nto remove:")
		for p in removals:
			print(f'-> {p}')

		print("\nall current pubs: ")
		for p in post_names:
			print(f'-> {p}')

		print("\n\n** stage_only=True, no changes made... ***")
	elif prune:
		if removals:
			print(f'\npruning {len(removals)} remote page(s):')
		for p in removals:
			notebook.delete_unlisted_post(p)
	elif removals:
		print("\nremote pages not pruned; use prune=True after reviewing stage output:")
		for p in removals:
			print(f'-> {p}')


def web_settings_post(notebook):
	""" request method to POST layout update
		from notebook.NOTE_PATH/pnbp_settings.json
		(see https://github.com/outside-labs/pretty-notebook/blob/main/apps/web-settings.json
		for examples)
	"""
	h = notebook.get_headers()

	_config = notebook.config.copy()

	bs_keys = tuple([
					"NAV_BRAND", "NAV_PAGES",
					"FOOTER", "TITLE",
					"darkmode", "APPEARANCE",
					"hljs_light", "hljs_dark",
					"merm_light", "merm_dark"
					])

	for k in notebook.config.keys():
		if not k in bs_keys:
			del _config[k]

	r = notebook._api_request(
		requests.post,
		'/api/layout',
		json=_config,
		headers=h,
	)

	print(r)
	return r


def post_favicon(notebook, path):
	"""Upload one PNG favicon using the notebook's configured site credentials."""
	path = Path(path).expanduser()
	if path.suffix.lower() != ".png":
		raise ValueError("Favicon must use the PNG format.")
	with path.open("rb") as source:
		content = source.read(1024 * 1024 + 1)
	if len(content) > 1024 * 1024:
		raise ValueError("Favicon exceeds the 1 MiB limit.")
	return notebook._api_request(requests.post, "/api/favicon",
		files={"file": (path.name, content, "image/png")}, headers=notebook.get_headers())


def create_api_user(notebook, username='', bootstrap_token=None):
	""" request method to generate an pnbp-web API user
	"""
	if not username:
		username = input('username: ')

	print(f'username: {username}')

	while True:
		p_1 = getpass.getpass("create password: ")
		p_2 = getpass.getpass("password (again): ")

		if p_1 == p_2:
			break

		print("The passwords do not match. Please try again.")

	u = {
		"username": username,
		"password_hash": p_1
		}

	h = notebook.get_headers()
	if not notebook.API_TOKEN:
		if bootstrap_token is None:
			bootstrap_token = getpass.getpass("bootstrap token: ")
		if bootstrap_token:
			h['X-PNBP-Bootstrap-Token'] = bootstrap_token
	r = requests.post(
		f'{notebook.API_BASE}/api/users',
		json=u,
		headers=h,
		timeout=notebook.REQUEST_TIMEOUT,
	)
	print(r)
	print(r.json())
	return r


def reset_api_password(notebook):
	""" request method to update the authed user's API password
	"""
	while True:
		p_1 = getpass.getpass("new password: ")
		p_2 = getpass.getpass("password (again): ")

		if p_1 == p_2:
			break

		print('passwords do not match...')

	p = {"password_hash": p_1}
	h = notebook.get_headers()
	r = requests.post(
		f'{notebook.API_BASE}/api/users/me',
		json=p,
		headers=h,
		timeout=notebook.REQUEST_TIMEOUT,
	)
	print(r)
	print(r.json())
	return r
