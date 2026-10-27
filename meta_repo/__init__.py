"""Render repositories with embedded Python and shared memory."""

from .processor import ProcessingError, process_repository

__version__ = "0.1.0"
__all__ = ["ProcessingError", "process_repository"]
