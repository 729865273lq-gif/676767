from app.platform.search_keywords import country_to_language


def test_country_to_language_maps_iso2_codes_case_insensitively() -> None:
    assert country_to_language("de") == "de"
    assert country_to_language("DE") == "de"
    assert country_to_language("br") == "pt"
    assert country_to_language("pt") == "pt"
    assert country_to_language("us") == "en"
    assert country_to_language("gb") == "en"
    assert country_to_language("au") == "en"
    assert country_to_language("ca") == "en"
    assert country_to_language("za") == "en"
    assert country_to_language("in") == "en"
    assert country_to_language("jp") == "ja"
    assert country_to_language("kr") == "ko"
    assert country_to_language("vn") == "vi"
    assert country_to_language("mx") == "es"
    assert country_to_language("ar") == "ar"


def test_country_to_language_accepts_common_country_names() -> None:
    assert country_to_language("Germany") == "de"
    assert country_to_language("germany") == "de"
    assert country_to_language("Brazil") == "pt"
    assert country_to_language("Vietnam") == "vi"
    assert country_to_language("Spain") == "es"
    assert country_to_language("United States") == "en"
    assert country_to_language("Turkey") == "tr"
    assert country_to_language("South Korea") == "ko"


def test_country_to_language_accepts_chinese_country_names() -> None:
    assert country_to_language("德国") == "de"
    assert country_to_language("越南") == "vi"
    assert country_to_language("日本") == "ja"
    assert country_to_language("韩国") == "ko"
    assert country_to_language("巴西") == "pt"


def test_country_to_language_falls_back_to_english() -> None:
    assert country_to_language("xx") == "en"
    assert country_to_language("") == "en"
    assert country_to_language("Somewhere Unknown") == "en"
