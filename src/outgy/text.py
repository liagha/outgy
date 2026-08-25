import re

_TO_LATIN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def latin_digits(value: str | int) -> str:
    return str(value).translate(_TO_LATIN)


def persian_digits(value: str | int) -> str:
    return str(value).translate(_TO_PERSIAN)


def digits_only(value: str | int) -> str:
    return re.sub(r"\D", "", latin_digits(value))
