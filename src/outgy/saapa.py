import asyncio
import logging
import re

import httpx

from .dates import window
from .outage import Outage
from .text import latin_digits

logger = logging.getLogger(__name__)

PLANNED_BLACKOUTS_PATH = "/api/ebills/PlannedBlackoutsReport"
OTP_SEND_PATH = "/api/otp/sendCode"
OTP_VERIFY_PATH = "/api/otp/verifyCode"
GET_BILLS_PATH = "/api/ebills/GetBills"
SEARCH_BRANCH_PATH = "/api/ebills/SearchBranchData"
PROVIDERS_PATH = "/api/providers/list"
CITIES_PATH = "/api/providers/cities"

BILL_ID_RE = re.compile(r"^\d{8,18}$")
MOBILE_RE = re.compile(r"^09\d{9}$")
OTP_CODE_RE = re.compile(r"^\d{4,8}$")


class SaapaError(RuntimeError):
    pass


class SaapaRejected(SaapaError):
    pass


class SaapaAuthError(SaapaError):
    pass


def normalize_mobile(raw: str) -> str:
    number = re.sub(r"[^\d+]", "", latin_digits(raw).strip())
    if number.startswith("+98"):
        number = "0" + number[3:]
    elif number.startswith("0098"):
        number = "0" + number[4:]
    if len(number) == 10 and number.startswith("9"):
        number = "0" + number
    return number


_BILL_ID_KEYS = ("bill_identifier", "bill_id", "BillId", "billID")
_BILL_LABEL_KEYS = ("address", "outage_address", "subscription_id", "name")


def extract_bill_id(item: dict) -> str | None:
    for key in _BILL_ID_KEYS:
        value = item.get(key)
        if value and BILL_ID_RE.match(latin_digits(value).strip()):
            return latin_digits(value).strip()
    return None


def bill_label(item: dict) -> str:
    for key in _BILL_LABEL_KEYS:
        value = item.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return ""


_NAME_CLEAN_RE = re.compile(r"[\s\u200c\u0640]+")
_ARABIC_MAP = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "ؤ": "و"})


def normalize_name(value: str) -> str:
    cleaned = latin_digits(value).translate(_ARABIC_MAP)
    cleaned = _NAME_CLEAN_RE.sub("", cleaned).lower()
    for word in ("استان", "شرکت", "توزیع", "منطقه", "برق"):
        cleaned = cleaned.replace(word, "")
    return cleaned.strip("-_")


def provider_code(provider: dict) -> str:
    return str(provider.get("code") or provider.get("id") or provider.get("co_code") or "")


def provider_name(provider: dict) -> str:
    return str(provider.get("name") or provider.get("title") or "")


def match_providers(providers: list[dict], needle: str) -> list[dict]:
    query = normalize_name(needle)
    matches = []
    for provider in providers:
        name = normalize_name(provider_name(provider))
        code = provider_code(provider)
        if not name and not code:
            continue
        if query == name or (query and query in name) or query == code:
            matches.append(provider)
    return matches


class SaapaClient:
    RETRIES = 3

    def __init__(self, http: httpx.AsyncClient, base_url: str):
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
            ),
        }

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        token: str | None = None,
    ) -> dict:
        headers = {**self._headers}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{self._base_url}{path}"
        resp: httpx.Response | None = None
        for attempt in range(self.RETRIES):
            try:
                resp = await self._http.request(method, url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise SaapaError(f"request failed: {exc}") from exc
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.RETRIES - 1:
                    delay = 3.0 * (attempt + 1)
                    logger.info("saapa %s %s; retrying in %.0fs", resp.status_code, path, delay)
                    await asyncio.sleep(delay)
                    continue
            return _parse_response(resp)
        raise SaapaError("saapa kept failing after retries")

    async def _post(self, path: str, payload: dict, token: str | None = None) -> dict:
        return await self._request("POST", path, payload, token)

    async def _get(self, path: str, token: str | None = None) -> dict:
        return await self._request("GET", path, token=token)

    async def send_otp(self, mobile: str) -> None:
        await self._post(OTP_SEND_PATH, {"mobile": mobile})

    async def verify_otp(self, mobile: str, code: str) -> str:
        body = await self._post(
            OTP_VERIFY_PATH,
            {
                "mobile": mobile,
                "code": code,
                "request_source": 5,
                "device_token": "",
            },
        )
        token = (body.get("data") or {}).get("Token")
        if not token:
            raise SaapaRejected("verify succeeded but no token returned")
        return token

    async def planned_blackouts(self, bill_id: str, days: int, *, token: str) -> list[Outage]:
        from_date, to_date = window(days)
        body = await self._post(
            PLANNED_BLACKOUTS_PATH,
            {
                "bill_id": bill_id,
                "from_date": from_date,
                "to_date": to_date,
            },
            token=token,
        )
        outages = []
        for item in body.get("data") or []:
            outage = Outage.from_api(item, bill_id)
            if outage:
                outages.append(outage)
            else:
                logger.debug("skipping malformed outage entry: %r", item)
        return sorted(outages)

    async def account(self, *, token: str) -> tuple[list[dict], str | None]:
        body = await self._get(GET_BILLS_PATH, token=token)
        data = body.get("data")
        bills: list[dict] = []
        mobile: str | None = None
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    bills.extend(i for i in value if isinstance(i, dict))
            profile = data.get("user_data")
            if isinstance(profile, dict):
                raw = profile.get("mobile_number") or profile.get("mobile")
                if raw:
                    normalized = normalize_mobile(str(raw))
                    if MOBILE_RE.match(normalized):
                        mobile = normalized
        elif isinstance(data, list):
            bills.extend(i for i in data if isinstance(i, dict))
        return bills, mobile

    async def get_bills(self, *, token: str) -> list[dict]:
        bills, _ = await self.account(token=token)
        return bills

    async def providers(self) -> list[dict]:
        body = await self._get(PROVIDERS_PATH)
        return [i for i in (body.get("data") or []) if isinstance(i, dict)]

    async def cities(self, co_code: str) -> list[dict]:
        body = await self._get(f"{CITIES_PATH}?code={co_code}")
        return [i for i in (body.get("data") or []) if isinstance(i, dict)]

    async def search_branch(
        self,
        *,
        search_type: int,
        co_code: str | int,
        mobile_number: str = "",
        serial_number: str = "",
        city_code: str | int | None = None,
        phase: str | int | None = None,
        token: str | None = None,
    ) -> list[dict]:
        payload: dict = {
            "search_type": int(search_type),
            "co_code": _as_int(co_code),
            "city_code": _as_int(city_code),
            "phase": _as_int(phase),
            "file_serial_number": None,
            "subscription_id": None,
        }
        if mobile_number:
            payload["mobile_number"] = mobile_number
        if serial_number:
            payload["serial_number"] = latin_digits(serial_number).strip()
        body = await self._post(SEARCH_BRANCH_PATH, payload, token=token)
        return [i for i in (body.get("data") or []) if isinstance(i, dict)]


def _as_int(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(latin_digits(value).strip())
    except ValueError:
        return None


def _parse_response(resp: httpx.Response) -> dict:
    if resp.status_code == 401:
        raise SaapaAuthError("saapa token expired or invalid (401)")
    if resp.status_code != 200:
        raise SaapaError(f"HTTP {resp.status_code}{_detail(resp)}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise SaapaError("non-JSON response") from exc
    if body.get("status") != 200:
        raise SaapaRejected(f"api status {body.get('status')}: {body.get('message', 'unknown')}")
    return body


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f": {resp.text[:120]}"
    message = str(body.get("message") or "")
    errors = body.get("error")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        extra = str(errors[0].get("ErrorMsg") or "")
        if extra:
            message = f"{message} ({extra})" if message else extra
    return f": {message}" if message else ""
