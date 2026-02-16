from calm_client.auth import BearerAuth, CookieAuth, auth_for
from calm_client.credentials import Credentials


def test_auth_factory_default() -> None:
    creds = Credentials(access_token="test_token")
    strategy = auth_for(creds)
    assert isinstance(strategy, CookieAuth)
    assert strategy.credentials == creds


def test_bearer_auth() -> None:
    creds = Credentials(access_token="test_token")
    strategy = BearerAuth(creds)
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert headers["Authorization"] == "Bearer test_token"
    assert "x-calm-platform" in headers


def test_cookie_auth() -> None:
    creds = Credentials(access_token="test_token")
    strategy = CookieAuth(creds)
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert headers["Cookie"] == "calm-user-token=test_token"
    assert "x-calm-platform" in headers


def test_auth_no_token() -> None:
    creds = Credentials(access_token="")
    strategy = CookieAuth(creds)
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert "Cookie" not in headers
