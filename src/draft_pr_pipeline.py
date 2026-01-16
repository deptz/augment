"""
Draft PR Pipeline
Orchestrates the complete PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR workflow
"""
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

from .draft_pr_models import PlanVersion, PlanFeedback, Approval, WorkspaceFingerprint, FeedbackType
from .plan_generator import PlanGenerator, PlanGeneratorError, PlanValidationError
from .yolo_policy import YOLOPolicyEvaluator
from .code_applier import CodeApplier, CodeApplierError, PlanApplyGuardError
from .verifier import Verifier
from .package_service import PackageService
from .draft_pr_creator import DraftPRCreator, DraftPRCreatorError
from .workspace_manager import WorkspaceManager
from .artifact_store import ArtifactStore
from .opencode_runner import OpenCodeRunner
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
        opencode_runner: Optional[OpenCodeRunner] = None,
        llm_client: Optional[LLMClient] = None,
        bitbucket_client: Optional[BitbucketClient] = None,
        yolo_policy: Optional[Dict[str, Any]] = None,
        verification_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize pipeline.
        
        Args:
            plan_generator: Plan generator service
            workspace_manager: Workspace manager
            artifact_store: Artifact store
            opencode_runner: OpenCode runner (optional)
            llm_client: LLM client (optional)
            bitbucket_client: Bitbucket client (optional)
            yolo_policy: YOLO policy configuration (optional)
            verification_config: Verification configuration (optional)
        """
        self.plan_generator = plan_generator
        self.workspace_manager = workspace_manager
        self.artifact_store = artifact_store
        self.opencode_runner = opencode_runner
        self.llm_client = llm_client
        self.bitbucket_client = bitbucket_client
        self.yolo_policy_config = yolo_policy
        self.verification_config = verification_config or {}
    
    async def continue_pipeline_after_approval(
        self,
        job_id: str,
        approved_plan_hash: str,
        cancellation_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Continue pipeline execution after plan approval.
        
        Resumes from APPLY stage with the approved plan.
        
        Args:
            job_id: Job identifier
            approved_plan_hash: Hash of the approved plan
            cancellation_event: Cancellation event
            
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
        
        # Get workspace path
        workspace_path = self.workspace_manager.get_workspace_path(job_id)
        if not workspace_path.exists():
            raise ValueError(f"Workspace not found for job {job_id}. Workspace may have been deleted or job was never started.")
        
        # Verify workspace still has repos
        repos_in_workspace = self.workspace_manager.list_repos_in_workspace(job_id)
        if not repos_in_workspace:
            raise ValueError(f"Workspace for job {job_id} has no repositories. Workspace may be corrupted.")
        
        repos = input_spec.get('repos', [])
        
        # Continue from APPLY stage
        return await self._execute_from_apply_stage(
            job_id=job_id,
            approved_plan=approved_plan,
            workspace_path=workspace_path,
            repos=repos,
            cancellation_event=cancellation_event
        )
    
    async def _execute_from_apply_stage(
        self,
        job_id: str,
        approved_plan: PlanVersion,
        workspace_path: Path,
        repos: List[Dict[str, Any]],
        cancellation_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Execute pipeline from APPLY stage onwards"""
        current_stage = PipelineStage.APPLYING
        
        try:
            # STAGE 3: APPLY
            logger.info(f"Job {job_id}: Starting APPLY stage")
            
            if not self.opencode_runner:
                raise ValueError("OpenCode runner required for APPLY stage")
            
            code_applier = CodeApplier(workspace_path)
            apply_results = await code_applier.apply_plan(
                plan_version=approved_plan,
                opencode_runner=self.opencode_runner,
                job_id=job_id,
                cancellation_event=cancellation_event
            )
            
            # Store git diff
            git_diff = apply_results.get("git_diff", "")
            self.artifact_store.store_artifact(job_id, "git_diff", git_diff)
            
            logger.info(f"Job {job_id}: Applied changes, {len(apply_results.get('changed_files', []))} files changed")
            
            # STAGE 4: VERIFY
            current_stage = PipelineStage.VERIFYING
            logger.info(f"Job {job_id}: Starting VERIFY stage")
            
            verifier = Verifier(
                test_command=self.verification_config.get("test_command"),
                lint_command=self.verification_config.get("lint_command"),
                build_command=self.verification_config.get("build_command")
            )
            
            verification_results = await verifier.verify(
                workspace_path=workspace_path,
                plan_spec=approved_plan.plan_spec,
                repos=repos
            )
            
            self.artifact_store.store_artifact(job_id, "validation_logs", verification_results)
            
            if not verification_results.get("passed"):
                current_stage = PipelineStage.FAILED
                return {
                    "stage": current_stage,
                    "error": "Verification failed",
                    "verification_results": verification_results
                }
            
            logger.info(f"Job {job_id}: Verification passed")
            
            # STAGE 5: PACKAGE
            current_stage = PipelineStage.PACKAGING
            logger.info(f"Job {job_id}: Starting PACKAGE stage")
            
            package_service = PackageService(workspace_path)
            package_results = package_service.package(approved_plan, verification_results)
            
            self.artifact_store.store_artifact(job_id, "pr_metadata", package_results["pr_metadata"])
            
            logger.info(f"Job {job_id}: Packaged changes for PR")
            
            # STAGE 6: DRAFT_PR
            current_stage = PipelineStage.DRAFTING
            logger.info(f"Job {job_id}: Starting DRAFT_PR stage")
            
            if not self.bitbucket_client:
                raise ValueError("Bitbucket client required for DRAFT_PR stage")
            
            # Get story_key from input_spec for PR linking
            input_spec = self.artifact_store.retrieve_artifact(job_id, "input_spec")
            story_key = input_spec.get('story_key') if input_spec else None
            
            draft_pr_creator = DraftPRCreator(workspace_path, self.bitbucket_client)
            pr_results = draft_pr_creator.create_draft_pr(
                plan_version=approved_plan,
                pr_metadata=package_results["pr_metadata"],
                job_id=job_id,
                ticket_key=story_key
            )
            
            self.artifact_store.store_artifact(job_id, "pr_metadata", {
                **package_results["pr_metadata"],
                **pr_results
            })
            
            # STAGE 7: COMPLETED
            current_stage = PipelineStage.COMPLETED
            logger.info(f"Job {job_id}: Pipeline completed, PR #{pr_results.get('pr_id')} created")
            
            return {
                "stage": current_stage,
                "approved_plan_hash": approved_plan.plan_hash,
                "apply_results": apply_results,
                "verification_results": verification_results,
                "pr_results": pr_results
            }
            
        except Exception as e:
            current_stage = PipelineStage.FAILED
            logger.error(f"Job {job_id}: Pipeline failed at stage {current_stage}: {e}", exc_info=True)
            
            return {
                "stage": current_stage,
                "error": str(e)
            }
    
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
        cancellation_event: Optional[Any] = None
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
            
            # STAGE 1: PLANNING
            current_stage = PipelineStage.PLANNING
            logger.info(f"Job {job_id}: Starting PLANNING stage")
            
            # Create workspace
            workspace_path = await self.workspace_manager.create_workspace(job_id, repos)
            
            # Generate workspace fingerprint
            workspace_fingerprint = self._generate_workspace_fingerprint(repos, scope)
            self.artifact_store.store_artifact(job_id, "workspace_fingerprint", workspace_fingerprint.dict())
            
            # Generate plan
            use_opencode = bool(repos and self.opencode_runner)
            plan_v1 = await self.plan_generator.generate_plan(
                job_id=job_id,
                story_key=story_key,
                story_summary=story_summary,
                story_description=story_description,
                scope=scope,
                repos=repos,
                additional_context=additional_context,
                use_opencode=use_opencode,
                workspace_path=workspace_path,
                cancellation_event=cancellation_event
            )
            
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
            # Continue with APPLY stage
            
            # STAGE 3: APPLY
            current_stage = PipelineStage.APPLYING
            logger.info(f"Job {job_id}: Starting APPLY stage")
            
            if not self.opencode_runner:
                raise ValueError("OpenCode runner required for APPLY stage")
            
            code_applier = CodeApplier(workspace_path)
            apply_results = await code_applier.apply_plan(
                plan_version=plan_v1,
                opencode_runner=self.opencode_runner,
                job_id=job_id,
                cancellation_event=cancellation_event
            )
            
            # Store git diff
            git_diff = apply_results.get("git_diff", "")
            self.artifact_store.store_artifact(job_id, "git_diff", git_diff)
            
            logger.info(f"Job {job_id}: Applied changes, {len(apply_results.get('changed_files', []))} files changed")
            
            # STAGE 4: VERIFY
            current_stage = PipelineStage.VERIFYING
            logger.info(f"Job {job_id}: Starting VERIFY stage")
            
            verifier = Verifier(
                test_command=self.verification_config.get("test_command"),
                lint_command=self.verification_config.get("lint_command"),
                build_command=self.verification_config.get("build_command")
            )
            
            verification_results = await verifier.verify(
                workspace_path=workspace_path,
                plan_spec=plan_v1.plan_spec,
                repos=repos
            )
            
            self.artifact_store.store_artifact(job_id, "validation_logs", verification_results)
            
            if not verification_results.get("passed"):
                current_stage = PipelineStage.FAILED
                return {
                    "stage": current_stage,
                    "error": "Verification failed",
                    "verification_results": verification_results
                }
            
            logger.info(f"Job {job_id}: Verification passed")
            
            # STAGE 5: PACKAGE
            current_stage = PipelineStage.PACKAGING
            logger.info(f"Job {job_id}: Starting PACKAGE stage")
            
            package_service = PackageService(workspace_path)
            package_results = package_service.package(plan_v1, verification_results)
            
            self.artifact_store.store_artifact(job_id, "pr_metadata", package_results["pr_metadata"])
            
            logger.info(f"Job {job_id}: Packaged changes for PR")
            
            # STAGE 6: DRAFT_PR
            current_stage = PipelineStage.DRAFTING
            logger.info(f"Job {job_id}: Starting DRAFT_PR stage")
            
            if not self.bitbucket_client:
                raise ValueError("Bitbucket client required for DRAFT_PR stage")
            
            draft_pr_creator = DraftPRCreator(workspace_path, self.bitbucket_client)
            pr_results = draft_pr_creator.create_draft_pr(
                plan_version=plan_v1,
                pr_metadata=package_results["pr_metadata"],
                job_id=job_id,
                ticket_key=story_key
            )
            
            self.artifact_store.store_artifact(job_id, "pr_metadata", {
                **package_results["pr_metadata"],
                **pr_results
            })
            
            # STAGE 7: COMPLETED
            current_stage = PipelineStage.COMPLETED
            logger.info(f"Job {job_id}: Pipeline completed, PR #{pr_results.get('pr_id')} created")
            
            return {
                "stage": current_stage,
                "plan_versions": [pv.dict() for pv in plan_versions],
                "approved_plan_hash": approved_plan_hash,
                "workspace_fingerprint": workspace_fingerprint.dict() if workspace_fingerprint else None,
                "apply_results": apply_results,
                "verification_results": verification_results,
                "pr_results": pr_results
            }
            
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
