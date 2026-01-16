"""
Plan Generator
Service for generating and revising structured plans for draft PR orchestrator
"""
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from .draft_pr_models import PlanSpec, PlanVersion, PlanFeedback, FeedbackType
from .draft_pr_schemas import validate_plan_spec, calculate_plan_hash
from .prompts.draft_pr_planning import DraftPRPlanningPrompts
from .llm_client import LLMClient
from .opencode_runner import OpenCodeRunner, OpenCodeError
from .workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class PlanGeneratorError(Exception):
    """Base exception for plan generation errors"""
    pass


class PlanValidationError(PlanGeneratorError):
    """Raised when plan validation fails"""
    pass


class PlanGenerator:
    """
    Generates and revises structured plans for draft PR orchestrator.
    
    Supports both OpenCode (code-aware) and direct LLM generation.
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        opencode_runner: Optional[OpenCodeRunner] = None,
        workspace_manager: Optional[WorkspaceManager] = None
    ):
        """
        Initialize plan generator.
        
        Args:
            llm_client: LLM client for direct generation (optional)
            opencode_runner: OpenCode runner for code-aware generation (optional)
            workspace_manager: Workspace manager for OpenCode (optional)
        """
        self.llm_client = llm_client
        self.opencode_runner = opencode_runner
        self.workspace_manager = workspace_manager
    
    async def generate_plan(
        self,
        job_id: str,
        story_key: str,
        story_summary: str,
        story_description: Optional[str] = None,
        scope: Optional[Dict[str, Any]] = None,
        repos: Optional[List[Dict[str, Any]]] = None,
        additional_context: Optional[str] = None,
        use_opencode: bool = False,
        workspace_path: Optional[Path] = None,
        cancellation_event: Optional[Any] = None
    ) -> PlanVersion:
        """
        Generate initial plan (v1) for a story.
        
        Args:
            job_id: Job identifier
            story_key: JIRA story key
            story_summary: Story summary
            story_description: Story description
            scope: Optional scope constraints
            repos: List of repositories (for OpenCode)
            additional_context: Additional context
            use_opencode: Whether to use OpenCode (requires repos)
            workspace_path: Workspace path (for OpenCode)
            cancellation_event: Cancellation event
            
        Returns:
            PlanVersion object (v1)
            
        Raises:
            PlanGeneratorError: If generation fails
            PlanValidationError: If plan validation fails
        """
        # Build prompt
        prompt = DraftPRPlanningPrompts.get_plan_generation_prompt(
            story_key=story_key,
            story_summary=story_summary,
            story_description=story_description,
            scope=scope,
            repos=repos,
            additional_context=additional_context
        )
        
        # Generate plan
        if use_opencode and repos and self.opencode_runner and workspace_path:
            plan_dict = await self._generate_with_opencode(
                job_id=job_id,
                prompt=prompt,
                workspace_path=workspace_path,
                cancellation_event=cancellation_event
            )
            generated_by = "opencode"
        elif self.llm_client:
            plan_dict = await self._generate_with_llm(prompt)
            generated_by = "llm"
        else:
            raise PlanGeneratorError("No LLM client or OpenCode runner available")
        
        # Validate plan
        try:
            validate_plan_spec(plan_dict)
        except Exception as e:
            raise PlanValidationError(f"Plan validation failed: {e}")
        
        # Create PlanSpec
        plan_spec = PlanSpec(**plan_dict)
        
        # Calculate hash
        plan_hash = calculate_plan_hash(plan_dict)
        
        # Detect cross-repo impacts
        cross_repo_impacts = self._detect_cross_repo_impacts(plan_dict, repos or [])
        if cross_repo_impacts:
            plan_spec.cross_repo_impacts = cross_repo_impacts
        
        # Detect missing environment requirements
        unknowns = self._detect_missing_requirements(plan_dict)
        if unknowns:
            plan_spec.unknowns.extend(unknowns)
        
        # Create PlanVersion
        plan_version = PlanVersion(
            version=1,
            plan_spec=plan_spec,
            plan_hash=plan_hash,
            previous_version_hash=None,
            generated_by=generated_by
        )
        
        logger.info(f"Generated plan v1 for job {job_id}, hash: {plan_hash[:8]}")
        return plan_version
    
    async def revise_plan(
        self,
        job_id: str,
        previous_version: PlanVersion,
        feedback: PlanFeedback,
        use_opencode: bool = False,
        workspace_path: Optional[Path] = None,
        cancellation_event: Optional[Any] = None
    ) -> PlanVersion:
        """
        Revise a plan based on user feedback.
        
        Args:
            job_id: Job identifier
            previous_version: Previous plan version
            feedback: User feedback
            use_opencode: Whether to use OpenCode
            workspace_path: Workspace path (for OpenCode)
            cancellation_event: Cancellation event
            
        Returns:
            New PlanVersion object (next version number)
            
        Raises:
            PlanGeneratorError: If revision fails
            PlanValidationError: If revised plan validation fails
        """
        # Convert previous plan to dict
        previous_plan_dict = previous_version.plan_spec.dict()
        previous_plan_dict['version'] = previous_version.version
        
        # Build revision prompt
        prompt = DraftPRPlanningPrompts.get_plan_revision_prompt(
            previous_plan=previous_plan_dict,
            feedback=feedback.feedback_text,
            specific_concerns=feedback.specific_concerns,
            feedback_type=feedback.feedback_type.value if feedback.feedback_type else None
        )
        
        # Generate revised plan
        if use_opencode and self.opencode_runner and workspace_path:
            plan_dict = await self._generate_with_opencode(
                job_id=job_id,
                prompt=prompt,
                workspace_path=workspace_path,
                cancellation_event=cancellation_event
            )
            generated_by = "opencode"
        elif self.llm_client:
            plan_dict = await self._generate_with_llm(prompt)
            generated_by = "llm"
        else:
            raise PlanGeneratorError("No LLM client or OpenCode runner available")
        
        # Remove version from dict (it's not part of PlanSpec)
        plan_dict.pop('version', None)
        
        # Validate revised plan
        try:
            validate_plan_spec(plan_dict)
        except Exception as e:
            raise PlanValidationError(f"Revised plan validation failed: {e}")
        
        # Create PlanSpec
        plan_spec = PlanSpec(**plan_dict)
        
        # Calculate hash
        plan_hash = calculate_plan_hash(plan_dict)
        
        # Create new PlanVersion with feedback history
        new_version = PlanVersion(
            version=previous_version.version + 1,
            plan_spec=plan_spec,
            plan_hash=plan_hash,
            previous_version_hash=previous_version.plan_hash,
            generated_by=generated_by,
            feedback_history=[feedback]
        )
        
        logger.info(f"Revised plan to v{new_version.version} for job {job_id}, hash: {plan_hash[:8]}")
        return new_version
    
    async def _generate_with_llm(self, prompt: str) -> Dict[str, Any]:
        """Generate plan using direct LLM"""
        if not self.llm_client:
            raise PlanGeneratorError("LLM client not available")
        
        # Use JSON generation mode
        json_response = self.llm_client.generate_json(prompt)
        
        try:
            return json.loads(json_response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Response was: {json_response[:500]}")
            raise PlanGeneratorError(f"Invalid JSON response from LLM: {e}")
    
    async def _generate_with_opencode(
        self,
        job_id: str,
        prompt: str,
        workspace_path: Path,
        cancellation_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Generate plan using OpenCode"""
        if not self.opencode_runner:
            raise PlanGeneratorError("OpenCode runner not available")
        
        try:
            result = await self.opencode_runner.execute(
                job_id=job_id,
                workspace_path=workspace_path,
                prompt=prompt,
                job_type="plan_generation",
                cancellation_event=cancellation_event
            )
            
            # OpenCode returns result.json, extract plan
            # The result should contain the plan directly or in a 'plan' field
            if isinstance(result, dict):
                if 'plan' in result:
                    return result['plan']
                elif 'summary' in result and 'scope' in result:
                    # Result is the plan itself
                    return result
                else:
                    raise PlanGeneratorError(f"Unexpected OpenCode result structure: {list(result.keys())}")
            else:
                raise PlanGeneratorError(f"OpenCode returned non-dict result: {type(result)}")
                
        except OpenCodeError as e:
            raise PlanGeneratorError(f"OpenCode execution failed: {e}")
    
    def _detect_cross_repo_impacts(
        self,
        plan_dict: Dict[str, Any],
        repos: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """
        Detect cross-repo impacts mentioned in plan.
        
        Args:
            plan_dict: Plan dictionary
            repos: List of available repos
            
        Returns:
            List of cross-repo impacts
        """
        impacts = []
        
        # Check if plan mentions other repos
        plan_text = json.dumps(plan_dict, default=str).lower()
        repo_urls = [r.get('url', r) if isinstance(r, dict) else r for r in repos]
        repo_names = [url.split('/')[-1].replace('.git', '') for url in repo_urls]
        
        # Look for references to repos not in the list
        # This is a simple heuristic - could be enhanced with more sophisticated analysis
        for repo_name in repo_names:
            if repo_name.lower() in plan_text:
                # Check if this repo is in our list
                found = False
                for repo in repos:
                    repo_url = repo.get('url', repo) if isinstance(repo, dict) else repo
                    if repo_name.lower() in repo_url.lower():
                        found = True
                        break
                
                if not found:
                    impacts.append({
                        "repo": repo_name,
                        "reason": f"Plan references {repo_name} but it's not in the workspace"
                    })
        
        return impacts
    
    def _detect_missing_requirements(self, plan_dict: Dict[str, Any]) -> List[str]:
        """
        Detect missing environment requirements.
        
        Args:
            plan_dict: Plan dictionary
            
        Returns:
            List of missing requirements to add to unknowns
        """
        missing = []
        
        # Check assumptions for common missing requirements
        assumptions = plan_dict.get('assumptions', [])
        plan_text = json.dumps(plan_dict, default=str).lower()
        
        # Common patterns that indicate missing requirements
        if 'database' in plan_text and not any('database' in a.lower() for a in assumptions):
            missing.append("Database connection and schema details need verification")
        
        if 'api' in plan_text and 'external' in plan_text:
            missing.append("External API credentials and endpoints need verification")
        
        if 'environment' in plan_text or 'env' in plan_text:
            missing.append("Environment variables and configuration need verification")
        
        return missing
