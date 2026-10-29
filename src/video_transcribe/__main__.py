import sys

from . import paths  # noqa: F401  - must run first: points all caches into the project
from .cli import main

sys.exit(main())
