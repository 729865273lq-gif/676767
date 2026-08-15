from __future__ import annotations

from typing import Protocol

from app.agents.base.contracts import SearchResult
from app.connectors.base import Connector
from app.connectors.search.bocha import BochaSearchConnector, BochaSearchError
from app.connectors.search.geoapify import GeoapifySearchConnector, GeoapifySearchError
from app.connectors.search.foursquare import FoursquareSearchConnector, FoursquareSearchError
from app.connectors.search.google_cse import (
    GoogleProgrammableSearchConnector,
    GoogleProgrammableSearchError,
)
from app.connectors.search.google_places import GooglePlacesSearchConnector, GooglePlacesSearchError
from app.connectors.search.multi import MultiSearchConnector, MultiSearchError
from app.connectors.search.openstreetmap import OpenStreetMapSearchConnector, OpenStreetMapSearchError
from app.connectors.search.tomtom import TomTomSearchConnector, TomTomSearchError


class SearchConnector(Connector, Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


__all__ = [
    "BochaSearchConnector",
    "BochaSearchError",
    "GeoapifySearchConnector",
    "GeoapifySearchError",
    "FoursquareSearchConnector",
    "FoursquareSearchError",
    "GoogleProgrammableSearchConnector",
    "GoogleProgrammableSearchError",
    "GooglePlacesSearchConnector",
    "GooglePlacesSearchError",
    "MultiSearchConnector",
    "MultiSearchError",
    "OpenStreetMapSearchConnector",
    "OpenStreetMapSearchError",
    "SearchConnector",
    "TomTomSearchConnector",
    "TomTomSearchError",
]
