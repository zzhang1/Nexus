from nexus_ai.core.markdown import ensure_minimal_front_matter, split_front_matter


def test_front_matter_roundtrip():
    md = ensure_minimal_front_matter("Hello world", doc_type="note", title="Test")
    parsed = split_front_matter(md)
    assert parsed.front_matter["type"] == "note"
    assert parsed.front_matter["title"] == "Test"
    assert parsed.front_matter["status"] == "active"
    assert "created" in parsed.front_matter
    assert "updated" in parsed.front_matter
    assert parsed.body.strip() == "Hello world"

