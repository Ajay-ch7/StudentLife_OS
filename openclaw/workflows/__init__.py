from openclaw.workflows.base_workflow import BaseWorkflow
from openclaw.workflows.briefing_workflow import MorningBriefingWorkflow
from openclaw.workflows.inbox_to_task import InboxToTaskWorkflow
from openclaw.workflows.inbox_workflow import InboxProcessingWorkflow
from openclaw.workflows.opportunity_workflow import OpportunityEvaluationWorkflow

__all__ = [
    "BaseWorkflow",
    "InboxProcessingWorkflow",
    "InboxToTaskWorkflow",
    "MorningBriefingWorkflow",
    "OpportunityEvaluationWorkflow",
]

