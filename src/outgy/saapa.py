import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import jdatetime

logger = logging.getLogger(__name__)

PLANNED_BLACKOUTS_PATH = "/api/ebills/PlannedBlackoutsReport"
OTP_SEND_PATH = "/api/otp/sendCode"
OTP_VERIFY_PATH = "/api/otp/verifyCode"
GET_BILLS_PATH = "/api/ebills/GetBills"
SEARCH_BRANCH_PATH = "/api/ebills/SearchBranchData"
PROVIDERS_PATH = "/api/providers/list"
CITIES_PATH = "/api/providers/cities"
TEHRAN = ZoneInfo("Asia/Tehran")

_DATE_RE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
BILL_ID_RE = re.compile(r"^\d{8,18}$")
MOBILE_RE = re.compile(r"^09\d{9}$")
OTP_CODE_RE = re.compile(r"^\d{4,8}$")

_DIGITS_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class SaapaError(RuntimeError):
    pass


class SaapaRejected(SaapaError):
    pass


class SaapaAuthError(SaapaError):
    pass


def to_latin_digits(text: str) -> str:
    return text.translate(_DIGITS_FA)


def normalize_mobile(raw: str) -> str:
    s = re.sub(r"[^\d+]", "", to_latin_digits(raw).strip())
    if s.startswith("+98"):
        s = "0" + s[3:]
    elif s.startswith("0098"):
        s = "0" + s[4:]
    if len(s) == 10 and s.startswith("9"):
        s = "0" + s
    return s


@dataclass(frozen=True)
class Outage:
    bill_id: str
    date: str
    start_time: str
    stop_time: str
    address: str
    number: str

    @property
    def key(self) -> str:
        return f"{self.date}|{self.start_time}|{self.stop_time}|{self.number}"

    @property
    def sort_key(self) -> tuple[int, ...]:
        y, m, d = (int(p) for p in self.date.split("/"))
        h, minute = (int(p) for p in self.start_time.split(":"))
        return (y, m, d, h, minute)


def today_jalali() -> jdatetime.date:
    now = datetime.now(TEHRAN)
    return jdatetime.date.fromgregorian(date=now.date())


def _fmt_jdate(d: jdatetime.date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def jalali_window(days: int) -> tuple[str, str]:
    today = today_jalali()
    end = today + jdatetime.timedelta(days=days)
    return _fmt_jdate(today), _fmt_jdate(end)


def _parse_response(resp: httpx.Response) -> dict:
    if resp.status_code == 401:
        raise SaapaAuthError("saapa token expired or invalid (401)")
    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json()
            msg = str(body.get("message") or "")
            errors = body.get("error")
            if isinstance(errors, list) and errors:
                extra = errors[0].get("ErrorMsg") if isinstance(errors[0], dict) else None
                if extra:
                    msg = f"{msg} ({extra})" if msg else str(extra)
            detail = f": {msg}" if msg else ""
        except ValueError:
            detail = f": {resp.text[:120]}"
        raise SaapaError(f"HTTP {resp.status_code}{detail}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise SaapaError("non-JSON response") from exc
    if body.get("status") != 200:
        raise SaapaRejected(f"api status {body.get('status')}: {body.get('message', 'unknown')}")
    return body


_BILL_ID_KEYS = ("bill_identifier", "bill_id", "BillId", "billID")
_BILL_LABEL_KEYS = ("address", "outage_address", "subscription_id", "name")


def extract_bill_id(item: dict) -> str | None:
    for key in _BILL_ID_KEYS:
        value = item.get(key)
        if value and BILL_ID_RE.match(to_latin_digits(str(value)).strip()):
            return to_latin_digits(str(value)).strip()
    return None


def bill_label(item: dict) -> str:
    for key in _BILL_LABEL_KEYS:
        value = item.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return ""


_NAME_CLEAN_RE = re.compile(r"[\s\u200c\u0640]+")
_ARABIC_MAP = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "ؤ": "و"})


def normalize_name(text: str) -> str:
    s = to_latin_digits(text).translate(_ARABIC_MAP)
    s = _NAME_CLEAN_RE.sub("", s).lower()
    for word in ("استان", "شرکت", "توزیع", "منطقه", "برق"):
        s = s.replace(word, "")
    return s.strip("-_")


def provider_code(p: dict) -> str:
    return str(p.get("code") or p.get("id") or p.get("co_code") or "")


def provider_name(p: dict) -> str:
    return str(p.get("name") or p.get("title") or "")


def match_providers(providers: list[dict], needle: str) -> list[dict]:
    q = normalize_name(needle)
    matches = []
    for p in providers:
        name = normalize_name(provider_name(p))
        code = provider_code(p)
        if not name and not code:
            continue
        if q == name or (q and q in name) or q == code:
            matches.append(p)
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
        from_date, to_date = jalali_window(days)
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
            date = item.get("outage_date", "")
            start = item.get("outage_start_time", "")
            stop = item.get("outage_stop_time", "")
            address = (item.get("address") or "").strip()
            number = str(item.get("outage_number") or "")
            if not (_DATE_RE.match(date) and _TIME_RE.match(start) and _TIME_RE.match(stop)):
                logger.debug("skipping malformed outage entry: %r", item)
                continue
            outages.append(
                Outage(
                    bill_id=bill_id,
                    date=date,
                    start_time=start,
                    stop_time=stop,
                    address=address,
                    number=number,
                )
            )
        outages.sort(key=lambda o: o.sort_key)
        return outages

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
        def _int(value: str | int | None) -> int | None:
            if value is None or value == "":
                return None
            try:
                return int(to_latin_digits(str(value)).strip())
            except ValueError:
                return None

        payload: dict = {
            "search_type": int(search_type),
            "co_code": _int(co_code),
            "city_code": _int(city_code),
            "phase": _int(phase),
            "file_serial_number": None,
            "subscription_id": None,
        }
        if mobile_number:
            payload["mobile_number"] = mobile_number
        if serial_number:
            payload["serial_number"] = to_latin_digits(serial_number).strip()
        body = await self._post(SEARCH_BRANCH_PATH, payload, token=token)
        return [i for i in (body.get("data") or []) if isinstance(i, dict)]
