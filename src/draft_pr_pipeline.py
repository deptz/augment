"""
Draft PR Pipeline
Orchestrates the complete PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR workflow
"""
import logging
import asyncio
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path
from datetime import datetime

from .draft_pr_models import PlanVersion, PlanFeedback, Approval, WorkspaceFingerprint, FeedbackType
from .plan_generator import PlanGenerator, PlanGeneratorError, PlanValidationError
from .yolo_policy import YOLOPolicyEvaluator
from .workspace_manager import WorkspaceManager
from .artifact_store import ArtifactStore
from .bitbucket_client import BitbucketClient
from .llm_client import LLMClient

logger = logging.getLogger(__name__)


class PipelineStage:
    """Pipeline stage constants"""
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    REVISING = "REVISING"
    APPLYING = "APPLYING"
    VERIFYING = "VERIFYING"
    PACKAGING = "PACKAGING"
    DRAFTING = "DRAFTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DraftPRPipeline:
    """
    Orchestrates the complete draft PR pipeline.
    
    Manages stage transitions, handles failures, and coordinates all services.
    """
    
    def __init__(
        self,
        plan_generator: PlanGenerator,
        workspace_manager: WorkspaceManager,
        artifact_store: ArtifactStore,
        sandbox_pipeline: Optional[Any] = None,
        sandbox_runner: Optional[Any] = None,
        llm_client: Optional[LLMClient] = None,
        bitbucket_client: Optional[BitbucketClient] = None,
        yolo_policy: Optional[Dict[str, Any]] = None,
        verification_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize pipeline.

        Args:
            plan_generator: Plan generator service
            workspace_manager: Workspace manager (for revise-plan workspace lookup when needed)
            artifact_store: Artifact store
            sandbox_pipeline: SandboxPipelineRunner for APPLY→PR in one sandbox (required for apply)
            sandbox_runner: SandboxCodeRunner for plan generation in sandbox (required for code-aware planning)
            llm_client: LLM client (optional)
            bitbucket_client: Bitbucket client (optional)
            yolo_policy: YOLO policy configuration (optional)
            verification_config: Verification configuration (optional)
        """
        self.plan_generator = plan_generator
        self.workspace_manager = workspace_manager
        self.artifact_store = artifact_store
        self.sandbox_pipeline = sandbox_pipeline
        self.sandbox_runner = sandbox_runner
        self.llm_client = llm_client
        self.bitbucket_client = bitbucket_client
        self.yolo_policy_config = yolo_policy
        self.verification_config = verification_config or {}
    
    async def continue_pipeline_after_approval(
        self,
        job_id: str,
        approved_plan_hash: str,
        cancellation_event: Optional[Any] = None,
        on_sandbox_created: Optional[Callable[[str, str], Any]] = None,
        on_sandbox_released: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """
        Continue pipeline execution after plan approval.

        Resumes from APPLY stage with the approved plan.

        Args:
            job_id: Job identifier
            approved_plan_hash: Hash of the approved plan
            cancellation_event: Cancellation event
            on_sandbox_created: Optional callback (job_id, sandbox_id) when sandbox is created
            on_sandbox_released: Optional callback (job_id) when sandbox is released

        Returns:
            Dict with pipeline results
        """
        # Retrieve job artifacts
        input_spec = self.artifact_store.retrieve_artifact(job_id, "input_spec")
        if not input_spec:
            raise ValueError(f"Input spec not found for job {job_id}")
        
        # Find approved plan version
        artifacts = self.artifact_store.list_artifacts(job_id)
        plan_versions = [a for a in artifacts if a.startswith('plan_v')]
        
        approved_plan = None
        for plan_name in plan_versions:
            try:
                plan_dict = self.artifact_store.retrieve_artifact(job_id, plan_name)
                if not plan_dict:
                    continue
                    
                # Verify plan hash matches
                stored_hash = plan_dict.get('plan_hash')
                if stored_hash != approved_plan_hash:
                    continue
                
                # Reconstruct PlanVersion with error handling for corrupted data
                try:
                    from .draft_pr_models import PlanSpec
                    plan_spec_data = plan_dict.get('plan_spec', plan_dict)
                    plan_spec = PlanSpec(**plan_spec_data)
                    
                    # Verify hash matches calculated hash (data integrity check)
                    from .draft_pr_schemas import calculate_plan_hash
                    calculated_hash = calculate_plan_hash(plan_spec_data)
                    if calculated_hash != stored_hash:
                        logger.error(f"Plan hash mismatch for {plan_name}: stored={stored_hash[:8]}, calculated={calculated_hash[:8]}")
                        raise ValueError(f"Plan artifact corruption detected: hash mismatch for {plan_name}")
                    
                    approved_plan = PlanVersion(
                        version=plan_dict.get('version', 1),
                        plan_spec=plan_spec,
                        plan_hash=stored_hash,
                        previous_version_hash=plan_dict.get('previous_version_hash'),
                        generated_by=plan_dict.get('generated_by')
                    )
                    break
                except (ValueError, KeyError, TypeError) as e:
                    logger.error(f"Failed to reconstruct PlanVersion from artifact {plan_name}: {e}")
                    raise ValueError(f"Plan artifact {plan_name} is corrupted or invalid: {e}")
            except Exception as e:
                logger.warning(f"Failed to retrieve or parse plan artifact {plan_name}: {e}")
                continue
        
        if not approved_plan:
            raise ValueError(f"Approved plan with hash {approved_plan_hash} not found")

        # Safety: Verify the approved plan hash matches what we found
        if approved_plan.plan_hash != approved_plan_hash:
            raise ValueError(
                f"Plan hash mismatch: found plan has hash {approved_plan.plan_hash[:8]} but approval requested {approved_plan_hash[:8]}"
            )

        repos = input_spec.get('repos', [])

        if not self.sandbox_pipeline:
            raise ValueError(
                "OpenSandbox is required for APPLY stage. Enable OPENSANDBOX_ENABLED and ensure the worker has sandbox configured."
            )
        return await self._execute_from_apply_stage(
            job_id=job_id,
            approved_plan=approved_plan,
            workspace_path=None,
            repos=repos,
            cancellation_event=cancellation_event,
            on_sandbox_created=on_sandbox_created,
            on_sandbox_released=on_sandbox_released,
        )

    async def _execute_from_apply_stage(
        self,
        job_id: str,
        approved_plan: PlanVersion,
        workspace_path: Optional[Path],
        repos: List[Dict[str, Any]],
        cancellation_event: Optional[Any] = None,
        on_sandbox_created: Optional[Callable[[str, str], Any]] = None,
        on_sandbox_released: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """Execute pipeline from APPLY stage onwards. workspace_path is None when using sandbox."""
        if not self.sandbox_pipeline:
            raise ValueError(
                "OpenSandbox is required for APPLY stage. Enable OPENSANDBOX_ENABLED and ensure the worker has sandbox configured."
            )
        repo_url = (repos[0].get("url") if repos else None) or ""
        branch = repos[0].get("branch") if repos else None
        input_spec = self.artifact_store.retrieve_artifact(job_id, "input_spec") or {}
        story_key = input_spec.get("story_key")
        return await self.sandbox_pipeline.execute_apply_to_pr(
            job_id=job_id,
            approved_plan=approved_plan,
            repo_url=repo_url,
            branch=branch,
            story_key=story_key,
            destination_branch="main",
            cancellation_event=cancellation_event,
            on_sandbox_created=on_sandbox_created,
            on_sandbox_released=on_sandbox_released,
        )

    async def execute_pipeline(
        self,
        job_id: str,
        story_key: str,
        story_summary: str,
        story_description: Optional[str],
        repos: List[Dict[str, Any]],
        scope: Optional[Dict[str, Any]] = None,
        additional_context: Optional[str] = None,
        mode: str = "normal",
        cancellation_event: Optional[Any] = None,
        on_sandbox_created: Optional[Callable[[str, str], Any]] = None,
        on_sandbox_released: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the complete pipeline.

        Args:
            job_id: Job identifier
            story_key: JIRA story key
            story_summary: Story summary
            story_description: Story description
            repos: List of repositories
            scope: Optional scope constraints
            additional_context: Additional context
            mode: Pipeline mode ("normal" or "yolo")
            cancellation_event: Cancellation event
            on_sandbox_created: Optional callback (job_id, sandbox_id) when a sandbox is created (APPLY stage)
            on_sandbox_released: Optional callback (job_id) when the sandbox is released

        Returns:
            Dict with pipeline results
        """
        current_stage = PipelineStage.CREATED
        plan_versions = []
        approved_plan_hash = None
        workspace_fingerprint = None
        
        try:
            # Store input spec
            input_spec = {
                "story_key": story_key,
                "story_summary": story_summary,
                "story_description": story_description,
                "repos": repos,
                "scope": scope,
                "additional_context": additional_context,
                "mode": mode
            }
            self.artifact_store.store_artifact(job_id, "input_spec", input_spec)
            
            # Workspace fingerprint can be derived from repos/scope without a real workspace.
            workspace_fingerprint = self._generate_workspace_fingerprint(repos, scope)
            self.artifact_store.store_artifact(job_id, "workspace_fingerprint", workspace_fingerprint.dict())
            
            # STAGE 1: PLANNING
            # Code-aware planning requires OpenSandbox (sandbox_runner). Without repos, LLM-only planning is used.
            current_stage = PipelineStage.PLANNING
            logger.info(f"Job {job_id}: Starting PLANNING stage")
            
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError(f"Job {job_id} was cancelled during PLANNING stage")
            
            if repos and not self.sandbox_runner:
                raise ValueError(
                    "OpenSandbox is required for code-aware Draft PR when repos are provided. "
                    "Enable OPENSANDBOX_ENABLED and ensure the worker has sandbox configured."
                )
            
            workspace_path = None
            if self.sandbox_runner and repos:
                # Sandbox planning: run plan generation inside OpenSandbox.
                prompt = self.plan_generator.build_plan_prompt(
                    story_key=story_key,
                    story_summary=story_summary,
                    story_description=story_description,
                    scope=scope,
                    repos=repos,
                    additional_context=additional_context,
                )
                repo_url = repos[0].get("url", repos[0]) if isinstance(repos[0], dict) else repos[0]
                branch = repos[0].get("branch") if isinstance(repos[0], dict) else None
                result = await self.sandbox_runner.execute_plan_generation(
                    job_id=job_id,
                    repo_url=repo_url,
                    branch=branch,
                    prompt=prompt,
                    cancellation_event=cancellation_event,
                )
                if isinstance(result, dict) and "plan" in result and isinstance(result["plan"], dict):
                    plan_dict = result["plan"]
                elif isinstance(result, dict) and result.get("summary") and result.get("scope"):
                    plan_dict = result
                else:
                    raise PlanGeneratorError(
                        f"Sandbox plan generation returned unexpected structure: keys={list(result.keys()) if isinstance(result, dict) else type(result)}"
                    )
                plan_v1 = self.plan_generator.post_process_plan(plan_dict, repos, generated_by="opencode")
            else:
                # LLM-only planning (no repos or sandbox not used).
                plan_v1 = await self.plan_generator.generate_plan(
                    job_id=job_id,
                    story_key=story_key,
                    story_summary=story_summary,
                    story_description=story_description,
                    scope=scope,
                    repos=repos,
                    additional_context=additional_context,
                    use_opencode=False,
                    workspace_path=None,
                    cancellation_event=cancellation_event,
                )
            
            if cancellation_event and cancellation_event.is_set():
                if workspace_path is not None:
                    await self.workspace_manager.cleanup_workspace(job_id)
                raise asyncio.CancelledError(f"Job {job_id} was cancelled after plan generation")
            
            plan_versions.append(plan_v1)
            self.artifact_store.store_artifact(job_id, f"plan_v{plan_v1.version}", plan_v1.dict())
            
            logger.info(f"Job {job_id}: Generated plan v1, hash: {plan_v1.plan_hash[:8]}")
            
            # STAGE 2: APPROVAL (or YOLO auto-approval)
            current_stage = PipelineStage.WAITING_FOR_APPROVAL
            
            if mode == "yolo" and self.yolo_policy_config:
                # Evaluate YOLO policy
                yolo_evaluator = YOLOPolicyEvaluator(self.yolo_policy_config)
                evaluation = yolo_evaluator.evaluate(plan_v1.plan_spec)
                
                if evaluation["compliant"]:
                    # Auto-approve
                    approved_plan_hash = plan_v1.plan_hash
                    logger.info(f"Job {job_id}: YOLO auto-approval granted")
                else:
                    # Fall back to normal approval
                    logger.info(f"Job {job_id}: YOLO policy not compliant, waiting for approval")
                    return {
                        "stage": current_stage,
                        "plan_versions": [pv.dict() for pv in plan_versions],
                        "yolo_evaluation": evaluation,
                        "requires_approval": True
                    }
            else:
                # Normal mode - requires approval
                logger.info(f"Job {job_id}: Waiting for approval")
                return {
                    "stage": current_stage,
                    "plan_versions": [pv.dict() for pv in plan_versions],
                    "requires_approval": True
                }
            
            # If we get here, plan is approved (either YOLO or manual)
            # Continue with APPLY stage. When planning was done in sandbox, workspace_path is None;
            # delegate to _execute_from_apply_stage which uses sandbox_pipeline when set.
            if workspace_path is None:
                apply_result = await self._execute_from_apply_stage(
                    job_id=job_id,
                    approved_plan=plan_v1,
                    workspace_path=None,
                    repos=repos,
                    cancellation_event=cancellation_event,
                    on_sandbox_created=on_sandbox_created,
                    on_sandbox_released=on_sandbox_released,
                )
                return {
                    "stage": apply_result.get("stage", PipelineStage.COMPLETED),
                    "plan_versions": [pv.dict() for pv in plan_versions],
                    "approved_plan_hash": approved_plan_hash,
                    "workspace_fingerprint": workspace_fingerprint.dict() if workspace_fingerprint else None,
                    **{k: v for k, v in apply_result.items() if k not in ("stage",)},
                }
            
        except asyncio.CancelledError as e:
            current_stage = PipelineStage.FAILED
            logger.info(f"Job {job_id}: Pipeline cancelled at stage {current_stage}: {e}")
            # Workspace cleanup handled by caller
            raise  # Re-raise to propagate cancellation
        
        except Exception as e:
            current_stage = PipelineStage.FAILED
            logger.error(f"Job {job_id}: Pipeline failed at stage {current_stage}: {e}", exc_info=True)
            
            # Cleanup workspace on failure (optional - artifacts are preserved)
            # Workspace cleanup can be done later via cleanup job
            # We preserve workspace for debugging
            
            return {
                "stage": current_stage,
                "error": str(e),
                "plan_versions": [pv.dict() for pv in plan_versions] if plan_versions else None
            }
    
    def _generate_workspace_fingerprint(
        self,
        repos: List[Dict[str, Any]],
        scope: Optional[Dict[str, Any]]
    ) -> WorkspaceFingerprint:
        """Generate workspace fingerprint"""
        import hashlib
        import json
        
        # Build fingerprint data
        fingerprint_data = {
            "repos": repos,
            "selected_paths": scope.get("files", []) if scope else []
        }
        
        # Calculate hash
        canonical_json = json.dumps(fingerprint_data, sort_keys=True)
        fingerprint_hash = hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
        
        return WorkspaceFingerprint(
            repos=repos,
            selected_paths=[f.get("path") for f in scope.get("files", [])] if scope else None,
            fingerprint_hash=fingerprint_hash
        )
