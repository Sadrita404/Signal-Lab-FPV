"""interflab: patchable interference generator (standalone; analogfpv can plug it in later)."""
from .engine import Engine
from .patch import MAX_SOURCES, MOD_TARGETS, SOURCE_SCHEMA, Patch, new_source
from .wave import WAVES
