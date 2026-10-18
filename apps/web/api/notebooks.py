"""Durable notebook owners and isolated publication namespaces."""

from pathlib import Path
from uuid import uuid4
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from tortoise import connections
from tortoise.transactions import in_transaction

from .catalog import PublicationStore, RouteConflict
from .permissions import require_permission

router = APIRouter()
OWNERSHIP_SCHEMA = (
    'CREATE TABLE pnbp_notebooks_next (slot TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, owner_id INTEGER REFERENCES user(id) ON DELETE SET NULL)',
    "INSERT INTO pnbp_notebooks_next SELECT slot,id,(SELECT user_id FROM pnbp_roles WHERE role='owner' ORDER BY user_id LIMIT 1) FROM pnbp_notebooks",
    'DROP TABLE pnbp_notebooks',
    'ALTER TABLE pnbp_notebooks_next RENAME TO pnbp_notebooks',
)


class NotebookInput(BaseModel):
    slug: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=80)
    owner_id: int = Field(ge=1)


async def notebook_record(slug):
    rows = await connections.get('default').execute_query_dict('SELECT * FROM pnbp_notebooks WHERE slot=?', [slug])
    if not rows:
        raise HTTPException(404, 'Notebook not found.')
    return rows[0]


def images_directory(root, slug):
    root = Path(root)
    path = root if slug == 'default' else root / 'n' / slug
    for candidate in (root, root / 'n', path):
        if candidate.is_symlink():
            raise HTTPException(503, 'Notebook image storage is unavailable.')
    return path


class NotebookStore(PublicationStore):
    def __init__(self, store, record):
        super().__init__(store.pages, lock=store.lock)
        self.notebook_id = record['id']
        self.slug = record['slot']

    async def check_name(self, name):
        if self.slug != 'default':
            if not name.startswith('n/' + self.slug + '/'):
                raise RouteConflict('Use this notebook’s /n/<slug>/ publication namespace.')
        elif name.startswith('n/'):
            slug = name.split('/', 2)[1]
            rows = await connections.get('default').execute_query_dict('SELECT 1 FROM pnbp_notebooks WHERE slot=?', [slug])
            if rows:
                raise RouteConflict('This namespace belongs to a separate notebook.')

    async def _note(self, name, *, connection=None):
        note = await super()._note(name, connection=connection)
        if note and note['notebook_id'] != self.notebook_id:
            raise HTTPException(404, 'Publication not found.')
        return note

    async def _claim(self, name, aliases=(), previous_name=None):
        for candidate in (name, *(alias.removeprefix('/') for alias in aliases), *((previous_name,) if previous_name else ())):
            await self.check_name(candidate)
        return await super()._claim(name, aliases, previous_name)

    async def inventory(self, *, detailed=False):
        entries = await super().inventory(detailed=True)
        selected = [entry for entry in entries if entry.get('notebook_id') == self.notebook_id or (self.slug == 'default' and 'notebook_id' not in entry)]
        if detailed:
            return selected
        return [{key: entry[key] for key in ('pub_name', 'mod_date')} for entry in selected]

    async def delete(self, name, **kwargs):
        await self.check_name(name)
        return await super().delete(name, **kwargs)


async def publication_store(request):
    record = await notebook_record(request.headers.get('X-PNBP-Notebook', 'default'))
    return NotebookStore(request.app.state.publications, record)


async def image_directory(request):
    record = await notebook_record(request.headers.get('X-PNBP-Notebook', 'default'))
    return images_directory(request.app.state.images_path, record['slot'])


@router.post('/api/notebooks', status_code=201, dependencies=[Depends(require_permission('admin'))])
async def create_notebook(data: NotebookInput, request: Request):
    if data.slug == 'default':
        raise HTTPException(409, 'The default notebook already exists.')
    async with request.app.state.storage_lock:
        connection = connections.get('default')
        roles = await connection.execute_query_dict('SELECT role FROM pnbp_roles WHERE user_id=?', [data.owner_id])
        if not roles or roles[0]['role'] not in {'owner', 'editor'}:
            raise HTTPException(422, 'Choose an owner or editor account for notebook ownership.')
        if await connection.execute_query_dict('SELECT 1 FROM pnbp_notebooks WHERE slot=?', [data.slug]):
            raise HTTPException(409, 'Notebook slug already exists.')
        routes = await connection.execute_query_dict('SELECT canonical_route,aliases FROM pnbp_notes')
        prefix = '/n/' + data.slug + '/'
        if any(route.startswith(prefix) for note in routes for route in (note['canonical_route'], *json.loads(note['aliases']))):
            raise HTTPException(409, 'Existing legacy routes occupy this namespace; migrate them before claiming it.')
        # Prepare storage before committing a usable notebook record.
        directory = images_directory(request.app.state.images_path, data.slug)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        notebook_id = str(uuid4())
        async with in_transaction() as transaction:
            await transaction.execute_query('INSERT INTO pnbp_notebooks (slot,id,owner_id) VALUES (?,?,?)', [data.slug, notebook_id, data.owner_id])
            for permission in ('read', 'publish', 'logs'):
                await transaction.execute_query('INSERT INTO pnbp_grants VALUES (?,?,?)', [data.owner_id, data.slug, permission])
    return {'slug': data.slug, 'id': notebook_id, 'owner_id': data.owner_id}


@router.get('/api/notebooks')
async def list_notebooks(user=Depends(require_permission('account'))):
    connection = connections.get('default')
    if user.role == 'owner':
        return await connection.execute_query_dict('SELECT slot AS slug,id,owner_id FROM pnbp_notebooks ORDER BY slot LIMIT 100')
    return await connection.execute_query_dict("SELECT slot AS slug,id,owner_id FROM pnbp_notebooks WHERE slot IN (SELECT notebook FROM pnbp_grants WHERE user_id=?) ORDER BY slot LIMIT 100", [user.id])
