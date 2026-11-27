"""Auth0 and API constants for Calm Client."""

from __future__ import annotations

# Auth0 tenant configuration (extracted from web login flow)
AUTH0_DOMAIN = "oneid.calm.com"
AUTH0_CLIENT_ID = "bqG2PSDLcAuZ1pD00NIOOmMEi0anL1lG"
AUTH0_AUDIENCE = "https://api.calm.com/"
AUTH0_CONNECTION = "Calm-Username-Password-Authentication"
AUTH0_SCOPE = "openid profile email offline_access"

# Auth0 ROPC grant type with realm support
AUTH0_GRANT_TYPE = "http://auth0.com/oauth/grant-type/password-realm"
AUTH0_TOKEN_URL = f"https://{AUTH0_DOMAIN}/oauth/token"

# User agent sent when calm-client owns its HTTP session and the caller set none.
# It mirrors the desktop web app that the authproxy endpoints serve. Whether Calm
# rejects other user agents has not been verified; integrations can pass their own.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
