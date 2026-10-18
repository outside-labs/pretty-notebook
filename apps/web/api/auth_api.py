"""Bearer authentication and single-use owner bootstrap."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from decouple import config
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.hash import bcrypt
from pydantic import BaseModel, Field, field_validator
from tortoise import connections, fields
from tortoise.contrib.pydantic import pydantic_model_creator
from tortoise.models import Model
from tortoise.transactions import in_transaction

router = APIRouter()

JWT_SECRET = config("JWT_SECRET")
JWT_ALGO = config("JWT_ALGO", default="HS256")
TOKEN_LIFETIME = timedelta(days=30)
BOOTSTRAP_HEADER = "X-PNBP-Bootstrap-Token"
MIN_SECRET_BYTES = 32
MIN_PASSWORD_CHARACTERS = 12
MAX_PASSWORD_BYTES = 72


def validate_jwt_settings(secret: str, algorithm: str) -> None:
    """Reject weak or unexpectedly configured signing settings at startup."""
    if algorithm != "HS256":
        raise RuntimeError("JWT_ALGO must be HS256")
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes")


validate_jwt_settings(JWT_SECRET, JWT_ALGO)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token", auto_error=False)


class User(Model):
    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=50, unique=True)
    password_hash = fields.CharField(max_length=128)
    tok_uuid = fields.TextField(default=lambda: secrets.token_urlsafe(32))

    def verify_password(self, password: str) -> bool:
        return bcrypt.verify(password, self.password_hash)


class PasswordInput(BaseModel):
    password_hash: str = Field(min_length=MIN_PASSWORD_CHARACTERS, max_length=128)

    @field_validator("password_hash")
    @classmethod
    def supported_bcrypt_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError("Password may contain at most 72 UTF-8 bytes")
        return value


class UserInput(PasswordInput):
    username: str = Field(min_length=1, max_length=50)

    @field_validator("username")
    @classmethod
    def nonblank_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username cannot be blank")
        return value


User_Pydantic = pydantic_model_creator(
    User,
    name="User",
    exclude=("password_hash", "tok_uuid"),
)


async def get_optional_user(
    token: Annotated[str | None, Depends(optional_oauth2_scheme)] = None,
):
    """Authenticate a supplied token while allowing a genuinely absent token."""
    if token is None:
        return None
    return await get_current_user(token)


async def _has_ever_created_user() -> bool:
    """Keep anonymous bootstrap closed after the first user is deleted."""
    if await User.all().exists():
        return True

    connection = connections.get("default")
    rows = await connection.execute_query_dict(
        "SELECT seq FROM sqlite_sequence WHERE name = ? LIMIT 1",
        [User._meta.db_table],
    )
    return bool(rows)


def _require_bootstrap_token(request: Request) -> None:
    expected = config("PNBP_BOOTSTRAP_TOKEN", default="")
    supplied = request.headers.get(BOOTSTRAP_HEADER, "")
    configured_safely = len(expected.encode("utf-8")) >= MIN_SECRET_BYTES
    if (
        not configured_safely
        or not supplied
        or not secrets.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid bootstrap token is required.",
        )


async def _save_user(user: UserInput, *, role='reader') -> User_Pydantic:
    user_obj = User(
        username=user.username,
        password_hash=bcrypt.hash(user.password_hash),
    )
    async with in_transaction() as connection:
        await user_obj.save(using_db=connection)
        await connection.execute_query('INSERT INTO pnbp_roles VALUES (?,?)', [user_obj.id, role])
        if role == 'owner':
            await connection.execute_query("UPDATE pnbp_notebooks SET owner_id=? WHERE slot='default' AND owner_id IS NULL", [user_obj.id])
    return await User_Pydantic.from_tortoise_orm(user_obj)


@router.post("/api/users", response_model=User_Pydantic)
async def create_user(
    user: UserInput,
    request: Request,
    curr_user: Annotated[User_Pydantic | None, Depends(get_optional_user)],
):
    """Allow one secret-authorized owner claim, then owner-created accounts."""
    if curr_user is None:
        async with request.app.state.bootstrap_lock:
            if await _has_ever_created_user():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Cannot access.",
                )
            _require_bootstrap_token(request)
            return await _save_user(user, role='owner')

    if curr_user.role != 'owner' or 'admin' not in curr_user.scopes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not allowed.",
        )

    return await _save_user(user)


def _password_supported(password: str) -> bool:
    byte_length = len(password.encode("utf-8"))
    return (
        MIN_PASSWORD_CHARACTERS <= len(password) and byte_length <= MAX_PASSWORD_BYTES
    )


async def authenticate_user(username: str, password: str):
    if not _password_supported(password):
        return False
    user = await User.filter(username=username.strip()).first()
    if not user or not user.verify_password(password=password):
        return False
    return user


async def _generate_token(user: User) -> str:
    now = datetime.now(UTC)
    token_id = secrets.token_urlsafe(32)
    user.tok_uuid = token_id
    await user.save(update_fields=["tok_uuid"])

    payload = {
        "sub": str(user.id),
        "username": user.username,
        "tok_uuid": token_id,
        "iat": now,
        "exp": now + TOKEN_LIFETIME,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


@router.post("/api/token")
async def generate_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    user = await authenticate_user(
        username=form_data.username,
        password=form_data.password,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = await _generate_token(user)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"access_token": token, "token_type": "bearer"}


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    from .permissions import authenticate_credential, principal_for
    if token.startswith('pnbp_'):
        return await authenticate_credential(token)
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGO],
            options={"require": ["sub", "tok_uuid", "iat", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise unauthorized("Could not validate credentials") from exc

    try:
        user_id = int(payload["sub"])
        token_id = payload["tok_uuid"]
    except (KeyError, TypeError, ValueError) as exc:
        raise unauthorized("Could not validate credentials") from exc

    user = await User.get_or_none(id=user_id)
    if user is None or not isinstance(token_id, str):
        raise unauthorized("Could not validate credentials")
    if not secrets.compare_digest(token_id, user.tok_uuid):
        raise unauthorized("Token revoked or superseded")

    return await principal_for(user)


@router.get("/api/users/me", response_model=User_Pydantic)
async def get_user(user: Annotated[User_Pydantic, Depends(get_current_user)]):
    return {"id": user.id, "username": user.username}


@router.post("/api/users/me", response_model=User_Pydantic)
async def reset_password(
    password: PasswordInput,
    user: Annotated[User_Pydantic, Depends(get_current_user)],
):
    from .permissions import authorize
    orm_user = await User.get_or_none(id=user.id)
    if orm_user is None:
        raise unauthorized("Could not validate credentials")
    await authorize(user, 'account')

    orm_user.password_hash = bcrypt.hash(password.password_hash)
    orm_user.tok_uuid = secrets.token_urlsafe(32)
    await orm_user.save(update_fields=["password_hash", "tok_uuid"])
    return await User_Pydantic.from_tortoise_orm(orm_user)


@router.get("/api")
async def api_index(user: Annotated[User_Pydantic, Depends(get_current_user)]):
    return {"authenticated": True, "username": user.username}
