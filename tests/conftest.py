import sys

import pytest

# Fake external tools in these tests are `#!/bin/sh` scripts, which Windows cannot run.
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="fake tools are sh scripts")
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only feature")
