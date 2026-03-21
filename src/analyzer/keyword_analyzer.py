import logging
import re
from collections import Counter

from src.analyzer.protocols import ComplaintInfo

logger = logging.getLogger(__name__)

# Complaint categories with associated keywords/patterns
COMPLAINT_PATTERNS: dict[str, list[str]] = {
    "Чистота": [
        "грязно", "грязь", "грязный", "немытый", "пыль", "пыльно",
        "мусор", "антисанитария", "неубрано", "запах", "воняет", "вонь",
    ],
    "Персонал": [
        "хамство", "хамит", "грубость", "грубый", "грубо", "невежливо",
        "персонал", "сотрудник", "администратор", "аниматор",
        "невнимательн", "игнорир", "не помог", "не подошли",
        "некомпетент", "не следят", "не смотрят",
    ],
    "Безопасность": [
        "опасно", "травм", "ушиб", "порез", "сломан", "поломан",
        "безопасность", "небезопасно", "острый", "торчит", "опасн",
        "ребенок упал", "ребёнок упал",
    ],
    "Цена": [
        "дорого", "цена", "цены", "переплат", "завышен", "деньги",
        "стоимость", "не стоит", "обдираловка", "грабеж", "грабёж",
    ],
    "Оборудование": [
        "сломан", "не работает", "не функционир", "поломка",
        "старый", "изношен", "батут", "горка", "аттракцион",
        "неисправн", "не исправн",
    ],
    "Очереди и переполненность": [
        "очередь", "толпа", "много людей", "переполнен", "тесно",
        "битком", "не протолкнуться", "долго ждать", "ожидание",
    ],
    "Еда": [
        "еда", "кафе", "столовая", "невкусно", "холодное",
        "несвежий", "просрочен", "отравлен", "пицца", "торт",
        "меню", "перекус",
    ],
    "Вентиляция и температура": [
        "душно", "жарко", "холодно", "кондиционер", "вентиляция",
        "дышать нечем", "температура", "духота",
    ],
}


class KeywordComplaintAnalyzer:
    """Keyword-based complaint extractor implementing ReviewAnalyzerProtocol."""

    async def extract_complaints(self, reviews_texts: list[str]) -> list[ComplaintInfo]:
        category_hits: dict[str, Counter[str]] = {
            cat: Counter() for cat in COMPLAINT_PATTERNS
        }
        category_samples: dict[str, list[str]] = {
            cat: [] for cat in COMPLAINT_PATTERNS
        }

        for text in reviews_texts:
            if not text:
                continue
            text_lower = text.lower()

            for category, keywords in COMPLAINT_PATTERNS.items():
                for keyword in keywords:
                    if keyword in text_lower:
                        category_hits[category][keyword] += 1
                        if len(category_samples[category]) < 3:
                            # Store a short snippet
                            snippet = self._extract_snippet(text, keyword)
                            category_samples[category].append(snippet)

        results: list[ComplaintInfo] = []
        for category, counter in category_hits.items():
            total = sum(counter.values())
            if total == 0:
                continue

            # Top keyword in this category
            top_keyword = counter.most_common(1)[0][0]
            results.append(ComplaintInfo(
                keyword=top_keyword,
                category=category,
                count=total,
                sample_texts=category_samples[category],
            ))

        results.sort(key=lambda x: x.count, reverse=True)
        logger.info("Extracted %d complaint categories", len(results))
        return results

    @staticmethod
    def _extract_snippet(text: str, keyword: str, context_chars: int = 80) -> str:
        idx = text.lower().find(keyword)
        if idx == -1:
            return text[:150]
        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(keyword) + context_chars)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet
