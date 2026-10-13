#!/usr/bin/env bash
# weatherkit 3.1 is installed; legacy.py still calls the 2.x API removed in 3.0.
set -euo pipefail
python3 -m venv --without-pip .venv
site=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
mkdir -p "$site/weatherkit" "$site/weatherkit-3.1.0.dist-info"
cat > "$site/weatherkit/__init__.py" <<'EOF'
"""weatherkit 3: forecasts as objects. The 2.x function API was removed in 3.0."""

from ._forecast import Forecast, Units

__all__ = ["Forecast", "Units"]
__version__ = "3.1.0"
EOF
cat > "$site/weatherkit/_forecast.py" <<'EOF'
from __future__ import annotations

import enum

_READINGS = {"lisbon": 21.5, "porto": 18.0, "faro": 24.25}


class Units(enum.Enum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class Forecast:
    """Today's forecast for one city."""

    def __init__(self, city: str, celsius: float, units: Units):
        self.city = city
        self._celsius = celsius
        self.units = units

    @classmethod
    def for_city(cls, city: str, *, units: Units = Units.METRIC) -> Forecast:
        """Look up today's forecast for ``city``."""
        try:
            return cls(city, _READINGS[city.lower()], units)
        except KeyError:
            raise LookupError(f"no forecast for {city!r}") from None

    @property
    def temperature(self) -> float:
        """Temperature in the forecast's units (Celsius for METRIC)."""
        return self._celsius if self.units is Units.METRIC else self._celsius * 9 / 5 + 32
EOF
cat > "$site/weatherkit-3.1.0.dist-info/METADATA" <<'EOF'
Metadata-Version: 2.1
Name: weatherkit
Version: 3.1.0
Summary: Tiny weather forecasts

# weatherkit

## Quick start (3.x)

    from weatherkit import Forecast
    print(Forecast.for_city("Porto").temperature)

## Migrating from 2.x

`get_forecast(city)["temp"]` was removed in 3.0.
EOF
echo weatherkit > "$site/weatherkit-3.1.0.dist-info/top_level.txt"
cat > pyproject.toml <<'EOF'
[project]
name = "dashboard"
version = "1.0.0"
dependencies = ["weatherkit>=3.0"]
EOF
cat > legacy.py <<'EOF'
"""Old dashboard (written against weatherkit 2.x)."""
import sys

import weatherkit


def show(city):
    data = weatherkit.get_forecast(city)
    return f"{city}: {data['temp']} °C"


if __name__ == "__main__":
    print(show(sys.argv[1]))
EOF
