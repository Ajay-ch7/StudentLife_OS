from openclaw.workflows.base_workflow import BaseWorkflow
from openclaw.workflows.briefing_workflow import MorningBriefingWorkflow
from openclaw.workflows.email_to_action_workflow import EmailToActionWorkflow
from openclaw.workflows.inbox_to_task import InboxToTaskWorkflow
from openclaw.workflows.inbox_workflow import InboxProcessingWorkflow
from openclaw.workflows.job_workflow import AutonomousJobWorkflow
from openclaw.workflows.opportunity_workflow import OpportunityEvaluationWorkflow

__all__ = [
    "BaseWorkflow",
    "AutonomousJobWorkflow",
    "EmailToActionWorkflow",
    "InboxProcessingWorkflow",
    "InboxToTaskWorkflow",
    "MorningBriefingWorkflow",
    "OpportunityEvaluationWorkflow",
]


