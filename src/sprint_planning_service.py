"""
Sprint Planning Service
Core service for sprint planning logic including capacity planning and timeline scheduling
"""
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta

from .jira_client import JiraClient
from .planning_models import TaskPlan, EpicPlan
from .team_member_service import TeamMemberService

# Import models with TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from api.models.sprint_planning import (
        SprintInfo, SprintAssignment, SprintPlanningResponse, 
        SprintTimelineItem, TimelineResponse
    )

logger = logging.getLogger(__name__)


class SprintPlanningService:
    """Service for sprint planning operations"""
    
    def __init__(self, jira_client: JiraClient, team_member_service: Optional[TeamMemberService] = None):
        self.jira_client = jira_client
        self.team_member_service = team_member_service or TeamMemberService()
    
    def plan_epic_to_sprints(
        self, 
        epic_key: str, 
        board_id: int, 
        sprint_capacity_days: Optional[float] = None,
        start_date: Optional[str] = None,
        sprint_duration_days: int = 14,
        team_id: Optional[int] = None,
        auto_create_sprints: bool = False,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Plan epic tasks across sprints based on capacity and dependencies
        
        Args:
            epic_key: Epic key to plan
            board_id: Board ID
            sprint_capacity_days: Sprint capacity in days (if None, uses team member data)
            start_date: Start date for planning (ISO format)
            sprint_duration_days: Sprint duration in days
            team_id: Team ID for capacity calculation
            auto_create_sprints: Auto-create sprints if needed
            dry_run: Preview mode
            
        Returns:
            SprintPlanningResponse with assignments
        """
        try:
            # Get epic tasks
            epic_issue = self.jira_client.get_ticket(epic_key)
            if not epic_issue:
                raise ValueError(f"Epic {epic_key} not found")
            
            # Get tasks for epic (this would need to be implemented based on your structure)
            # For now, we'll assume tasks are passed or retrieved differently
            # This is a placeholder - you'll need to integrate with your planning service
            
            # Get or calculate capacity
            if sprint_capacity_days is None:
                if team_id:
                    sprint_capacity_days = self.team_member_service.get_team_capacity(team_id, board_id)
                else:
                    # Default capacity
                    sprint_capacity_days = 10.0
            
            # Get existing sprints
            sprints = self.jira_client.get_board_sprints(board_id, state="active")
            if not sprints and auto_create_sprints and not dry_run:
                # Create initial sprint
                if start_date:
                    start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                else:
                    start = datetime.now()
                end = start + timedelta(days=sprint_duration_days)
                
                sprint = self.jira_client.create_sprint(
                    name=f"Sprint {start.strftime('%Y-%m-%d')}",
                    board_id=board_id,
                    start_date=start.strftime('%Y-%m-%d'),
                    end_date=end.strftime('%Y-%m-%d')
                )
                sprints = [sprint]
            
            # Convert to SprintInfo
            sprint_infos = [self._convert_to_sprint_info(s) for s in sprints]
            
            # This is a placeholder - actual task planning logic would go here
            # You'll need to integrate with your planning service to get tasks
            assignments = []
            errors = []
            warnings = []
            
            return {
                "epic_key": epic_key,
                "board_id": board_id,
                "success": True,
                "assignments": assignments,
                "sprints_created": [],
                "total_tasks": 0,
                "total_sprints": len(sprint_infos),
                "capacity_utilization": {},
                "errors": errors,
                "warnings": warnings
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to plan epic to sprints: {str(e)}")
            raise
    
    def optimize_sprint_assignments(
        self,
        tasks: List[TaskPlan],
        sprints: List[Dict[str, Any]],
        capacity_days: float
    ) -> List[Dict[str, Any]]:
        """
        Optimize sprint assignments based on dependencies and capacity
        
        Args:
            tasks: List of tasks to assign
            sprints: List of available sprints
            capacity_days: Capacity per sprint in days
            
        Returns:
            List of sprint assignments
        """
        assignments = []
        
        # Build dependency graph
        task_map = {task.key or task.summary: task for task in tasks}
        dependency_graph = {}
        for task in tasks:
            task_key = task.key or task.summary
            dependency_graph[task_key] = []
            for dep_key in task.depends_on_tasks:
                if dep_key in task_map:
                    dependency_graph[task_key].append(dep_key)
        
        # Topological sort to respect dependencies
        sorted_tasks = self._topological_sort(tasks, dependency_graph)
        
        # Assign tasks to sprints
        sprint_capacity_used = {}
        sprint_assignments = {}
        for sprint in sprints:
            sprint_id = sprint.get('id') if isinstance(sprint, dict) else sprint.id
            sprint_capacity_used[sprint_id] = 0.0
            sprint_assignments[sprint_id] = []
        
        for task in sorted_tasks:
            task_key = task.key or task.summary
            estimated_days = task.cycle_time_estimate.total_days if task.cycle_time_estimate else 1.0
            
            # Find earliest sprint that can fit this task and respects dependencies
            assigned = False
            for sprint in sprints:
                sprint_id = sprint.get('id') if isinstance(sprint, dict) else sprint.id
                # Check if dependencies are satisfied
                deps_satisfied = True
                for dep_key in task.depends_on_tasks:
                    dep_assigned = False
                    for prev_sprint in sprints:
                        prev_sprint_id = prev_sprint.get('id') if isinstance(prev_sprint, dict) else prev_sprint.id
                        if prev_sprint_id <= sprint_id:
                            if dep_key in [t.key or t.summary for t in sprint_assignments[prev_sprint_id]]:
                                dep_assigned = True
                                break
                    if not dep_assigned:
                        deps_satisfied = False
                        break
                
                if deps_satisfied and sprint_capacity_used[sprint_id] + estimated_days <= capacity_days:
                    sprint_assignments[sprint_id].append(task)
                    sprint_capacity_used[sprint_id] += estimated_days
                    assigned = True
                    break
            
            if not assigned:
                # Task doesn't fit - would need new sprint or error
                logger.warning(f"Task {task_key} doesn't fit in available sprints")
        
        # Convert to assignment dictionaries
        for sprint in sprints:
            sprint_id = sprint.get('id') if isinstance(sprint, dict) else sprint.id
            sprint_name = sprint.get('name') if isinstance(sprint, dict) else sprint.name
            for task in sprint_assignments[sprint_id]:
                task_key = task.key or task.summary
                estimated_days = task.cycle_time_estimate.total_days if task.cycle_time_estimate else 1.0
                team = task.team.value if hasattr(task.team, 'value') else str(task.team) if task.team else None
                
                assignments.append({
                    "task_key": task_key,
                    "task_summary": task.summary,
                    "sprint_id": sprint_id,
                    "sprint_name": sprint_name,
                    "estimated_days": estimated_days,
                    "team": team
                })
        
        return assignments
    
    def schedule_timeline(
        self,
        epic_key: str,
        board_id: int,
        start_date: str,
        sprint_duration_days: int,
        team_capacity_days: Optional[float] = None,
        team_id: Optional[int] = None,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Create timeline schedule for epic
        
        Args:
            epic_key: Epic key
            board_id: Board ID
            start_date: Start date (ISO format)
            sprint_duration_days: Sprint duration in days
            team_capacity_days: Team capacity in days
            team_id: Team ID for capacity calculation
            dry_run: Preview mode
            
        Returns:
            TimelineResponse with scheduled sprints
        """
        try:
            # Get or calculate capacity
            if team_capacity_days is None:
                if team_id:
                    team_capacity_days = self.team_member_service.get_team_capacity(team_id, board_id)
                else:
                    team_capacity_days = 10.0
            
            # Parse start date
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            
            # This is a placeholder - you'll need to get tasks from your planning service
            # For now, return empty timeline
            sprints = []
            errors = []
            warnings = []
            
            return {
                "epic_key": epic_key,
                "board_id": board_id,
                "start_date": start_date,
                "sprint_duration_days": sprint_duration_days,
                "sprints": sprints,
                "total_sprints": 0,
                "total_tasks": 0,
                "errors": errors,
                "warnings": warnings
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to schedule timeline: {str(e)}")
            raise
    
    def assign_tickets_to_sprint(self, ticket_keys: List[str], sprint_id: int, dry_run: bool = True) -> bool:
        """Assign tickets to sprint"""
        if dry_run:
            logger.info(f"DRY RUN: Would assign {len(ticket_keys)} tickets to sprint {sprint_id}")
            return True
        
        return self.jira_client.add_issues_to_sprint(sprint_id, ticket_keys)
    
    def calculate_sprint_capacity(self, sprint_id: int, team_capacity_days: Optional[float] = None) -> float:
        """Calculate available capacity for a sprint"""
        if team_capacity_days:
            return team_capacity_days
        
        # Get sprint issues to calculate used capacity
        issues = self.jira_client.get_sprint_issues(sprint_id)
        # This would need to sum up estimates from issues
        # For now, return default
        return 10.0
    
    def _convert_to_sprint_info(self, sprint_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JIRA sprint data to sprint info dictionary"""
        return {
            "id": sprint_data.get('id'),
            "name": sprint_data.get('name', ''),
            "state": sprint_data.get('state', 'active'),
            "start_date": sprint_data.get('startDate'),
            "end_date": sprint_data.get('endDate'),
            "board_id": sprint_data.get('originBoardId'),
            "goal": sprint_data.get('goal'),
            "complete_date": sprint_data.get('completeDate')
        }
    
    def _topological_sort(self, tasks: List[TaskPlan], dependency_graph: Dict[str, List[str]]) -> List[TaskPlan]:
        """Topological sort of tasks respecting dependencies"""
        task_map = {task.key or task.summary: task for task in tasks}
        in_degree = {task_key: 0 for task_key in task_map.keys()}
        
        # Calculate in-degrees
        for task_key, deps in dependency_graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[task_key] += 1
        
        # Kahn's algorithm
        queue = [task_key for task_key, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            task_key = queue.pop(0)
            result.append(task_map[task_key])
            
            # Reduce in-degree of dependent tasks
            for dependent_key, deps in dependency_graph.items():
                if task_key in deps:
                    in_degree[dependent_key] -= 1
                    if in_degree[dependent_key] == 0:
                        queue.append(dependent_key)
        
        # Add any remaining tasks (cycles or missing dependencies)
        for task_key, degree in in_degree.items():
            if degree > 0 and task_map[task_key] not in result:
                result.append(task_map[task_key])
        
        return result

