from calm_client.auth import BearerAuth, CookieAuth, auth_for
from calm_client.credentials import Credentials


def test_auth_factory_default() -> None:
    creds = Credentials(token="test_token")
    strategy = auth_for(creds)
    assert isinstance(strategy, CookieAuth)
    assert strategy.credentials == creds


def test_bearer_auth() -> None:
    creds = Credentials(token="test_token")
    strategy = BearerAuth(creds)
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert headers["Authorization"] == "Bearer test_token"
    assert "x-calm-platform" in headers


def test_cookie_auth() -> None:
    creds = Credentials(token="test_token")
    strategy = CookieAuth(creds)
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert headers["Cookie"] == "calm-user-token=test_token"
    assert "x-calm-platform" in headers


def test_auth_no_token() -> None:
    creds = Credentials(token="")
    strategy = CookieAuth(creds)
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert "Cookie" not in headers


def test_bearer_auth_without_token() -> None:
    strategy = BearerAuth(Credentials(token=""))
    headers: dict[str, str | bytes] = {}
    strategy.before_request(headers)
    assert "Authorization" not in headers


def test_cookie_auth_prefers_session_token() -> None:
    creds = Credentials(token="jwt", session_token="session", device_id="dev-1")
    headers: dict[str, str | bytes] = {}
    CookieAuth(creds).before_request(headers)
    assert headers["Cookie"] == "calm-user-token=session"
    assert headers["x-session-token"] == "session"
    assert headers["x-device-id"] == "dev-1"


def test_cookie_auth_without_device_id() -> None:
    creds = Credentials(token="jwt", device_id="")
    headers: dict[str, str | bytes] = {}
    CookieAuth(creds).before_request(headers)
    assert "x-device-id" not in headers
