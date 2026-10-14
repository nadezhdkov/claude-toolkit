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
        # Partial versions with > and <= cover the whole partial range, as in npm.
        ((1, 2, 1), ">1.2", False),
        ((1, 3, 0), ">1.2", True),
        ((1, 2, 5), "<=1.2", True),
        ((1, 3, 0), "<=1.2", False),
        ((1, 9, 9), ">1", False),
        ((2, 0, 0), ">1", True),
        ((1, 9, 9), "<=1", True),
        ((2, 0, 0), "<=1", False),
        ((1, 5, 0), ">1.x", False),
        ((2, 0, 0), ">1.x", True),
        ((1, 2, 7), "<=1.2.x", True),
        ((1, 3, 0), "<=1.2.x", False),
        ((1, 1, 9), ">=1.2", False),
        ((1, 2, 0), ">=1.2", True),
        ((1, 2, 9), "<1.2", False),
        ((1, 1, 9), "<1.2", True),
        ((1, 2, 4), ">1.2.3", True),
        ((1, 2, 4), "<=1.2.3", False),
        # npm hyphen ranges: partial lower bound pads with zeros (>=1.2.0 <=2.3.4)
        ((1, 2, 0), "1.2 - 2.3.4", True),
        ((2, 3, 4), "1.2 - 2.3.4", True),
        ((1, 1, 9), "1.2 - 2.3.4", False),
        ((2, 3, 5), "1.2 - 2.3.4", False),
        # partial upper bound exclusive of next increment (>=1.2.3 <2.4.0)
        ((1, 2, 3), "1.2.3 - 2.3", True),
        ((2, 3, 9), "1.2.3 - 2.3", True),
        ((1, 2, 2), "1.2.3 - 2.3", False),
        ((2, 4, 0), "1.2.3 - 2.3", False),
        # partial upper bound with only major exclusive of next increment (>=1.2.3 <3.0.0)
        ((1, 2, 3), "1.2.3 - 2", True),
        ((2, 9, 9), "1.2.3 - 2", True),
        ((1, 2, 2), "1.2.3 - 2", False),
        ((3, 0, 0), "1.2.3 - 2", False),
        # fully-specified hyphen range (>=1.2.3 <=2.3.4)
        ((1, 2, 3), "1.2.3 - 2.3.4", True),
        ((2, 3, 4), "1.2.3 - 2.3.4", True),
        ((1, 2, 2), "1.2.3 - 2.3.4", False),
        ((2, 3, 5), "1.2.3 - 2.3.4", False),
        # partial bounds on both ends (>=18.0.0 <21.0.0)
        ((18, 0, 0), "18 - 20", True),
        ((20, 9, 0), "18 - 20", True),
        ((17, 9, 9), "18 - 20", False),
        ((21, 0, 0), "18 - 20", False),
        # hyphen ranges combined with ||
        ((18, 0, 0), "^14 || 18 - 20", True),
        ((14, 5, 0), "^14 || 18 - 20", True),
        ((16, 0, 0), "^14 || 18 - 20", False),
        ((21, 0, 0), "^14 || 18 - 20", False),
        ((1, 5, 0), "1.0.0 - 2.0.0 || 3.0.0 - 4.0.0", True),
        ((3, 5, 0), "1.0.0 - 2.0.0 || 3.0.0 - 4.0.0", True),
        ((2, 5, 0), "1.0.0 - 2.0.0 || 3.0.0 - 4.0.0", False),
    ],
)
def test_npm_ranges(version, spec, expected):
    assert semver.satisfies(version, spec) is expected


@pytest.mark.parametrize(
    "spec",
    [
        "1.2 -",
        "- 2",
        "-",
        "1.2 - - 2.3",
        "1.2 - 2.3 - 3.4",
        ">=1.2 - 2.3",
        "1.2 - <=2.3",
        "1.2 - || ^14",
    ],
)
def test_npm_unsupported_range_is_reported_not_guessed(spec):
    with pytest.raises(semver.UnsupportedRange):
        semver.satisfies((1, 0, 0), spec)


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
