"""Contact Energy API client."""

from __future__ import annotations

import asyncio
from datetime import date
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.contact-digital-prod.net"
# Public key shipped with the Contact Energy mobile app.
API_KEY = "z840P4lQCH9TqcjC9L2pP157DZcZJMcr5tVQCvyx"
# The usage endpoint regularly takes several seconds to answer.
REQUEST_TIMEOUT = 60


class ContactEnergyError(Exception):
    """Base error for the Contact Energy API."""


class CannotConnect(ContactEnergyError):
    """The API could not be reached or returned an unexpected response."""


class InvalidAuth(ContactEnergyError):
    """The email or password was rejected."""


class ContactEnergyApi:
    """Async client for the API used by the Contact Energy app."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    async def async_login(self) -> None:
        """Log in and keep the session token."""
        async with self._login_lock:
            if self._token:
                return
            status, data = await self._raw_request(
                "POST",
                "/login/v2",
                json={"username": self._email, "password": self._password},
            )
            if status in (400, 401, 403):
                raise InvalidAuth
            if status != 200 or not isinstance(data, dict) or not data.get("token"):
                raise CannotConnect(f"Unexpected login response ({status})")
            self._token = data["token"]

    async def async_get_accounts(self, account_id: str | None = None) -> dict[str, Any]:
        """Return the account summary and the detail of one account."""
        params = {"ba": account_id} if account_id else None
        data = await self._request("GET", "/accounts/v2", params=params)
        if not isinstance(data, dict) or "accountDetail" not in data:
            raise CannotConnect("Unexpected accounts response")
        return data

    async def async_get_plan_details(self, account_id: str) -> dict[str, Any]:
        """Return the plan of every contract of an account."""
        data = await self._request(
            "GET", "/usage/v2/plan-details", params={"ba": account_id}
        )
        return data if isinstance(data, dict) else {}

    async def async_get_usage(
        self,
        contract_id: str,
        account_id: str,
        interval: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Return usage points ("hourly" only works for a single day).

        The API answers 502 when there is nothing to return for the
        contract/interval/range (e.g. hourly or daily gas), so that is
        treated as "no data".
        """
        data = await self._request(
            "POST",
            f"/usage/v2/{contract_id}",
            params={
                "ba": account_id,
                "interval": interval,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
            empty_on_502=True,
        )
        return data if isinstance(data, list) else []

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        empty_on_502: bool = False,
    ) -> Any:
        """Make an authenticated request, logging in again once if needed."""
        for attempt in range(2):
            if not self._token:
                await self.async_login()
            status, data = await self._raw_request(
                method, path, params=params, session=self._token
            )
            if status == 401 and attempt == 0:
                _LOGGER.debug("Session expired, logging in again")
                self._token = None
                continue
            if status == 401:
                raise InvalidAuth
            if status == 200:
                return data
            if status == 502 and empty_on_502:
                return None
            raise CannotConnect(f"{method} {path} returned {status}")
        raise CannotConnect(f"{method} {path} failed")

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        session: str | None = None,
    ) -> tuple[int, Any]:
        """Send one request and return its status and decoded JSON body."""
        headers = {"x-api-key": API_KEY}
        if session:
            headers["session"] = session
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, BASE_URL + path, params=params, json=json, headers=headers
                ) as response:
                    _LOGGER.debug("%s %s -> %s", method, path, response.status)
                    try:
                        data = await response.json(content_type=None)
                    except ValueError:
                        data = None
                    return response.status, data
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(f"{method} {path}: {err}") from err
