"""
Bulk Ticket Creation Service for JIRA Integration
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import time

from .planning_models import (
    EpicPlan, StoryPlan, TaskPlan, PlanningResult, OperationMode
)
from .jira_client import JiraClient

logger = logging.getLogger(__name__)


class BulkTicketCreator:
    """Service for creating multiple JIRA tickets with proper relationships"""
    
    def __init__(self, jira_client: JiraClient, confluence_client=None):
        self.jira_client = jira_client
        self.confluence_client = confluence_client
    
    def create_epic_structure(self, epic_plan: EpicPlan, dry_run: bool = True) -> Dict[str, Any]:
        """
        Create complete epic structure with stories and tasks
        
        Args:
            epic_plan: Complete epic plan with stories and tasks
            dry_run: If True, simulate creation without actually creating tickets
            
        Returns:
            Creation results with ticket keys and any errors
        """
        start_time = time.time()
        logger.info(f"Starting epic structure creation for {epic_plan.epic_key} (dry_run={dry_run})")
        
        results = {
            "epic_key": epic_plan.epic_key,
            "dry_run": dry_run,
            "success": True,
            "created_tickets": {
                "stories": [],
                "tasks": []
            },
            "failed_creations": [],
            "relationships_created": [],
            "relationships_failed": [],
            "errors": [],
            "execution_time_seconds": 0.0
        }
        
        if dry_run:
            return self._simulate_epic_creation(epic_plan, results)
        
        try:
            # Get project key from epic
            project_key = self.jira_client.get_project_key_from_epic(epic_plan.epic_key)
            if not project_key:
                results["success"] = False
                results["errors"].append(f"Could not extract project key from epic {epic_plan.epic_key}")
                return results
            
            # Create stories first
            story_mapping = {}  # original_story_plan -> created_key
            
            for story_plan in epic_plan.stories:
                story_key = self._create_story_with_retry(story_plan, project_key)
                
                if story_key:
                    results["created_tickets"]["stories"].append(story_key)
                    story_mapping[id(story_plan)] = story_key
                    logger.info(f"Created story {story_key}: {story_plan.summary}")
                else:
                    results["failed_creations"].append({
                        "type": "story",
                        "summary": story_plan.summary,
                        "error": "Failed to create story ticket"
                    })
                    results["success"] = False
            
            # Create tasks for each story
            task_mapping = {}  # task_plan_id -> created_key
            pending_links = []  # Collect links to create after all tickets are created
            
            for story_plan in epic_plan.stories:
                story_id = id(story_plan)
                if story_id not in story_mapping:
                    continue  # Skip if story creation failed
                
                story_key = story_mapping[story_id]
                
                for task_plan in story_plan.tasks:
                    task_key = self._create_task_with_retry(task_plan, project_key, story_key)
                    
                    if task_key:
                        results["created_tickets"]["tasks"].append(task_key)
                        task_mapping[id(task_plan)] = task_key
                        logger.info(f"Created task {task_key}: {task_plan.summary}")
                        
                        # Collect "Split From" relationship for later creation
                        if hasattr(task_plan, 'split_from_story') and task_plan.split_from_story:
                            pending_links.append({
                                "from": task_key,
                                "to": story_key,
                                "type": "Split From"
                            })
                    else:
                        results["failed_creations"].append({
                            "type": "task",
                            "summary": task_plan.summary,
                            "parent_story": story_key,
                            "error": "Failed to create task ticket"
                        })
                        results["success"] = False
            
            # Now that all tickets are created, create all links
            logger.info(f"All tickets created. Creating {len(pending_links)} pending links...")
            
            # Create "Split From" relationships
            for link_info in pending_links:
                # Swap: Story as inward, Task as outward to get correct relationship
                # link_info["from"] is task_key, link_info["to"] is story_key
                # We need to swap them for correct relationship
                link_success = self.jira_client.create_issue_link(
                    link_info["to"], link_info["from"], link_info["type"]  # Swapped: story as inward, task as outward
                )
                if link_success:
                    results["relationships_created"].append(link_info)
                else:
                    results["relationships_failed"].append(link_info)
            
            # Create dependency relationships between tasks
            self._create_task_dependencies(epic_plan.stories, task_mapping, results)
            
            # Validate the created structure
            validation_results = self.jira_client.validate_ticket_relationships(epic_plan.epic_key)
            if not validation_results["valid"]:
                results["errors"].extend(validation_results["issues"])
                logger.warning(f"Epic structure validation found issues: {validation_results['issues']}")
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Unexpected error during epic creation: {str(e)}")
            logger.error(f"Error creating epic structure: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
            logger.info(f"Epic structure creation completed in {results['execution_time_seconds']:.2f}s")
        
        return results
    
    def create_stories_only(self, epic_key: str, stories: List[StoryPlan], dry_run: bool = True) -> Dict[str, Any]:
        """
        Create only stories for an epic
        
        Args:
            epic_key: Parent epic key
            stories: List of story plans to create
            dry_run: If True, simulate creation
            
        Returns:
            Creation results
        """
        start_time = time.time()
        logger.info(f"Creating {len(stories)} stories for epic {epic_key} (dry_run={dry_run})")
        
        results = {
            "epic_key": epic_key,
            "dry_run": dry_run,
            "success": True,
            "created_tickets": {"stories": []},
            "failed_creations": [],
            "errors": [],
            "execution_time_seconds": 0.0
        }
        
        if dry_run:
            for story in stories:
                results["created_tickets"]["stories"].append(f"STORY-{hash(story.summary) % 10000}")
            results["execution_time_seconds"] = time.time() - start_time
            return results
        
        try:
            project_key = self.jira_client.get_project_key_from_epic(epic_key)
            if not project_key:
                results["success"] = False
                results["errors"].append(f"Could not extract project key from epic {epic_key}")
                return results
            
            for story_plan in stories:
                story_key = self._create_story_with_retry(story_plan, project_key)
                
                if story_key:
                    results["created_tickets"]["stories"].append(story_key)
                    logger.info(f"Created story {story_key}")
                else:
                    results["failed_creations"].append({
                        "type": "story",
                        "summary": story_plan.summary,
                        "error": "Failed to create story ticket"
                    })
                    results["success"] = False
        
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Error creating stories: {str(e)}")
            logger.error(f"Error creating stories: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
        
        return results
    
    def create_tasks_only(self, tasks: List[TaskPlan], story_keys: List[str], dry_run: bool = True) -> Dict[str, Any]:
        """
        Create only tasks for existing stories
        
        Args:
            tasks: List of task plans to create
            story_keys: List of parent story keys
            dry_run: If True, simulate creation
            
        Returns:
            Creation results
        """
        start_time = time.time()
        logger.info(f"Creating {len(tasks)} tasks for {len(story_keys)} stories (dry_run={dry_run})")
        
        results = {
            "story_keys": story_keys,
            "dry_run": dry_run,
            "success": True,
            "created_tickets": {"tasks": []},
            "failed_creations": [],
            "relationships_created": [],
            "relationships_failed": [],
            "errors": [],
            "execution_time_seconds": 0.0
        }
        
        if dry_run:
            for task in tasks:
                results["created_tickets"]["tasks"].append(f"TASK-{hash(task.summary) % 10000}")
            results["execution_time_seconds"] = time.time() - start_time
            return results
        
        try:
            # Assume all stories are in the same project
            project_key = None
            if story_keys:
                project_key = self.jira_client.get_project_key_from_epic(story_keys[0])
            
            if not project_key:
                results["success"] = False
                results["errors"].append("Could not determine project key from story keys")
                return results
            
            # Create tasks with story relationships
            task_mapping = {}  # task_plan_id -> created_key
            story_task_mapping = {}  # task_key -> story_key
            story_index = 0
            
            for task_plan in tasks:
                # Assign to story in round-robin fashion
                story_key = story_keys[story_index % len(story_keys)]
                story_index += 1
                
                task_key = self._create_task_with_retry(task_plan, project_key, story_key)
                
                if task_key:
                    results["created_tickets"]["tasks"].append(task_key)
                    task_mapping[id(task_plan)] = task_key
                    story_task_mapping[task_key] = story_key
                    logger.info(f"Created task {task_key} under story {story_key}")
                else:
                    results["failed_creations"].append({
                        "type": "task",
                        "summary": task_plan.summary,
                        "parent_story": story_key,
                        "error": "Failed to create task ticket"
                    })
                    results["success"] = False
            
            # Create story-task links for all created tasks
            for task_key, story_key in story_task_mapping.items():
                # Swap: Story as inward, Task as outward to get correct relationship
                # This makes Task show "split from" Story correctly
                link_success = self.jira_client.create_issue_link(
                    inward_key=story_key,    # Story is inward
                    outward_key=task_key,    # Task is outward (shows "split from" Story)
                    link_type="Work item split"
                )
                if link_success:
                    results["relationships_created"].append({
                        "from": task_key,
                        "to": story_key,
                        "type": "Work item split"
                    })
                    logger.info(f"Created story-task link: {task_key} split from {story_key}")
                else:
                    results["relationships_failed"].append({
                        "from": task_key,
                        "to": story_key,
                        "type": "Work item split",
                        "error": "Failed to create link"
                    })
                    logger.warning(f"Failed to create story-task link: {task_key} -> {story_key}")
            
            # Create dependency relationships if any tasks have dependencies
            if any(task.depends_on_tasks for task in tasks):
                self._create_standalone_task_dependencies(tasks, task_mapping, results)
        
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Error creating tasks: {str(e)}")
            logger.error(f"Error creating tasks: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
        
        return results
    
    def _simulate_epic_creation(self, epic_plan: EpicPlan, results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate epic structure creation for dry run"""
        logger.info(f"Simulating epic structure creation for {epic_plan.epic_key}")
        
        # Simulate story creation
        task_keys = []
        for story_plan in epic_plan.stories:
            story_key = f"STORY-{hash(story_plan.summary) % 10000}"
            results["created_tickets"]["stories"].append(story_key)
            
            # Simulate task creation
            for task_plan in story_plan.tasks:
                task_key = f"TASK-{hash(task_plan.summary) % 10000}"
                results["created_tickets"]["tasks"].append(task_key)
                task_keys.append(task_key)
                
                # Simulate parent relationships
                results["relationships_created"].append({
                    "from": task_key,
                    "to": story_key,
                    "type": "Parent"
                })
                
                # Simulate dependency relationships
                if task_plan.depends_on_tasks:
                    for dep_id in task_plan.depends_on_tasks:
                        # For simulation, create a blocking relationship with another task
                        if len(task_keys) > 1:
                            blocking_key = task_keys[-2]  # Previous task blocks this one
                            results["relationships_created"].append({
                                "from": blocking_key,
                                "to": task_key,
                                "type": "Blocks",
                                "blocking_team": "backend",  # Simulated team
                                "dependent_team": task_plan.team.value
                            })
        
        results["execution_time_seconds"] = 0.5  # Simulate quick dry run
        logger.info(f"Simulated creation: {len(results['created_tickets']['stories'])} stories, {len(results['created_tickets']['tasks'])} tasks, {len([r for r in results['relationships_created'] if r['type'] == 'Blocks'])} dependencies")
        
        return results
    
    def _create_story_with_retry(self, story_plan: StoryPlan, project_key: str, max_retries: int = 3) -> Optional[str]:
        """Create story ticket with retry logic"""
        # Get Confluence server URL if available
        confluence_server_url = None
        if self.confluence_client:
            confluence_server_url = self.confluence_client.server_url
        
        for attempt in range(max_retries):
            try:
                story_key = self.jira_client.create_story_ticket(
                    story_plan, 
                    project_key,
                    confluence_server_url=confluence_server_url
                )
                if story_key:
                    return story_key
                
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
            except Exception as e:
                logger.warning(f"Story creation attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        return None
    
    def _create_task_with_retry(self, task_plan: TaskPlan, project_key: str, story_key: str, max_retries: int = 3) -> Optional[str]:
        """Create task ticket with retry logic"""
        # Get Confluence server URL if available
        confluence_server_url = None
        if self.confluence_client:
            confluence_server_url = self.confluence_client.server_url
        
        for attempt in range(max_retries):
            try:
                task_key = self.jira_client.create_task_ticket(task_plan, project_key, story_key, confluence_server_url=confluence_server_url)
                if task_key:
                    return task_key
                
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
            except Exception as e:
                logger.warning(f"Task creation attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        return None
    
    def rollback_creation(self, created_tickets: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Rollback created tickets in case of failure
        
        Args:
            created_tickets: Dictionary with lists of created ticket keys
            
        Returns:
            Rollback results
        """
        rollback_results = {
            "success": True,
            "deleted_tickets": [],
            "failed_deletions": [],
            "errors": []
        }
        
        # Delete in reverse order (tasks first, then stories)
        all_tickets = created_tickets.get("tasks", []) + created_tickets.get("stories", [])
        
        for ticket_key in reversed(all_tickets):
            try:
                # Note: This would require delete permissions and careful consideration
                # For now, we'll just log what would be deleted
                logger.warning(f"Would delete ticket {ticket_key} in rollback")
                rollback_results["deleted_tickets"].append(ticket_key)
                
            except Exception as e:
                rollback_results["failed_deletions"].append(ticket_key)
                rollback_results["errors"].append(f"Failed to delete {ticket_key}: {str(e)}")
                rollback_results["success"] = False
        
        return rollback_results
    
    def _create_task_dependencies(self, stories: List[StoryPlan], task_mapping: Dict[int, str], results: Dict[str, Any]) -> None:
        """
        Create dependency relationships between tasks based on their depends_on_tasks field
        
        Args:
            stories: List of story plans containing tasks
            task_mapping: Mapping from task plan ID to created JIRA key  
            results: Results dictionary to update with relationship info
        """
        logger.info("Creating task dependency relationships")
        
        # Build a mapping from task summary to task plan for dependency lookup
        all_tasks = []
        for story in stories:
            all_tasks.extend(story.tasks)
        
        # Create summary to task plan mapping for AI-generated dependencies
        summary_to_task = {}
        for task in all_tasks:
            summary_to_task[task.summary] = task
        
        # Create task ID to plan mapping for legacy dependencies
        task_id_to_plan = {}
        for i, task in enumerate(all_tasks):
            task_id_to_plan[f"task_{i+1}"] = task
        
        dependency_count = 0
        
        for task_plan in all_tasks:
            task_id = id(task_plan)
            
            if task_id not in task_mapping:
                continue  # Skip if task wasn't created
                
            dependent_task_key = task_mapping[task_id]
            
            # Create "is blocked by" relationships for each dependency
            for dep_identifier in task_plan.depends_on_tasks:
                dependency_task_plan = None
                
                # Try to find dependency by task summary (AI-generated dependencies)
                if dep_identifier in summary_to_task:
                    dependency_task_plan = summary_to_task[dep_identifier]
                    logger.info(f"Found AI dependency: '{task_plan.summary}' depends on '{dep_identifier}'")
                # Fallback to legacy task ID format (pattern-generated dependencies)
                elif dep_identifier in task_id_to_plan:
                    dependency_task_plan = task_id_to_plan[dep_identifier]
                    logger.info(f"Found legacy dependency: '{task_plan.summary}' depends on task ID '{dep_identifier}'")
                else:
                    logger.warning(f"Dependency not found for '{task_plan.summary}': '{dep_identifier}'")
                    continue
                
                # Create the JIRA link if we found the dependency task
                if dependency_task_plan:
                    dependency_task_id = id(dependency_task_plan)
                    
                    if dependency_task_id in task_mapping:
                        blocking_task_key = task_mapping[dependency_task_id]
                        
                        # Create "Blocks" relationship (blocking_task blocks dependent_task)
                        link_success = self.jira_client.create_issue_link(
                            blocking_task_key, dependent_task_key, "Blocks"
                        )
                        
                        if link_success:
                            results["relationships_created"].append({
                                "from": blocking_task_key,
                                "to": dependent_task_key,
                                "type": "Blocks",
                                "blocking_team": dependency_task_plan.team.value,
                                "dependent_team": task_plan.team.value
                            })
                            dependency_count += 1
                            logger.info(f"Created blocking relationship: {blocking_task_key} ({dependency_task_plan.team.value}) blocks {dependent_task_key} ({task_plan.team.value})")
                        else:
                            results["relationships_failed"].append({
                                "from": blocking_task_key,
                                "to": dependent_task_key,
                                "type": "Blocks",
                                "error": "Failed to create blocking relationship"
                            })
        
        logger.info(f"Created {dependency_count} task dependency relationships")
    
    def _create_standalone_task_dependencies(self, tasks: List[TaskPlan], task_mapping: Dict[int, str], results: Dict[str, Any]) -> None:
        """
        Create dependency relationships for standalone task creation
        
        Args:
            tasks: List of task plans
            task_mapping: Mapping from task plan ID to created JIRA key
            results: Results dictionary to update with relationship info
        """
        logger.info("Creating standalone task dependency relationships")
        
        # Create summary to task plan mapping for AI-generated dependencies
        summary_to_task = {}
        for task in tasks:
            summary_to_task[task.summary] = task
        
        # Create task ID to plan mapping for legacy dependencies
        task_id_to_plan = {}
        for i, task in enumerate(tasks):
            task_id_to_plan[f"task_{i+1}"] = task
        
        dependency_count = 0
        
        for task_plan in tasks:
            task_id = id(task_plan)
            
            if task_id not in task_mapping:
                continue  # Skip if task wasn't created
                
            dependent_task_key = task_mapping[task_id]
            
            # Create "is blocked by" relationships for each dependency
            for dep_identifier in task_plan.depends_on_tasks:
                dependency_task_plan = None
                
                # Try to find dependency by task summary (AI-generated dependencies)
                if dep_identifier in summary_to_task:
                    dependency_task_plan = summary_to_task[dep_identifier]
                    logger.info(f"Found AI dependency: '{task_plan.summary}' depends on '{dep_identifier}'")
                # Fallback to legacy task ID format (pattern-generated dependencies)
                elif dep_identifier in task_id_to_plan:
                    dependency_task_plan = task_id_to_plan[dep_identifier]
                    logger.info(f"Found legacy dependency: '{task_plan.summary}' depends on task ID '{dep_identifier}'")
                else:
                    logger.warning(f"Dependency not found for '{task_plan.summary}': '{dep_identifier}'")
                    continue
                
                # Create the JIRA link if we found the dependency task
                if dependency_task_plan:
                    dependency_task_id = id(dependency_task_plan)
                    
                    if dependency_task_id in task_mapping:
                        blocking_task_key = task_mapping[dependency_task_id]
                        
                        # Create "Blocks" relationship (blocking_task blocks dependent_task)
                        link_success = self.jira_client.create_issue_link(
                            blocking_task_key, dependent_task_key, "Blocks"
                        )
                        
                        if link_success:
                            results["relationships_created"].append({
                                "from": blocking_task_key,
                                "to": dependent_task_key,
                                "type": "Blocks",
                                "blocking_team": dependency_task_plan.team.value,
                                "dependent_team": task_plan.team.value
                            })
                            dependency_count += 1
                            logger.info(f"Created blocking relationship: {blocking_task_key} ({dependency_task_plan.team.value}) blocks {dependent_task_key} ({task_plan.team.value})")
                        else:
                            results["relationships_failed"].append({
                                "from": blocking_task_key,
                                "to": dependent_task_key,
                                "type": "Blocks",
                                "error": "Failed to create blocking relationship"
                            })
        
        logger.info(f"Created {dependency_count} standalone task dependency relationships")
