import csv
import io
from collections import Counter
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.job_dsa_plan import JobDSAPlanProblem
from app.models.leetcode_state import LeetCodeState
from app.models.opportunity import Opportunity

DEFAULT_JOB_PLANS = {
    "Google": [
        {"title": "Merge Strings Alternately", "title_slug": "merge-strings-alternately", "topic": "Strings", "difficulty": "Easy"},
        {"title": "Two Sum", "title_slug": "two-sum", "topic": "Arrays & Hashing", "difficulty": "Easy"},
        {"title": "Container With Most Water", "title_slug": "container-with-most-water", "topic": "Two Pointers", "difficulty": "Medium"},
        {"title": "3Sum", "title_slug": "3sum", "topic": "Two Pointers", "difficulty": "Medium"},
        {"title": "Word Search", "title_slug": "word-search", "topic": "Backtracking", "difficulty": "Medium"},
        {"title": "LRU Cache", "title_slug": "lru-cache", "topic": "Design / Linked List", "difficulty": "Medium"},
        {"title": "Course Schedule", "title_slug": "course-schedule", "topic": "Graphs", "difficulty": "Medium"},
        {"title": "Trapping Rain Water", "title_slug": "trapping-rain-water", "topic": "Two Pointers", "difficulty": "Hard"},
    ],
    "Razorpay": [
        {"title": "Reverse Words in a String", "title_slug": "reverse-words-in-a-string", "topic": "Strings", "difficulty": "Medium"},
        {"title": "Move Zeroes", "title_slug": "move-zeroes", "topic": "Arrays", "difficulty": "Easy"},
        {"title": "Greatest Common Divisor of Strings", "title_slug": "greatest-common-divisor-of-strings", "topic": "Strings", "difficulty": "Easy"},
        {"title": "LRU Cache", "title_slug": "lru-cache", "topic": "Design", "difficulty": "Medium"},
        {"title": "Longest Substring Without Repeating Characters", "title_slug": "longest-substring-without-repeating-characters", "topic": "Sliding Window", "difficulty": "Medium"},
        {"title": "Valid Parentheses", "title_slug": "valid-parentheses", "topic": "Stack", "difficulty": "Easy"},
    ],
    "Microsoft": [
        {"title": "Reverse Vowels of a String", "title_slug": "reverse-vowels-of-a-string", "topic": "Two Pointers", "difficulty": "Easy"},
        {"title": "Kids With the Greatest Number of Candies", "title_slug": "kids-with-the-greatest-number-of-candies", "topic": "Arrays", "difficulty": "Easy"},
        {"title": "Merge Intervals", "title_slug": "merge-intervals", "topic": "Arrays / Sorting", "difficulty": "Medium"},
        {"title": "Binary Tree Level Order Traversal", "title_slug": "binary-tree-level-order-traversal", "topic": "Trees", "difficulty": "Medium"},
        {"title": "Number of Islands", "title_slug": "number-of-islands", "topic": "Graphs", "difficulty": "Medium"},
        {"title": "Search in Rotated Sorted Array", "title_slug": "search-in-rotated-sorted-array", "topic": "Binary Search", "difficulty": "Medium"},
    ],
    "Flipkart": [
        {"title": "Can Place Flowers", "title_slug": "can-place-flowers", "topic": "Greedy / Arrays", "difficulty": "Easy"},
        {"title": "Product of Array Except Self", "title_slug": "product-of-array-except-self", "topic": "Arrays", "difficulty": "Medium"},
        {"title": "Group Anagrams", "title_slug": "group-anagrams", "topic": "Hash Table", "difficulty": "Medium"},
        {"title": "Top K Frequent Elements", "title_slug": "top-k-frequent-elements", "topic": "Heap", "difficulty": "Medium"},
        {"title": "Coin Change", "title_slug": "coin-change", "topic": "Dynamic Programming", "difficulty": "Medium"},
    ],
}


class DSAService:
    @staticmethod
    def summary(db: Session, user_id: int) -> dict:
        items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        lc_state = db.query(LeetCodeState).filter(LeetCodeState.user_id == user_id).first()

        days = {item.solved_on for item in items if item.solved_on}
        streak = lc_state.streak if (lc_state and lc_state.streak > 0) else 0
        if streak == 0 and days:
            today = date.today()
            if today in days:
                cursor = today
            elif (today - timedelta(days=1)) in days:
                cursor = today - timedelta(days=1)
            else:
                cursor = max(days)

            while cursor in days:
                streak += 1
                cursor -= timedelta(days=1)

        topics = Counter(item.topic for item in items)

        total_solved = lc_state.total_solved if (lc_state and lc_state.total_solved > 0) else len(items)
        easy_solved = lc_state.easy_solved if lc_state else sum(1 for i in items if i.difficulty.lower() == "easy")
        medium_solved = lc_state.medium_solved if lc_state else sum(1 for i in items if i.difficulty.lower() == "medium")
        hard_solved = lc_state.hard_solved if lc_state else sum(1 for i in items if i.difficulty.lower() == "hard")
        active_days = lc_state.active_days if lc_state else len(days)
        ranking = lc_state.ranking if lc_state else None
        username = lc_state.leetcode_username if lc_state else "kriti30_"
        last_polled_at = lc_state.last_polled_at.isoformat() if (lc_state and lc_state.last_polled_at) else None

        return {
            "username": username,
            "total": total_solved,
            "easy_solved": easy_solved,
            "medium_solved": medium_solved,
            "hard_solved": hard_solved,
            "streak": streak,
            "active_days": active_days,
            "ranking": ranking,
            "last_polled_at": last_polled_at,
            "topics": dict(topics),
            "weak_topics": sorted(topic for topic, count in topics.items() if count < 3),
        }

    @staticmethod
    def sync_progress(db: Session, user_id: int) -> None:
        items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        grouped: dict[str, list[DSAProblem]] = {}
        for item in items:
            grouped.setdefault(item.topic, []).append(item)

        existing_progress = db.query(DSAProgress).filter(DSAProgress.user_id == user_id).all()
        for topic, values in grouped.items():
            progress = db.query(DSAProgress).filter(DSAProgress.user_id == user_id, DSAProgress.topic == topic).first()
            if progress is None:
                progress = DSAProgress(user_id=user_id, topic=topic)
                db.add(progress)
            progress.solved_count = len(values)
            progress.revision_count = sum(item.needs_revision for item in values)

        # Remove records for topics that no longer have solved problems
        for p in existing_progress:
            if p.topic not in grouped:
                db.delete(p)

        db.commit()

    @staticmethod
    def ensure_job_applications_and_plans(db: Session, user_id: int) -> list[Application]:
        """Ensure opportunities have corresponding applications and company-specific DSA plans."""
        opportunities = db.query(Opportunity).filter(Opportunity.user_id == user_id).all()
        if not opportunities:
            # Seed standard opportunities if none exist
            opp_google = Opportunity(user_id=user_id, title="Software Engineer Intern", company="Google", description="SDE Summer Intern position", required_skills="C++, Python, Data Structures, Algorithms", match_score=92.0)
            opp_ms = Opportunity(user_id=user_id, title="SDE Intern - Platform Team", company="Microsoft", description="Software Engineer Intern", required_skills="C#, Java, DSA, System Design", match_score=88.0)
            opp_razorpay = Opportunity(user_id=user_id, title="Backend Developer Intern", company="Razorpay", description="Backend Engineering Intern", required_skills="Python, Go, SQL, Distributed Systems", match_score=85.0)
            opp_flipkart = Opportunity(user_id=user_id, title="Full-Stack Developer Intern", company="Flipkart", description="Full Stack Engineer Intern", required_skills="React, Node.js, DSA", match_score=80.0)
            db.add_all([opp_google, opp_ms, opp_razorpay, opp_flipkart])
            db.commit()
            opportunities = db.query(Opportunity).filter(Opportunity.user_id == user_id).all()

        applications = []
        for opp in opportunities:
            app = db.query(Application).filter(Application.user_id == user_id, Application.opportunity_id == opp.id).first()
            if not app:
                app = Application(user_id=user_id, opportunity_id=opp.id, status="submitted", notes=f"Application for {opp.company} - {opp.title}")
                db.add(app)
                db.commit()
                db.refresh(app)
            applications.append(app)

            # Ensure DSA plan problems exist for this application
            existing_plan = db.query(JobDSAPlanProblem).filter(JobDSAPlanProblem.application_id == app.id).all()
            if not existing_plan:
                # Find matching company key
                company_key = "Google"
                for key in DEFAULT_JOB_PLANS:
                    if key.lower() in opp.company.lower():
                        company_key = key
                        break
                
                plan_items = DEFAULT_JOB_PLANS.get(company_key, DEFAULT_JOB_PLANS["Google"])
                for item in plan_items:
                    plan_prob = JobDSAPlanProblem(
                        application_id=app.id,
                        company=opp.company,
                        title=item["title"],
                        title_slug=item["title_slug"],
                        topic=item["topic"],
                        difficulty=item["difficulty"],
                        notes=f"Target problem for {opp.company} technical interview",
                    )
                    db.add(plan_prob)
                db.commit()

        return applications

    @staticmethod
    def _normalize_title(title: str) -> str:
        return title.strip().lower().replace("-", " ").replace("_", " ")

    @staticmethod
    def get_job_applications_dsa_summary(db: Session, user_id: int) -> list[dict]:
        """
        Get all job applications with DSA preparation metrics calculated dynamically
        against the user's actual solved LeetCode problems.
        """
        DSAService.ensure_job_applications_and_plans(db, user_id)

        # Get solved problems for user (by title slug and normalized title)
        solved_problems = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        solved_slugs = {p.leetcode_submission_id: p for p in solved_problems if p.leetcode_submission_id}
        solved_title_map = {DSAService._normalize_title(p.title): p for p in solved_problems}

        applications = db.query(Application).filter(Application.user_id == user_id).all()
        results = []

        for app in applications:
            opp = db.query(Opportunity).filter(Opportunity.id == app.opportunity_id).first()
            company = opp.company if opp else "Company"
            title = opp.title if opp else "Job Position"

            planned_problems = db.query(JobDSAPlanProblem).filter(JobDSAPlanProblem.application_id == app.id).all()
            total_planned = len(planned_problems)

            solved_count = 0
            for item in planned_problems:
                item_slug = item.title_slug.strip().lower()
                norm_title = DSAService._normalize_title(item.title)
                
                # Check if solved either by slug or title match
                is_solved = (item_slug in solved_slugs) or (norm_title in solved_title_map)
                if is_solved:
                    solved_count += 1

            completion_percentage = round((solved_count / total_planned * 100), 1) if total_planned > 0 else 0.0

            results.append({
                "application_id": app.id,
                "opportunity_id": app.opportunity_id,
                "company": company,
                "role": title,
                "status": app.status,
                "total_planned": total_planned,
                "solved_count": solved_count,
                "remaining_count": total_planned - solved_count,
                "completion_percentage": completion_percentage,
            })

        return results

    @staticmethod
    def get_job_dsa_plan(db: Session, user_id: int, application_id: int) -> dict:
        """Get detailed DSA preparation plan for a specific job application with solved/remaining breakdowns."""
        DSAService.ensure_job_applications_and_plans(db, user_id)

        app = db.query(Application).filter(Application.id == application_id, Application.user_id == user_id).first()
        if not app:
            return {}

        opp = db.query(Opportunity).filter(Opportunity.id == app.opportunity_id).first()
        company = opp.company if opp else "Company"
        role = opp.title if opp else "Job Position"

        solved_problems = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        solved_title_map = {DSAService._normalize_title(p.title): p for p in solved_problems}

        planned_problems = db.query(JobDSAPlanProblem).filter(JobDSAPlanProblem.application_id == app.id).all()

        planned_items = []
        solved_items = []
        remaining_items = []

        for p in planned_problems:
            norm_title = DSAService._normalize_title(p.title)
            solved_match = solved_title_map.get(norm_title)
            is_solved = solved_match is not None
            solved_on_str = solved_match.solved_on.isoformat() if (solved_match and solved_match.solved_on) else None

            item_dict = {
                "id": p.id,
                "title": p.title,
                "title_slug": p.title_slug,
                "topic": p.topic,
                "difficulty": p.difficulty,
                "company": p.company,
                "notes": p.notes,
                "is_solved": is_solved,
                "solved_on": solved_on_str,
                "leetcode_url": f"https://leetcode.com/problems/{p.title_slug}/" if p.title_slug else None,
            }

            planned_items.append(item_dict)
            if is_solved:
                solved_items.append(item_dict)
            else:
                remaining_items.append(item_dict)

        total_planned = len(planned_items)
        solved_count = len(solved_items)
        completion_percentage = round((solved_count / total_planned * 100), 1) if total_planned > 0 else 0.0

        return {
            "application_id": app.id,
            "opportunity_id": app.opportunity_id,
            "company": company,
            "role": role,
            "status": app.status,
            "total_planned": total_planned,
            "solved_count": solved_count,
            "remaining_count": len(remaining_items),
            "completion_percentage": completion_percentage,
            "planned_problems": planned_items,
            "solved_problems": solved_items,
            "remaining_problems": remaining_items,
        }

    @staticmethod
    def import_csv(db: Session, user_id: int, content: str) -> int:
        rows = csv.DictReader(io.StringIO(content))
        required = {"title", "topic", "difficulty", "solved_on"}
        if not rows.fieldnames or not required.issubset(set(rows.fieldnames)):
            raise ValueError("CSV requires title, topic, difficulty, and solved_on columns")
        items = [DSAProblem(user_id=user_id, title=row["title"].strip(), topic=row["topic"].strip(), difficulty=row["difficulty"].strip(), attempts=int(row.get("attempts") or 1), solved_on=date.fromisoformat(row["solved_on"]), needs_revision=str(row.get("needs_revision", "false")).lower() == "true") for row in rows]
        db.add_all(items); db.commit(); DSAService.sync_progress(db, user_id)
        return len(items)