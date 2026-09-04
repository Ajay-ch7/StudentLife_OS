import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.integrations.leetcode_query import LeetCodeQueryClient
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.leetcode_state import LeetCodeState
from app.models.student_profile import StudentProfile, User
from app.services.leetcode_watcher_service import LeetCodeWatcherService
from openclaw.workflows.dsa_workflow import DSARecommendationWorkflow


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()

    user = User(email="leetcode_student@test.com", full_name="LeetCode Student", telegram_name="lc_student")
    session.add(user)
    session.commit()
    session.refresh(user)

    profile = StudentProfile(user_id=user.id, leetcode_username="test_lc_user")
    session.add(profile)
    session.commit()

    yield session, user
    session.close()


@pytest.mark.asyncio
async def test_leetcode_query_client_profile_success():
    client = LeetCodeQueryClient()
    mock_data = {
        "matchedUser": {
            "username": "test_user",
            "submitStatsGlobal": {
                "acSubmissionNum": [
                    {"difficulty": "All", "count": 120},
                    {"difficulty": "Easy", "count": 50},
                    {"difficulty": "Medium", "count": 60},
                    {"difficulty": "Hard", "count": 10},
                ]
            },
        }
    }

    with patch.object(client, "_post_graphql", new_callable=AsyncMock, return_value=mock_data):
        profile = await client.fetch_user_profile("test_user")
        assert profile["found"] is True
        assert profile["total_solved"] == 120
        assert profile["easy"] == 50
        assert profile["medium"] == 60
        assert profile["hard"] == 10


@pytest.mark.asyncio
async def test_leetcode_query_client_recent_submissions():
    client = LeetCodeQueryClient()
    mock_data = {
        "recentAcSubmissionList": [
            {
                "id": "1001",
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "timestamp": "1700000000",
            },
            {
                "id": "1002",
                "title": "Add Two Numbers",
                "titleSlug": "add-two-numbers",
                "timestamp": "1700001000",
            },
        ]
    }

    with patch.object(client, "_post_graphql", new_callable=AsyncMock, return_value=mock_data):
        subs = await client.fetch_recent_ac_submissions("test_user")
        assert len(subs) == 2
        assert subs[0]["submission_id"] == "1001"
        assert subs[0]["title"] == "Two Sum"


@pytest.mark.asyncio
async def test_leetcode_watcher_change_detection_and_openclaw(test_db):
    session, user = test_db

    watcher = LeetCodeWatcherService(interval_seconds=60)

    mock_profile = {
        "found": True,
        "total_solved": 15,
        "easy": 10,
        "medium": 4,
        "hard": 1,
    }
    mock_subs = [
        {
            "submission_id": "sub_999",
            "title": "Binary Tree Inorder Traversal",
            "title_slug": "binary-tree-inorder-traversal",
            "timestamp": 1700000000,
        }
    ]
    mock_details = {"difficulty": "Easy", "topic": "Tree"}

    watcher.query_client.fetch_user_profile = AsyncMock(return_value=mock_profile)
    watcher.query_client.fetch_recent_ac_submissions = AsyncMock(return_value=mock_subs)
    watcher.query_client.fetch_problem_details = AsyncMock(return_value=mock_details)

    watcher.dsa_workflow.telegram.send_message = AsyncMock(
        return_value=MagicMock(mocked=True, chat_id="mock_chat")
    )

    res = await watcher.check_user_leetcode_updates(db=session, user_id=user.id)
    assert res["status"] == "success"
    assert res["newly_solved_count"] == 1

    # Verify DSAProblem was stored
    problem = session.query(DSAProblem).filter(DSAProblem.leetcode_submission_id == "sub_999").first()
    assert problem is not None
    assert problem.title == "Binary Tree Inorder Traversal"
    assert problem.topic == "Tree"
    assert problem.difficulty == "Easy"

    # Verify DSAProgress was synced
    progress = session.query(DSAProgress).filter(DSAProgress.user_id == user.id, DSAProgress.topic == "Tree").first()
    assert progress is not None
    assert progress.solved_count == 1

    # Verify LeetCodeState was updated
    state = session.query(LeetCodeState).filter(LeetCodeState.user_id == user.id).first()
    assert state is not None
    assert state.total_solved == 15
    assert state.last_submission_id == "sub_999"

    # Run polling again with same submission — should not duplicate!
    res_second = await watcher.check_user_leetcode_updates(db=session, user_id=user.id)
    assert res_second["newly_solved_count"] == 0

    problems_count = session.query(DSAProblem).filter(DSAProblem.user_id == user.id).count()
    assert problems_count == 1


@pytest.mark.asyncio
async def test_dsa_recommendation_workflow_telegram_message_formatting(test_db):
    session, user = test_db

    workflow = DSARecommendationWorkflow()
    mock_send = AsyncMock(return_value=MagicMock(mocked=True))
    workflow.telegram.send_message = mock_send

    payload = {
        "username": "test_dev & coder",
        "total_solved": 45,
        "newly_solved": [
            {"title": "Two Sum", "difficulty": "Easy", "topic": "Arrays & Hashing"},
            {"title": "Group Anagrams", "difficulty": "Medium", "topic": "Arrays & Hashing"},
            {"title": "3Sum", "difficulty": "Medium", "topic": "Two Pointers"},
        ],
    }

    res = await workflow.run(user_id=user.id, db=session, payload=payload)
    assert res["status"] == "completed"

    mock_send.assert_called_once()
    _, kwargs = mock_send.call_args
    sent_text = kwargs["text"]

    # Verify header & user info
    assert "DSA Progress Update" in sent_text
    assert "<b>Total Solved:</b> 45" in sent_text
    assert "<b>User:</b> @test_dev &amp; coder" in sent_text

    # Verify grouping by topic
    assert "<b>Arrays &amp; Hashing</b>" in sent_text
    assert "• Two Sum (<i>Easy</i>)" in sent_text
    assert "• Group Anagrams (<i>Medium</i>)" in sent_text

    assert "<b>Two Pointers</b>" in sent_text
    assert "• 3Sum (<i>Medium</i>)" in sent_text

    # Verify recommendation section
    assert "<b>OpenClaw Recommendation:</b>" in sent_text
    assert res["recommendation"] is not None
    assert len(res["recommendation"]) > 0

