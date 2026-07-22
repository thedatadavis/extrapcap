from __future__ import annotations


def merge_pages(pages: list[dict], collection_key: str) -> dict:
    """Merge API pages while preserving metadata and rejecting inconsistent payloads."""
    if not pages:
        return {collection_key: []}
    merged = dict(pages[0])
    merged.pop("next_page_token", None)
    if collection_key == "snapshots":
        values = {}
        for page in pages:
            values.update(page.get(collection_key, {}))
    else:
        values = [item for page in pages for item in page.get(collection_key, [])]
    merged[collection_key] = values
    merged["page_count"] = len(pages)
    return merged
