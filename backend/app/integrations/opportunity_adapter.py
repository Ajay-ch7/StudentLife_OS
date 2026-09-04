from abc import ABC, abstractmethod
from typing import Any


class OpportunityAdapter(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError


class CuratedOpportunityAdapter(OpportunityAdapter):
    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        items = [
            {"title": "Backend Engineering Intern", "company": "Stripe", "description": "Build APIs with Python and SQL.", "required_skills": ["Python", "SQL", "FastAPI"], "source": "curated"},
            {"title": "Cloud Platform Intern", "company": "Google", "description": "Work on distributed infrastructure.", "required_skills": ["Python", "Algorithms", "Kubernetes"], "source": "curated"},
        ]
        query = query.lower()
        return [item for item in items if query in item["title"].lower() or query in item["description"].lower()][:limit]
