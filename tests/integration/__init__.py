"""Qt integration tests that can run without a desktop."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
