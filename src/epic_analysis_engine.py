"""
Epic Analysis Engine for gap analysis and planning operations
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from .planning_models import (
    EpicPlan, StoryPlan, TaskPlan, GapAnalysis, 
    PlanningContext, OperationMode, CycleTimeEstimate
)
from .jira_client import JiraClient
from .confluence_client import ConfluenceClient
from .models import PRDContent, RFCContent

logger = logging.getLogger(__name__)


class EpicAnalysisEngine:
    """Engine for analyzing epics and generating planning recommendations"""
    
    def __init__(self, jira_client: JiraClient, confluence_client: ConfluenceClient):
        self.jira_client = jira_client
        self.confluence_client = confluence_client
    
    def analyze_epic_structure(self, epic_key: str) -> GapAnalysis:
        """
        Analyze an epic to identify gaps in story/task structure
        
        Args:
            epic_key: JIRA epic key to analyze
            
        Returns:
            GapAnalysis with identified gaps and recommendations
        """
        logger.info(f"Analyzing epic structure for {epic_key}")
        
        try:
            # Get epic details
            epic_issue = self.jira_client.jira.issue(epic_key)
            epic_summary = epic_issue.fields.summary
            epic_description = getattr(epic_issue.fields, 'description', '') or ''
            
            # Get linked stories and tasks
            existing_stories = self._get_epic_stories(epic_key)
            story_tasks = self._get_stories_tasks(existing_stories)
            orphaned_tasks = self._get_orphaned_tasks(epic_key, story_tasks)
            
            # Get requirements from PRD/RFC
            prd_requirements = []
            rfc_requirements = []
            
            # Extract requirements from custom fields
            prd_url = self._get_custom_field_value(epic_issue, 'PRD')
            rfc_url = self._get_custom_field_value(epic_issue, 'RFC')
            
            if prd_url:
                # Use the correct confluence client method to get enhanced PRD content
                prd_page_data = self.confluence_client.get_page_content(prd_url)
                if prd_page_data:
                    prd_content = self._build_prd_content_from_page_data(prd_page_data)
                    prd_requirements = self._extract_prd_requirements(prd_content)
            
            if rfc_url:
                # Use the correct confluence client method to get enhanced RFC content
                rfc_page_data = self.confluence_client.get_page_content(rfc_url)
                if rfc_page_data:
                    rfc_content = self._build_rfc_content_from_page_data(rfc_page_data)
                    rfc_requirements = self._extract_rfc_requirements(rfc_content)
            
            # Identify missing stories based on requirements
            missing_stories = self._identify_missing_stories(
                epic_summary, epic_description, prd_requirements, rfc_requirements, existing_stories
            )
            
            # Identify incomplete stories (stories without tasks)
            incomplete_stories = [story_key for story_key in existing_stories if not story_tasks.get(story_key)]
            
            gap_analysis = GapAnalysis(
                epic_key=epic_key,
                existing_stories=existing_stories,
                missing_stories=missing_stories,
                incomplete_stories=incomplete_stories,
                orphaned_tasks=orphaned_tasks,
                prd_requirements=prd_requirements,
                rfc_requirements=rfc_requirements
            )
            
            logger.info(f"Gap analysis complete for {epic_key}: {len(missing_stories)} missing stories, {len(incomplete_stories)} incomplete stories")
            return gap_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing epic {epic_key}: {str(e)}")
            return GapAnalysis(epic_key=epic_key)
    
    def _get_epic_stories(self, epic_key: str) -> List[str]:
        """Get all stories linked to an epic"""
        try:
            # Search for stories in this epic
            jql = f'"Epic Link" = {epic_key} AND issuetype = Story'
            issues = self.jira_client.jira.search_issues(jql, maxResults=1000)
            return [issue.key for issue in issues]
        except Exception as e:
            logger.warning(f"Error getting stories for epic {epic_key}: {str(e)}")
            return []
    
    def _get_stories_tasks(self, story_keys: List[str]) -> Dict[str, List[str]]:
        """Get tasks for each story"""
        story_tasks = {}
        
        for story_key in story_keys:
            try:
                # Search for tasks/subtasks under this story
                jql = f'parent = {story_key} OR "Epic Link" = {story_key} AND issuetype in (Task, Sub-task)'
                issues = self.jira_client.jira.search_issues(jql, maxResults=100)
                story_tasks[story_key] = [issue.key for issue in issues]
            except Exception as e:
                logger.warning(f"Error getting tasks for story {story_key}: {str(e)}")
                story_tasks[story_key] = []
        
        return story_tasks
    
    def _get_orphaned_tasks(self, epic_key: str, story_tasks: Dict[str, List[str]]) -> List[str]:
        """Get tasks directly linked to epic but not under any story"""
        try:
            # Get all tasks in epic
            jql = f'"Epic Link" = {epic_key} AND issuetype in (Task, Sub-task)'
            epic_tasks = self.jira_client.jira.search_issues(jql, maxResults=1000)
            epic_task_keys = {issue.key for issue in epic_tasks}
            
            # Get all tasks under stories
            story_task_keys = set()
            for tasks in story_tasks.values():
                story_task_keys.update(tasks)
            
            # Find orphaned tasks
            orphaned = list(epic_task_keys - story_task_keys)
            return orphaned
            
        except Exception as e:
            logger.warning(f"Error getting orphaned tasks for epic {epic_key}: {str(e)}")
            return []
    
    def _get_custom_field_value(self, issue, field_type: str) -> Optional[str]:
        """Get custom field value for PRD or RFC"""
        try:
            if field_type == 'PRD':
                field_id = self.jira_client.prd_field_id
            elif field_type == 'RFC':
                field_id = self.jira_client.rfc_field_id
            else:
                return None
            
            return getattr(issue.fields, field_id, None)
        except Exception:
            return None
    
    def _build_prd_content_from_page_data(self, page_data: Dict[str, Any]) -> PRDContent:
        """Build PRDContent from page data using enhanced section extraction"""
        # Extract enhanced PRD sections (same as generator does)
        prd_sections = page_data.get('prd_sections', {})
        
        # Build PRDContent with enhanced section data
        return PRDContent(
            title=page_data['title'],
            url=page_data['url'],
            summary=page_data.get('summary'),
            goals=page_data.get('goals'),
            content=page_data.get('content', ''),
            # Enhanced sections for better planning context
            target_population=prd_sections.get('target_population'),
            user_problem_definition=prd_sections.get('user_problem_definition'),
            business_value=prd_sections.get('business_value'),
            proposed_solution=prd_sections.get('proposed_solution'),
            success_criteria=prd_sections.get('success_criteria'),
            strategic_impact=prd_sections.get('strategic_impact'),
            constraints_limitation=prd_sections.get('constraints_limitation'),
            user_stories=prd_sections.get('user_stories'),
            description_flow=prd_sections.get('description_flow'),
            user_value=prd_sections.get('user_value'),
            business_impact=prd_sections.get('business_impact'),
            user_problem_frequency=prd_sections.get('user_problem_frequency'),
            user_problem_severity=prd_sections.get('user_problem_severity')
        )
    
    def _build_rfc_content_from_page_data(self, page_data: Dict[str, Any]) -> RFCContent:
        """Build RFCContent from page data using enhanced section extraction"""
        # Extract enhanced RFC sections (same as generator does)
        rfc_sections = page_data.get('rfc_sections', {})
        
        # Build RFCContent with comprehensive field coverage
        return RFCContent(
            # Metadata
            status=rfc_sections.get('status'),
            owner=rfc_sections.get('owner'),
            authors=rfc_sections.get('authors'),
            
            # 1. Overview section
            overview=rfc_sections.get('overview'),
            success_criteria=rfc_sections.get('success_criteria'),
            out_of_scope=rfc_sections.get('out_of_scope'),
            related_documents=rfc_sections.get('related_documents'),
            assumptions=rfc_sections.get('assumptions'),
            dependencies=rfc_sections.get('dependencies'),
            
            # 2. Technical Design section
            technical_design=rfc_sections.get('technical_design'),
            architecture_tech_stack=rfc_sections.get('architecture_tech_stack'),
            sequence=rfc_sections.get('sequence'),
            database_model=rfc_sections.get('database_model'),
            apis=rfc_sections.get('apis'),
            
            # 3. High-Availability & Security section
            high_availability_security=rfc_sections.get('high_availability_security'),
            performance_requirement=rfc_sections.get('performance_requirement'),
            monitoring_alerting=rfc_sections.get('monitoring_alerting'),
            logging=rfc_sections.get('logging'),
            security_implications=rfc_sections.get('security_implications'),
            
            # 4. Backwards Compatibility and Rollout Plan section
            backwards_compatibility_rollout=rfc_sections.get('backwards_compatibility_rollout'),
            compatibility=rfc_sections.get('compatibility'),
            rollout_strategy=rfc_sections.get('rollout_strategy'),
            
            # 5. Concern, Questions, or Known Limitations section
            concerns_questions_limitations=rfc_sections.get('concerns_questions_limitations'),
            
            # Additional common sections
            alternatives_considered=rfc_sections.get('alternatives_considered'),
            risks_and_mitigations=rfc_sections.get('risks_and_mitigations'),
            testing_strategy=rfc_sections.get('testing_strategy'),
            timeline=rfc_sections.get('timeline')
        )
    
    def _extract_prd_requirements(self, prd_content: PRDContent) -> List[str]:
        """Extract functional requirements from enhanced PRD sections"""
        requirements = []
        
        # Extract from enhanced PRD sections
        if prd_content.user_problem_definition:
            requirements.append(f"Problem: {prd_content.user_problem_definition}")
        
        if prd_content.proposed_solution:
            requirements.append(f"Solution: {prd_content.proposed_solution}")
        
        if prd_content.success_criteria:
            requirements.append(f"Success Criteria: {prd_content.success_criteria}")
        
        if prd_content.user_stories:
            requirements.append(f"User Stories: {prd_content.user_stories}")
        
        if prd_content.constraints_limitation:
            requirements.append(f"Constraints: {prd_content.constraints_limitation}")
        
        if prd_content.description_flow:
            requirements.append(f"Flow: {prd_content.description_flow}")
        
        if prd_content.strategic_impact:
            requirements.append(f"Strategic Impact: {prd_content.strategic_impact}")
        
        # Fallback to legacy attributes if they exist
        if hasattr(prd_content, 'functional_requirements') and prd_content.functional_requirements:
            requirements.extend(prd_content.functional_requirements)
        
        if hasattr(prd_content, 'features') and prd_content.features:
            requirements.extend(prd_content.features)
        
        return [req for req in requirements if req.strip()]
    
    def _extract_rfc_requirements(self, rfc_content: RFCContent) -> List[str]:
        """Extract technical requirements from enhanced RFC sections"""
        requirements = []
        
        # Extract from enhanced RFC sections
        if rfc_content.technical_design:
            requirements.append(f"Technical Design: {rfc_content.technical_design}")
        
        if rfc_content.architecture_tech_stack:
            requirements.append(f"Architecture: {rfc_content.architecture_tech_stack}")
        
        if rfc_content.security_implications:
            requirements.append(f"Security: {rfc_content.security_implications}")
        
        if rfc_content.performance_requirement:
            requirements.append(f"Performance: {rfc_content.performance_requirement}")
        
        if rfc_content.dependencies:
            requirements.append(f"Dependencies: {rfc_content.dependencies}")
        
        if rfc_content.testing_strategy:
            requirements.append(f"Testing: {rfc_content.testing_strategy}")
        
        if rfc_content.rollout_strategy:
            requirements.append(f"Rollout: {rfc_content.rollout_strategy}")
        
        if rfc_content.risks_and_mitigations:
            requirements.append(f"Risks: {rfc_content.risks_and_mitigations}")
        
        # Fallback to legacy attributes if they exist
        if hasattr(rfc_content, 'technical_details') and rfc_content.technical_details:
            requirements.append(rfc_content.technical_details)
        
        if hasattr(rfc_content, 'implementation') and rfc_content.implementation:
            requirements.append(rfc_content.implementation)
        if hasattr(rfc_content, 'security_implications') and rfc_content.security_implications:
            requirements.append(rfc_content.security_implications)
        
        return [req for req in requirements if req.strip()]
    
    def _identify_missing_stories(
        self, 
        epic_summary: str,
        epic_description: str, 
        prd_requirements: List[str],
        rfc_requirements: List[str],
        existing_stories: List[str]
    ) -> List[str]:
        """Identify missing story areas based on requirements"""
        # This is a simplified version - in a real implementation, 
        # this would use LLM analysis to identify gaps
        
        missing_areas = []
        
        # Basic keyword-based analysis
        all_requirements = prd_requirements + rfc_requirements
        requirement_text = ' '.join(all_requirements).lower()
        
        # Common story patterns
        story_patterns = [
            ("authentication", "User Authentication"),
            ("authorization", "User Authorization"),
            ("api", "API Integration"),
            ("database", "Data Storage"),
            ("ui", "User Interface"),
            ("testing", "Testing"),
            ("deployment", "Deployment"),
            ("monitoring", "Monitoring"),
            ("security", "Security"),
            ("performance", "Performance")
        ]
        
        for keyword, story_area in story_patterns:
            if keyword in requirement_text:
                # Check if we have a story covering this area
                has_story = any(keyword in story.lower() for story in existing_stories)
                if not has_story:
                    missing_areas.append(story_area)
        
        return missing_areas
    
    def estimate_cycle_time(self, task_description: str, task_complexity: str = "medium") -> CycleTimeEstimate:
        """
        Estimate cycle time for a task based on description and complexity
        
        Args:
            task_description: Description of the task
            task_complexity: Complexity level (low, medium, high)
            
        Returns:
            CycleTimeEstimate with breakdown
        """
        # Base estimates by complexity
        base_estimates = {
            "low": {"dev": 0.5, "test": 0.25, "review": 0.25, "deploy": 0.25},
            "medium": {"dev": 1.5, "test": 0.5, "review": 0.5, "deploy": 0.25},
            "high": {"dev": 2.5, "test": 1.0, "review": 0.75, "deploy": 0.5}
        }
        
        estimates = base_estimates.get(task_complexity.lower(), base_estimates["medium"])
        
        # Adjust based on task type keywords
        description_lower = task_description.lower()
        
        multipliers = {
            "database": 1.3,
            "migration": 1.5,
            "api": 1.2,
            "integration": 1.4,
            "security": 1.3,
            "performance": 1.2,
            "ui": 1.1,
            "test": 0.8,
            "documentation": 0.7,
            "configuration": 0.6
        }
        
        multiplier = 1.0
        for keyword, mult in multipliers.items():
            if keyword in description_lower:
                multiplier *= mult
                break
        
        # Apply multiplier
        dev_days = estimates["dev"] * multiplier
        test_days = estimates["test"] * multiplier
        review_days = estimates["review"]
        deploy_days = estimates["deploy"]
        
        total_days = dev_days + test_days + review_days + deploy_days
        
        # Confidence based on how well we can estimate
        confidence = 0.8 if task_complexity == "medium" else (0.7 if task_complexity == "low" else 0.6)
        
        return CycleTimeEstimate(
            development_days=dev_days,
            testing_days=test_days,
            review_days=review_days,
            deployment_days=deploy_days,
            total_days=total_days,
            confidence_level=confidence
        )
    
    def should_split_task(self, cycle_estimate: CycleTimeEstimate, max_days: float = 3.0) -> bool:
        """Determine if a task should be split based on cycle time"""
        return cycle_estimate.total_days > max_days
    
    def suggest_task_split(self, task_description: str, cycle_estimate: CycleTimeEstimate) -> List[str]:
        """
        Suggest how to split an oversized task
        
        Args:
            task_description: Original task description
            cycle_estimate: Cycle time estimate showing it's oversized
            
        Returns:
            List of suggested smaller task descriptions
        """
        # This is a simplified version - real implementation would use LLM
        suggestions = []
        
        # Common split patterns
        if "and" in task_description.lower():
            # Split on "and" conjunctions
            parts = task_description.split(" and ")
            if len(parts) > 1:
                for i, part in enumerate(parts):
                    suggestions.append(f"Task {i+1}: {part.strip()}")
        
        elif any(keyword in task_description.lower() for keyword in ["implement", "develop", "create"]):
            # Split implementation tasks
            suggestions = [
                f"Design and plan: {task_description}",
                f"Implement core functionality: {task_description}",
                f"Testing and validation: {task_description}"
            ]
        
        else:
            # Generic split
            suggestions = [
                f"Phase 1: {task_description}",
                f"Phase 2: {task_description}"
            ]
        
        # Ensure we have valid splits
        if not suggestions or len(suggestions) == 1:
            suggestions = [
                f"Part 1: {task_description[:len(task_description)//2]}",
                f"Part 2: {task_description[len(task_description)//2:]}"
            ]
        
        return suggestions
