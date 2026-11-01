# oraculum/providers/__init__.py
"""Data providers owned by the Qwen handoff.

oraculum.providers.csv_provider builds a canonical ResearchBundle from a
supplied CSV price tape, a base ResearchBundle (identity, sources, non-daily
metrics) and an explicit exchange session calendar. Offline only: no network
access, no scraping, no AI or broker integration.
"""
__all__ = ["CsvResearchProvider"]


def __getattr__(name):
    # Keep the package import convenient without preloading the CLI module.
    if name == "CsvResearchProvider":
        from .csv_provider import CsvResearchProvider
        return CsvResearchProvider
    raise AttributeError(name)
