import sys
from pathlib import Path

# Make tests/timing_harness.py importable and make sure the package's
# local-cache environment is applied before anything else is imported.
sys.path.insert(0, str(Path(__file__).parent))
import video_transcribe.paths  # noqa: E402,F401
