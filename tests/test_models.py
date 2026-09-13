import pytest
from pydantic import ValidationError

from grok_search_mcp.models import SearchOptions


@pytest.mark.parametrize(
    "values",
    [
        {"query": "  "},
        {"allowed_domains": ["a.com"], "excluded_domains": ["b.com"]},
        {"allowed_domains": ["https://a.com"]},
        {"allowed_domains": [f"a{i}.com" for i in range(6)]},
        {"allowed_x_handles": ["a"], "excluded_x_handles": ["b"]},
        {"allowed_x_handles": ["not a handle"]},
        {"from_date": "bad date"},
        {"from_date": "2026-09-12", "to_date": "2026-09-01"},
        {"include_x": False, "from_date": "2026-09-12"},
        {"max_cost_usd": float("nan")},
        {"timeout_seconds": float("inf")},
        {"max_rounds": 5},
        {"model": "another-provider"},
    ],
)
def test_invalid_request(values):
    with pytest.raises(ValidationError):
        SearchOptions.model_validate({"query": "test", **values})


def test_dates_and_filter_normalization():
    options = SearchOptions(
        query=" q ", allowed_domains=["Docs.Example.COM."], from_date="2026-09-12T00:00:00-05:00"
    )
    assert options.query == "q" and options.allowed_domains == ["docs.example.com"]
    assert options.from_date.hour == 5 and options.from_date.utcoffset().total_seconds() == 0
