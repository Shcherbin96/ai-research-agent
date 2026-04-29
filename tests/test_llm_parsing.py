import pytest

from research_agent.llm import extract_json_tag


def test_extracts_from_json_tags():
    raw = 'preamble <json>{"subqueries": ["a", "b"]}</json> trailing'
    assert extract_json_tag(raw) == {"subqueries": ["a", "b"]}


def test_falls_back_to_first_object():
    raw = 'no tags here, but {"k": 1, "v": [2, 3]} appears'
    assert extract_json_tag(raw) == {"k": 1, "v": [2, 3]}


def test_falls_back_to_array():
    raw = "some text [1, 2, 3]"
    assert extract_json_tag(raw) == [1, 2, 3]


def test_raises_on_garbage():
    with pytest.raises(ValueError):
        extract_json_tag("totally not json")
