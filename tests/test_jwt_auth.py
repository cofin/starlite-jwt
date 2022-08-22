import string
from datetime import timedelta
from typing import TYPE_CHECKING, Optional

import pytest
from hypothesis import given
from hypothesis.strategies import integers, none, one_of, sampled_from, text, timedeltas
from starlite import Request, Response, get
from starlite.testing import create_test_client

from starlite_jwt_auth import JWTAuth, Token
from tests.conftest import User, UserFactory

if TYPE_CHECKING:

    from starlite.cache import SimpleCacheBackend

algorithms = [
    "HS256",
    "HS384",
    "HS512",
]

headers = ["Authorization", "X-API-Key"]


@pytest.mark.asyncio()
@given(
    algorithm=sampled_from(algorithms),
    auth_header=sampled_from(headers),
    default_token_expiration=timedeltas(min_value=timedelta(seconds=30), max_value=timedelta(weeks=1)),
    token_secret=text(min_size=10),
    response_status_code=integers(min_value=200, max_value=201),
    token_expiration=timedeltas(min_value=timedelta(seconds=1), max_value=timedelta(weeks=1)),
    token_issuer=one_of(none(), text(max_size=256)),
    token_audience=one_of(none(), text(max_size=256, alphabet=string.ascii_letters)),
    token_unique_jwt_id=one_of(none(), text(max_size=256)),
)
async def test_jwt_auth(
    mock_db: "SimpleCacheBackend",
    algorithm: str,
    auth_header: str,
    default_token_expiration: timedelta,
    token_secret: str,
    response_status_code: int,
    token_expiration: Optional[timedelta],
    token_issuer: Optional[str],
    token_audience: Optional[str],
    token_unique_jwt_id: Optional[str],
) -> None:
    user = UserFactory.build()

    await mock_db.set(str(user.id), user, 120)

    async def retrieve_user_handler(sub: str) -> "User":
        stored_user = await mock_db.get(sub)
        assert stored_user
        return stored_user

    jwt_auth = JWTAuth(
        algorithm=algorithm,
        auth_header=auth_header,
        default_token_expiration=default_token_expiration,
        token_secret=token_secret,
        retrieve_user_handler=retrieve_user_handler,
    )

    @get("/my-endpoint", middleware=[jwt_auth.create_middleware])
    def my_handler(request: Request["User", Token]) -> None:
        assert request.user
        assert request.user.name == user.name
        assert request.user.id == user.id
        assert request.auth
        assert request.auth.sub == user.id

    @get("/login")
    async def login_handler() -> Response["User"]:
        response = await jwt_auth.login(
            identifier=str(user.id),
            response_body=user,
            response_status_code=response_status_code,
            token_expiration=token_expiration,
            token_issuer=token_issuer,
            token_audience=token_audience,
            token_unique_jwt_id=token_unique_jwt_id,
        )
        return response

    with create_test_client(route_handlers=[my_handler, login_handler]) as client:
        response = client.get("/login")
        assert response.status_code == response_status_code
        encoded_token = response.headers.get(auth_header)
        assert encoded_token
        decoded_token = Token.decode(encoded_token=encoded_token, secret=token_secret, algorithm=algorithm)
        assert decoded_token.sub == str(user.id)
        assert decoded_token.iss == token_issuer
        assert decoded_token.aud == token_audience
        assert decoded_token.jti == token_unique_jwt_id
