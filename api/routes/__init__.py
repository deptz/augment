"""
Routes Package
Aggregate all route routers
"""
from fastapi import APIRouter

# Import all routers
from .health import router as health_router
from .generation import router as generation_router
from .jobs import router as jobs_router
from .planning import router as planning_router
from .bulk_creation import router as bulk_creation_router
from .test_generation import router as test_generation_router
from .story_analysis import router as story_analysis_router
from .jira_operations import router as jira_operations_router
from .prompt_testing import router as prompt_testing_router
from .sprint_planning import router as sprint_planning_router
from .team_members import router as team_members_router
from .draft_pr import router as draft_pr_router

# Create main router
api_router = APIRouter()

# Include all routers
api_router.include_router(health_router)
api_router.include_router(generation_router)
api_router.include_router(jobs_router)
api_router.include_router(planning_router)
api_router.include_router(bulk_creation_router)
api_router.include_router(test_generation_router)
api_router.include_router(story_analysis_router)
api_router.include_router(jira_operations_router)
api_router.include_router(prompt_testing_router)
api_router.include_router(sprint_planning_router)
api_router.include_router(team_members_router)
api_router.include_router(draft_pr_router)
