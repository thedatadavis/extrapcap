from extrapcap.data.pagination import merge_pages


def test_pagination_merges_lists_and_snapshot_maps():
    assert merge_pages([{"bars": [1]}, {"bars": [2]}], "bars")["bars"] == [1, 2]
    merged = merge_pages([{"snapshots": {"A": {"p": 1}}}, {"snapshots": {"B": {"p": 2}}}], "snapshots")
    assert set(merged["snapshots"]) == {"A", "B"}
    assert merged["page_count"] == 2
