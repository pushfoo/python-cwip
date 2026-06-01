import pytest

from cwip import parse_version, MajorMinorPatchVersion


@pytest.mark.parametrize("raw_string,expected", [
    ("9.99.999alphanumeric", MajorMinorPatchVersion(9, 99, 999, "alphanumeric")),
    ("1", MajorMinorPatchVersion(1, 0, 0)),
    ("9.1", MajorMinorPatchVersion(9, 1, 0)),
    ("10.1.2", MajorMinorPatchVersion(10, 1, 2))
])
def test_parse_version_returns_expected_version_for_default_version_pattern(
    raw_string,
    expected,
):
    result = parse_version(raw_string)
    assert result == expected


@pytest.fixture(params=[0xBAD_D47A, b'bad data', ("bad", "data")])
def not_a_string_type(request):
    return request.param


def test_parse_version_raises_type_error_for_nonstring_values(not_a_string_type):
    with pytest.raises(TypeError):
        _ = parse_version(not_a_string_type)


def test_parse_version_raises_value_error_for_empty_string():
    with pytest.raises(ValueError):
        _ = parse_version('')
