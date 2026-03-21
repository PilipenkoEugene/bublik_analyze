from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ComplaintInfo:
    """Extracted complaint with category and frequency."""
    keyword: str
    category: str
    count: int
    sample_texts: list[str]


@runtime_checkable
class ReviewAnalyzerProtocol(Protocol):
    """Protocol for review analysis.

    Implement this to switch between keyword-based and LLM-based analysis.
    """

    async def extract_complaints(self, reviews_texts: list[str]) -> list[ComplaintInfo]:
        """Extract and categorize complaints from review texts."""
        ...
