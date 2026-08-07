def test_truncated_turn_stores_full_text(tmp_path):
    from memory.memory_service import MemoryService

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn(
        "s1",
        "assistant",
        "short visible",
        full_text="long full text that was truncated",
        truncated=True,
    )
    rows = svc.get_recent_turns("s1", limit=1)
    assert rows[0]["text"] == "short visible"
    assert rows[0]["full_text"] == "long full text that was truncated"
    assert rows[0]["truncated"] == 1


def test_truncated_flag_without_differing_full_text(tmp_path):
    from memory.memory_service import MemoryService

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn("s1", "assistant", "same text", truncated=True)
    rows = svc.get_recent_turns("s1", limit=1)
    assert rows[0]["text"] == "same text"
    assert rows[0]["full_text"] is None
    assert rows[0]["truncated"] == 1
