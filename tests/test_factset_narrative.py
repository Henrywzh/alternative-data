from __future__ import annotations

from factset_earnings_data.narrative import parse_article_narrative


REVISION_TEXT = """
Given concerns in the market about higher oil and gas prices, have analysts lowered EPS estimates more than normal for S&P 500 companies for the third quarter?
The answer is no. During the months of July and August, analysts increased EPS estimates in aggregate for the third quarter. The Q3 bottom-up EPS estimate increased by 1.2% (to $89.69 from $88.64) from June 30 to August 31.
In a typical quarter, analysts usually reduce earnings estimates during the first two months of a quarter. During the past five years (20 quarters), the average decline in the bottom-up EPS estimate during the first two months of a quarter has been 1.7%. During the past ten years, (40 quarters), the average decline in the bottom-up EPS estimate during the first two months of a quarter has been 2.1%. During the past fifteen years, (60 quarters), the average decline in the bottom-up EPS estimate during the first two months of a quarter has been 2.6%. During the past 20 years (80 quarters), the average decline in the bottom-up EPS estimate during the first two months of a quarter has been 3.1%.
At the sector level, four of the eleven sectors witnessed an increase in their bottom-up EPS estimate for Q3 2026 from June 30 to August 31, led by the Energy (+11.8%) sector. On the other hand, seven sectors recorded a decrease in their bottom-up EPS estimate for Q3 2026 during this period, led by the Materials (-9.1%) sector.
This blog post is for informational purposes only.
"""


def test_parse_article_narrative_extracts_question_typical_history_and_breadth() -> None:
    parsed = parse_article_narrative(REVISION_TEXT)
    assert parsed is not None
    assert parsed["question"].startswith("Given concerns in the market about higher oil and gas prices")
    assert parsed["answer"] == "no"
    assert parsed["answer_sentence"].startswith("The answer is no.")
    assert parsed["window"] == "June 30 to August 31"
    assert [item["years"] for item in parsed["typical"]] == [5, 10, 15, 20]
    assert [item["value"] for item in parsed["typical"]] == [-1.7, -2.1, -2.6, -3.1]
    assert parsed["breadth"]["up_count"] == 4
    assert parsed["breadth"]["down_count"] == 7
    assert parsed["breadth"]["led_up"] == ["Energy"]
    assert parsed["breadth"]["led_down"] == ["Materials"]


def test_parse_article_narrative_returns_none_without_factset_question() -> None:
    assert parse_article_narrative("Energy rose and Materials fell this week.") is None
