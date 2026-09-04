import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
DEFAULT_TIMEOUT = 15.0


class LeetCodeQueryClient:
    """
    Client for querying public LeetCode GraphQL endpoints for profile statistics,
    recent accepted submissions, and problem details.
    """

    def __init__(self, endpoint_url: str = LEETCODE_GRAPHQL_URL, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.endpoint_url = endpoint_url
        self.timeout = timeout
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StudentLifeOS/1.0",
            "Referer": "https://leetcode.com",
        }

    async def _post_graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute GraphQL POST request with timeout and error handling."""
        payload = {"query": query, "variables": variables}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.endpoint_url, json=payload, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                if "errors" in data and not data.get("data"):
                    logger.warning("LeetCode GraphQL query returned errors: %s", data["errors"])
                    return {}
                return data.get("data", {})
        except Exception as err:
            logger.error("LeetCode query request failed: %s", err)
            return {}

    async def fetch_user_profile(self, username: str) -> dict[str, Any]:
        """Fetch total problems solved, difficulty breakdown, streak, active days, and ranking for a given LeetCode username."""
        query = """
        query userProfileDetailed($username: String!) {
          matchedUser(username: $username) {
            username
            userCalendar {
              streak
              totalActiveDays
            }
            profile {
              ranking
              reputation
            }
            submitStatsGlobal {
              acSubmissionNum {
                difficulty
                count
              }
            }
            submitStats {
              acSubmissionNum {
                difficulty
                count
              }
            }
          }
        }
        """
        data = await self._post_graphql(query, {"username": username})
        matched_user = data.get("matchedUser")
        if not matched_user:
            logger.warning("LeetCode profile for '%s' not found or empty response.", username)
            return {
                "username": username,
                "found": False,
                "total_solved": 0,
                "easy": 0,
                "medium": 0,
                "hard": 0,
                "streak": 0,
                "active_days": 0,
                "ranking": None,
            }

        stats_container = matched_user.get("submitStatsGlobal") or matched_user.get("submitStats") or {}
        ac_num = stats_container.get("acSubmissionNum") or []

        counts = {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0}
        for item in ac_num:
            diff = item.get("difficulty")
            count = item.get("count", 0)
            if diff in counts:
                counts[diff] = count

        calendar = matched_user.get("userCalendar") or {}
        profile_info = matched_user.get("profile") or {}

        return {
            "username": username,
            "found": True,
            "total_solved": counts["All"],
            "easy": counts["Easy"],
            "medium": counts["Medium"],
            "hard": counts["Hard"],
            "streak": calendar.get("streak", 0),
            "active_days": calendar.get("totalActiveDays", 0),
            "ranking": profile_info.get("ranking"),
        }

    async def fetch_recent_ac_submissions(self, username: str, limit: int = 15) -> list[dict[str, Any]]:
        """Fetch recent accepted submissions for a given username."""
        query = """
        query recentAcSubmissions($username: String!, $limit: Int!) {
          recentAcSubmissionList(username: $username, limit: $limit) {
            id
            title
            titleSlug
            timestamp
          }
        }
        """
        data = await self._post_graphql(query, {"username": username, "limit": limit})
        submissions = data.get("recentAcSubmissionList")
        if not isinstance(submissions, list):
            return []

        formatted = []
        for item in submissions:
            formatted.append({
                "submission_id": str(item.get("id") or item.get("timestamp")),
                "title": item.get("title", "Untitled Problem"),
                "title_slug": item.get("titleSlug", ""),
                "timestamp": int(item.get("timestamp") or 0),
            })
        return formatted

    async def fetch_problem_details(self, title_slug: str) -> dict[str, Any]:
        """Fetch difficulty and topic tags for a problem given its title slug."""
        if not title_slug:
            return {"difficulty": "Medium", "topic": "General"}

        query = """
        query questionData($titleSlug: String!) {
          question(titleSlug: $titleSlug) {
            difficulty
            topicTags {
              name
            }
          }
        }
        """
        data = await self._post_graphql(query, {"titleSlug": title_slug})
        q = data.get("question") or {}
        difficulty = q.get("difficulty", "Medium")
        topic_tags = q.get("topicTags") or []
        main_topic = topic_tags[0].get("name") if topic_tags else "General"

        return {
            "difficulty": difficulty,
            "topic": main_topic,
        }
