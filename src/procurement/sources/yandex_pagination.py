"""Продолжение из публичного HTML: только JSON-данные, без исполнения JS."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from procurement.sources.catalog_routes import CategoryRoute, has_next_category_page

PAGINATION_POLICY: Literal["CATEGORY_LINK_OR_STATE_V1"] = "CATEGORY_LINK_OR_STATE_V1"


class PaginationError(ValueError):
    """Неоднозначные данные не разрешают принять страницу или перейти дальше."""


@dataclass(frozen=True)
class CategoryContinuation:
    status: Literal["NEXT_PAGE", "END_REPORTED", "UNKNOWN"]
    evidence: Literal["LINK", "PAGE_STATE", "LINK_AND_PAGE_STATE"] | None = None
    locator: str | None = None


class _Patches(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inside = False
        self.parts: list[str] = []
        self.patches: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "noframes" and dict(attrs).get("data-apiary") == "patch":
            if self.inside:
                raise PaginationError("PAGINATION_STATE_INVALID")
            self.inside = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "noframes" and self.inside:
            self.patches.append("".join(self.parts))
            self.inside = False


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PaginationError("PAGINATION_STATE_INVALID")
        result[key] = value
    return result


def category_continuation(
    content: bytes, route: CategoryRoute, number: int
) -> CategoryContinuation:
    """Состояние связано с точными категорией и страницей; внешние URL не берутся."""
    parser = _Patches()
    try:
        if not 0 < len(content) <= 3 * 1024 * 1024:
            raise PaginationError("PAGINATION_STATE_INVALID")
        parser.feed(content.decode("utf-8"))
        parser.close()
        if parser.inside:
            raise PaginationError("PAGINATION_STATE_INVALID")
        states: list[tuple[dict[str, object], str]] = []
        for index, patch in enumerate(parser.patches, 1):
            if '"visibleSearchResult"' not in patch:
                continue
            payload = json.loads(patch, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise PaginationError("PAGINATION_STATE_INVALID")
            collections = payload.get("collections", {})
            if not isinstance(collections, dict):
                raise PaginationError("PAGINATION_STATE_INVALID")
            if "visibleSearchResult" not in collections:
                continue
            results = collections["visibleSearchResult"]
            if results == {}:
                continue  # Штатная пустая инициализация до populated patch.
            if not isinstance(results, dict) or len(results) != 1:
                raise PaginationError("PAGINATION_STATE_INVALID")
            key, state = next(iter(results.items()))
            if (
                not isinstance(state, dict)
                or state.get("id") != key
                or state.get("entity") != "visibleSearchResult"
            ):
                raise PaginationError("PAGINATION_STATE_INVALID")
            states.append(
                (state, f"noframes[data-apiary=patch] #{index}/collections/visibleSearchResult")
            )
        if len(states) > 1:
            raise PaginationError("PAGINATION_STATE_INVALID")
        link = has_next_category_page(content, route, number)
        if not states:
            return (
                CategoryContinuation("NEXT_PAGE", "LINK", "a/link[href]")
                if link
                else (CategoryContinuation("UNKNOWN"))
            )
        state, locator = states[0]
        hids = state.get("hids")
        page = state.get("page")
        count = state.get("pageCount")
        size = state.get("itemsPerPage")
        more = state.get("hasNextPage")
        result_ids = state.get("searchResultIds")
        if (
            not isinstance(hids, list)
            or len(hids) != 1
            or type(hids[0]) is not int
            or hids[0] != int(route.hid)
            or type(page) is not int
            or page != number
            or type(count) is not int
            or not number <= count <= 100_000
            or type(size) is not int
            or not 1 <= size <= 100
            or type(more) is not bool
            or more != (number < count)
            or state.get("currentPageIds") != [str(number)]
            or not isinstance(result_ids, dict)
            or not isinstance(result_ids.get(str(number)), str)
            or not result_ids[str(number)]
            or (link and not more)
        ):
            raise PaginationError("PAGINATION_STATE_INVALID")
        return CategoryContinuation(
            "NEXT_PAGE" if more else "END_REPORTED",
            "LINK_AND_PAGE_STATE" if link else "PAGE_STATE",
            locator,
        )
    except (ValueError, TypeError, RecursionError) as error:
        raise PaginationError("PAGINATION_STATE_INVALID") from error
