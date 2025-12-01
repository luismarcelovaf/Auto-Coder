"""Authentication utilities including certificate and SSO support."""

import io
import os
import zipfile
from typing import Any

import certifi
import httpx
import requests

from .authentication_provider import (
    AuthenticationProvider,
    AuthenticationProviderWithClientSideTokenRefresh,
)

# Flag to track if certifi has been updated
_certifi_updated = False


def update_certifi() -> None:
    """Update certifi certificates (only runs once).

    This function is a placeholder for custom certificate management.
    Implement your certificate update logic here.
    Subsequent calls after the first will be no-ops.
    """
    global _certifi_updated
    if _certifi_updated:
        return

    # TODO: Implement certificate update logic

    _certifi_updated = True


def get_certifi_path() -> str:
    """Get the path to the certifi CA bundle.

    Returns:
        Path to the CA certificate bundle
    """
    return certifi.where()


def is_sso_enabled() -> bool:
    """Check if SSO authentication is enabled.

    Returns:
        True if USE_SSO environment variable is not set or set to 'true' (case-insensitive).
        Only returns False if explicitly set to 'false'.
    """
    value = os.environ.get("USE_SSO", "true").lower()
    return value != "false"


def is_server_side_token_refresh_enabled() -> bool:
    """Check if server-side token refresh is enabled.

    Returns:
        True if SERVER_SIDE_TOKEN_REFRESH environment variable is set to 'true'
    """
    return os.environ.get("SERVER_SIDE_TOKEN_REFRESH", "").lower() == "true"


def get_authentication(
    auth_provider: AuthenticationProvider | None = None,
) -> tuple[dict[str, str], httpx.Auth | None]:
    """Get authentication headers and/or httpx.Auth based on configuration.

    Authentication logic:
    1. If USE_SSO is true: Use AuthenticationProvider to generate a bearer token
    2. If USE_SSO is false and SERVER_SIDE_TOKEN_REFRESH is true:
       Use AuthenticationProvider to get basic credentials
    3. Otherwise: Use AuthenticationProviderWithClientSideTokenRefresh as httpx.Auth

    Args:
        auth_provider: Optional AuthenticationProvider instance.
                       If not provided, a new one will be created.

    Returns:
        Tuple of (headers dict, httpx.Auth instance or None)
    """
    headers: dict[str, str] = {}
    auth: httpx.Auth | None = None

    if auth_provider is None:
        auth_provider = AuthenticationProvider()

    if is_sso_enabled():
        # Case 1: SSO enabled - use bearer token
        token = auth_provider.generate_auth_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif is_server_side_token_refresh_enabled():
        # Case 2: Server-side token refresh - use basic credentials
        credentials = auth_provider.get_basic_credentials()
        if credentials:
            headers["Authorization"] = f"Basic {credentials}"
    else:
        # Case 3: Client-side token refresh - use httpx.Auth
        auth = AuthenticationProviderWithClientSideTokenRefresh()

    return headers, auth
