"""Metadata enrichment (e.g. Crossref DOI lookup)."""

from app.services.metadata.crossref_client import fetch_crossref_metadata

__all__ = ["fetch_crossref_metadata"]
