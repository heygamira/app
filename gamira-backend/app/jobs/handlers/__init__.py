"""Importing this package registers every job handler.

Split by dependency, not by feature: ``care`` needs nothing but the database,
``ai`` needs a model provider. A worker with a broken AI configuration still
runs every handler in ``care``.
"""

from app.jobs.handlers import ai, care

__all__ = ["ai", "care"]
