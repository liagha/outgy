from outgy.text import digits_only, latin_digits, persian_digits


def test_latin_digits_converts_persian_and_arabic():
    assert latin_digits("۱۴۰۵/۰۶/۰۳") == "1405/06/03"
    assert latin_digits("١٢٣") == "123"


def test_latin_digits_keeps_ascii():
    assert latin_digits("16:00-18:00") == "16:00-18:00"


def test_persian_digits_roundtrip():
    assert persian_digits(latin_digits("۴۰۰۰۰۱۱۱۱۱۱۱")) == "۴۰۰۰۰۱۱۱۱۱۱۱"


def test_persian_digits_only_touches_numbers():
    assert persian_digits("code 400001111111") == "code ۴۰۰۰۰۱۱۱۱۱۱۱"


def test_digits_only_strips_everything_else():
    assert digits_only("۰۹۱۲ 345-6789") == "09123456789"
