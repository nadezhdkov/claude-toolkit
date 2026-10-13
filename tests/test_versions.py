import pytest

from claude_toolkit import pep440, semver


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ((24, 18, 0), "24.18.0", True),
        ((24, 18, 1), "24.18.0", False),
        ((24, 3, 0), "24", True),
        ((26, 11, 1), "24", False),
        ((22, 19, 0), ">=22.19 <23 || ^24.11 || >=26", True),
        ((23, 0, 0), ">=22.19 <23 || ^24.11 || >=26", False),
        ((24, 11, 0), "^24.11", True),
        ((25, 0, 0), "^24.11", False),
        ((0, 2, 5), "^0.2.3", True),
        ((0, 3, 0), "^0.2.3", False),
        ((1, 2, 9), "~1.2.3", True),
        ((1, 3, 0), "~1.2.3", False),
        ((18, 0, 0), ">= 18", True),
        ((20, 1, 0), "20.x", True),
        ((21, 0, 0), "20.x", False),
        ((99, 0, 0), "lts/*", True),
    ],
)
def test_npm_ranges(version, spec, expected):
    assert semver.satisfies(version, spec) is expected


def test_npm_unsupported_range_is_reported_not_guessed():
    with pytest.raises(semver.UnsupportedRange):
        semver.satisfies((1, 0, 0), "1.0.0 - 2.0.0")


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ((3, 12, 4), ">=3.11", True),
        ((3, 10, 9), ">=3.11", False),
        ((3, 13, 0), ">=3.11,<3.14", True),
        ((3, 14, 0), ">=3.11,<3.14", False),
        ((3, 12, 1), "~=3.12", True),
        ((4, 0, 0), "~=3.12", False),
        ((3, 12, 7), "==3.12.*", True),
        ((3, 13, 0), "==3.12.*", False),
        ((3, 12, 0), "!=3.12.*", False),
    ],
)
def test_pep440_specifiers(version, spec, expected):
    assert pep440.satisfies(version, spec) is expected
