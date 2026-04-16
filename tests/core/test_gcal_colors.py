from src.gcal_colors import GCAL_COLOR_NAMES, GCAL_COLOR_IDS


def test_all_11_colors_present():
    expected = {"Lavender", "Sage", "Grape", "Flamingo", "Banana",
                "Tangerine", "Peacock", "Blueberry", "Basil", "Tomato", "Avocado"}
    assert set(GCAL_COLOR_NAMES.values()) == expected
    assert len(GCAL_COLOR_NAMES) == 11


def test_ids_are_string_integers_1_to_11():
    assert set(GCAL_COLOR_NAMES.keys()) == {str(i) for i in range(1, 12)}


def test_color_ids_is_inverse_of_color_names():
    for cid, name in GCAL_COLOR_NAMES.items():
        assert GCAL_COLOR_IDS[name] == cid


def test_lookup_flamingo_by_id():
    assert GCAL_COLOR_NAMES["4"] == "Flamingo"


def test_lookup_flamingo_by_name():
    assert GCAL_COLOR_IDS["Flamingo"] == "4"
