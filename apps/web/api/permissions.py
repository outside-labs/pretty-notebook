"""Explicit site permissions, notebook grants and revocable script credentials."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from tortoise import connections

from .auth_api import User, get_current_user, unauthorized

router = APIRouter()
SCOPES = frozenset({'account', 'admin', 'site', 'inbox', 'read', 'publish', 'logs'})
NOTEBOOK_SCOPES = frozenset({'read', 'publish', 'logs'})
ROLE_SCOPES = {
    'owner': SCOPES,
    'editor': frozenset({'account', 'read', 'publish', 'logs'}),
    'reader': frozenset({'account', 'read'}),
    'inbox': frozenset({'account', 'inbox'}),
}
PERMISSION_SCHEMA = (
    "CREATE TABLE pnbp_roles (user_id INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('owner','editor','reader','inbox')))",
    "INSERT INTO pnbp_roles SELECT id, CASE WHEN id=1 THEN 'owner' ELSE 'editor' END FROM user",
    "CREATE TABLE pnbp_grants (user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE, notebook TEXT NOT NULL, permission TEXT NOT NULL, PRIMARY KEY(user_id,notebook,permission))",
    "INSERT INTO pnbp_grants SELECT id, 'default', 'read' FROM user WHERE id<>1",
    "INSERT INTO pnbp_grants SELECT id, 'default', 'publish' FROM user WHERE id<>1",
    "INSERT INTO pnbp_grants SELECT id, 'default', 'logs' FROM user WHERE id<>1",
    "CREATE TABLE pnbp_credentials (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE, digest TEXT NOT NULL UNIQUE, generation TEXT NOT NULL, scopes TEXT NOT NULL, notebook TEXT NOT NULL, expires_at TEXT NOT NULL)",
)


@dataclass(frozen=True)
class Principal:
    id: int
    username: str
    role: str
    scopes: frozenset[str] = SCOPES
    notebook: str | None = None


async def principal_for(user, *, scopes=SCOPES, notebook=None):
    rows = await connections.get('default').execute_query_dict('SELECT role FROM pnbp_roles WHERE user_id=?', [user.id])
    # Missing roles never inherit privileges from a numeric user ID.
    return Principal(user.id, user.username, rows[0]['role'] if rows else 'reader', frozenset(scopes), notebook)


async def authorize(user, permission, notebook='default'):
    if permission not in user.scopes or permission not in ROLE_SCOPES[user.role]:
        raise HTTPException(403, 'Permission denied.')
    if permission in NOTEBOOK_SCOPES:
        if user.notebook is not None and user.notebook != notebook:
            raise HTTPException(403, 'Permission denied.')
        if user.role != 'owner':
            rows = await connections.get('default').execute_query_dict(
                'SELECT 1 FROM pnbp_grants WHERE user_id=? AND notebook=? AND permission=?', [user.id, notebook, permission])
            if not rows:
                raise HTTPException(403, 'Permission denied.')
    return user


def require_permission(permission):
    async def check(request: Request, user=Depends(get_current_user)):
        return await authorize(user, permission, request.headers.get('X-PNBP-Notebook', 'default'))
    return check


async def authenticate_credential(token):
    rows = await connections.get('default').execute_query_dict(
        'SELECT * FROM pnbp_credentials WHERE digest=?', [hashlib.sha256(token.encode()).hexdigest()])
    if not rows or datetime.fromisoformat(rows[0]['expires_at']) <= datetime.now(UTC):
        raise unauthorized('Could not validate credentials')
    credential = rows[0]
    user = await User.get_or_none(id=credential['user_id'])
    if user is None or not secrets.compare_digest(credential['generation'], user.tok_uuid):
        raise unauthorized('Token revoked or superseded')
    return await principal_for(user, scopes=json.loads(credential['scopes']), notebook=credential['notebook'])


class GrantInput(BaseModel):
    notebook: str = Field(default='default', min_length=1, max_length=100)
    permissions: list[Literal['read', 'publish', 'logs']] = Field(max_length=3)


class RoleInput(BaseModel):
    role: Literal['owner', 'editor', 'reader', 'inbox']


@router.put('/api/users/{user_id}/role', dependencies=[Depends(require_permission('admin'))])
async def set_role(user_id: int, data: RoleInput, request: Request):
    async with request.app.state.storage_lock:
        connection = connections.get('default')
        rows = await connection.execute_query_dict('SELECT role FROM pnbp_roles WHERE user_id=?', [user_id])
        if not rows:
            raise HTTPException(404, 'Account not found.')
        owners = await connection.execute_query_dict("SELECT COUNT(*) AS total FROM pnbp_roles WHERE role='owner'")
        if rows[0]['role'] == 'owner' and data.role != 'owner' and owners[0]['total'] == 1:
            raise HTTPException(409, 'Keep at least one site owner.')
        await connection.execute_query('UPDATE pnbp_roles SET role=? WHERE user_id=?', [data.role, user_id])
    return {'id': user_id, 'role': data.role}


@router.put('/api/users/{user_id}/grants', dependencies=[Depends(require_permission('admin'))])
async def set_grants(user_id: int, data: GrantInput, request: Request):
    if not await User.filter(id=user_id).exists():
        raise HTTPException(404, 'Account not found.')
    from tortoise.transactions import in_transaction
    async with request.app.state.storage_lock:
        async with in_transaction() as connection:
            await connection.execute_query('DELETE FROM pnbp_grants WHERE user_id=? AND notebook=?', [user_id, data.notebook])
            for permission in set(data.permissions):
                await connection.execute_query('INSERT INTO pnbp_grants VALUES (?,?,?)', [user_id, data.notebook, permission])
    return data


class CredentialInput(BaseModel):
    notebook: str = Field(default='default', min_length=1, max_length=100)
    scopes: list[Literal['site', 'inbox', 'read', 'publish', 'logs']] = Field(min_length=1, max_length=5)
    lifetime_days: int = Field(default=30, ge=1, le=90)


@router.post('/api/credentials', status_code=201)
async def create_credential(data: CredentialInput, user=Depends(require_permission('account'))):
    for permission in data.scopes:
        await authorize(user, permission, data.notebook)
    token = 'pnbp_' + secrets.token_urlsafe(32)
    orm_user = await User.get(id=user.id)
    expires = (datetime.now(UTC) + timedelta(days=data.lifetime_days)).isoformat()
    await connections.get('default').execute_query(
        'INSERT INTO pnbp_credentials (user_id,digest,generation,scopes,notebook,expires_at) VALUES (?,?,?,?,?,?)',
        [user.id, hashlib.sha256(token.encode()).hexdigest(), orm_user.tok_uuid, json.dumps(sorted(set(data.scopes))), data.notebook, expires])
    return {'access_token': token, 'token_type': 'bearer', 'expires_at': expires}


@router.get('/api/credentials')
async def list_credentials(user=Depends(require_permission('account'))):
    return await connections.get('default').execute_query_dict(
        'SELECT id,scopes,notebook,expires_at FROM pnbp_credentials WHERE user_id=? ORDER BY id LIMIT 100', [user.id])


@router.delete('/api/credentials/{credential_id}', status_code=204)
async def revoke_credential(credential_id: int, user=Depends(require_permission('account'))):
    await connections.get('default').execute_query('DELETE FROM pnbp_credentials WHERE id=? AND user_id=?', [credential_id, user.id])
