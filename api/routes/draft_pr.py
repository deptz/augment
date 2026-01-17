"""
Draft PR Routes
API endpoints for draft PR orchestrator
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from datetime import datetime
from collections import Counter
import logging
import uuid
import json
import re

from ..models.draft_pr import (
    CreateDraftPRRequest,
    RevisePlanRequest,
    ApprovePlanRequest,
    PlanRevisionResponse,
    PlanComparisonResponse,
    StructuredPlanComparison,
    RetryJobRequest,
    ProgressResponse,
    StoryValidationResponse,
    RepoValidationRequest,
    RepoValidationResponse,
    ArtifactMetadata,
    TemplateCreateRequest,
    TemplateUpdateRequest,
    TemplateResponse,
    TemplateSummary,
    BulkCreateRequest,
    BulkApproveRequest,
    BulkResponse,
    AnalyticsStats,
    JobAnalyticsRequest
)
from ..models.generation import JobStatus, PipelineStage
from ..dependencies import get_config, get_jira_client, jobs
from ..auth import get_current_user
from ..job_queue import get_redis_pool
from src.draft_pr_models import PlanFeedback, FeedbackType, Approval
from src.draft_pr_pipeline import DraftPRPipeline, PipelineStage as PipelineStageEnum
from src.plan_generator import PlanGenerator
from src.plan_comparator import PlanComparator
from src.workspace_manager import WorkspaceManager
from src.artifact_store import ArtifactStore, get_artifact_store
from src.opencode_runner import OpenCodeRunner
from src.llm_client import LLMClient
from src.bitbucket_client import BitbucketClient
from src.template_store import get_template_store
from src.analytics import AnalyticsService

router = APIRouter()
logger = logging.getLogger(__name__)

# UUID validation pattern
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

def _validate_job_id(job_id: str) -> str:
    """Validate and sanitize job_id to prevent path traversal"""
    if not job_id:
        raise HTTPException(status_code=400, detail="Job ID cannot be empty")
    
    # Sanitize to prevent path traversal
    safe_job_id = job_id.replace('/', '_').replace('\\', '_').replace('..', '_')
    safe_job_id = safe_job_id.replace('\x00', '_')
    safe_job_id = safe_job_id.strip('. ')
    
    if not safe_job_id:
        raise HTTPException(status_code=400, detail="Invalid job ID format")
    
    # Validate UUID format (job IDs should be UUIDs)
    if not UUID_PATTERN.match(safe_job_id):
        # Not a strict UUID, but allow it if it's safe (for backward compatibility)
        # Just ensure it doesn't contain dangerous characters
        if len(safe_job_id) > 100:
            raise HTTPException(status_code=400, detail="Job ID too long (max 100 characters)")
    
    return safe_job_id

def _validate_template_id(template_id: str) -> str:
    """Validate and sanitize template_id"""
    if not template_id:
        raise HTTPException(status_code=400, detail="Template ID cannot be empty")
    
    # Sanitize to prevent path traversal
    safe_template_id = template_id.replace('/', '_').replace('\\', '_').replace('..', '_')
    safe_template_id = safe_template_id.replace('\x00', '_')
    safe_template_id = safe_template_id.strip('. ')
    
    if not safe_template_id:
        raise HTTPException(status_code=400, detail="Invalid template ID format")
    
    # Validate UUID format
    if not UUID_PATTERN.match(safe_template_id):
        if len(safe_template_id) > 100:
            raise HTTPException(status_code=400, detail="Template ID too long (max 100 characters)")
    
    return safe_template_id


def _get_draft_pr_pipeline() -> DraftPRPipeline:
    """Get or create draft PR pipeline instance"""
    config = get_config()
    
    # Initialize services
    artifact_store = get_artifact_store()
    
    # Get OpenCode runner if available
    opencode_runner = None
    try:
        opencode_config = config.get_opencode_config()
        if opencode_config.get('enabled'):
            opencode_runner = OpenCodeRunner(
                docker_image=opencode_config.get('docker_image'),
                job_timeout_minutes=opencode_config.get('job_timeout_minutes', 20),
                max_result_size_mb=opencode_config.get('max_result_size_mb', 10),
                result_file=opencode_config.get('result_file', 'result.json'),
                llm_config=config.get_llm_config() if hasattr(config, 'get_llm_config') else config._config.get('llm', {})
            )
            opencode_runner.set_concurrency_limit(opencode_config.get('max_concurrent', 2))
    except Exception as e:
        logger.warning(f"OpenCode runner not available: {e}")
    
    # Get LLM client
    llm_client = None
    try:
        from ..utils import create_custom_llm_client
        llm_client = create_custom_llm_client()
    except Exception as e:
        logger.warning(f"LLM client not available: {e}")
    
    # Get workspace manager
    git_creds = config.get_git_credentials()
    opencode_config = config.get_opencode_config()
    workspace_manager = WorkspaceManager(
        git_username=git_creds.get('username'),
        git_password=git_creds.get('password'),
        clone_timeout_seconds=opencode_config.get('clone_timeout_seconds', 300),
        shallow_clone=opencode_config.get('shallow_clone', True)
    )
    
    # Get Bitbucket client
    bitbucket_client = None
    try:
        bitbucket_config = config._config.get('bitbucket', {})
        if bitbucket_config.get('email') and bitbucket_config.get('api_token'):
            bitbucket_client = BitbucketClient(
                workspaces=bitbucket_config.get('workspaces', []),
                email=bitbucket_config.get('email'),
                api_token=bitbucket_config.get('api_token'),
                jira_server_url=config._config.get('jira', {}).get('server_url')
            )
    except Exception as e:
        logger.warning(f"Bitbucket client not available: {e}")
    
    # Get plan generator
    plan_generator = PlanGenerator(
        llm_client=llm_client,
        opencode_runner=opencode_runner,
        workspace_manager=workspace_manager
    )
    
    # Get YOLO policy and verification config
    draft_pr_config = config._config.get('draft_pr', {})
    yolo_policy = draft_pr_config.get('yolo_policy')
    verification_config = draft_pr_config.get('verification', {})
    
    return DraftPRPipeline(
        plan_generator=plan_generator,
        workspace_manager=workspace_manager,
        artifact_store=artifact_store,
        opencode_runner=opencode_runner,
        llm_client=llm_client,
        bitbucket_client=bitbucket_client,
        yolo_policy=yolo_policy,
        verification_config=verification_config
    )


@router.post("/draft-pr/create",
          tags=["Draft PR"],
          summary="Create new draft PR job",
          description="Create a new draft PR orchestrator job. Returns job_id for status tracking.")
async def create_draft_pr(
    request: CreateDraftPRRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new draft PR job"""
    # Check for duplicate active job (same story key)
    from ..dependencies import get_active_job_for_ticket, register_ticket_job
    active_job_id = get_active_job_for_ticket(request.story_key)
    if active_job_id:
        if active_job_id in jobs:
            active_job = jobs[active_job_id]
            # Only prevent if job is still active (not completed/failed)
            if active_job.status in ["created", "processing", "started"]:
                raise HTTPException(
                    status_code=409,
                    detail=f"Story {request.story_key} is already being processed in job {active_job_id}",
                    headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                )
    
    job_id = str(uuid.uuid4())
    
    # Create job status
    job = JobStatus(
        job_id=job_id,
        job_type="draft_pr",
        status="started",
        progress={"message": "Creating draft PR job..."},
        started_at=datetime.now(),
        stage=PipelineStageEnum.CREATED.value,
        ticket_key=request.story_key,
        mode=request.mode
    )
    jobs[job_id] = job
    
    # Register story key for duplicate prevention
    register_ticket_job(request.story_key, job_id)
    
    # Queue job for processing
    try:
        from ..job_queue import get_redis_pool
        from arq import ArqRedis
        
        redis_pool = await get_redis_pool()
        await redis_pool.enqueue_job(
            'process_draft_pr_worker',
            job_id=job_id,
            story_key=request.story_key,
            story_summary="",  # Will be fetched from JIRA
            story_description=None,
            repos=request.repos,
            scope=request.scope,
            additional_context=request.additional_context,
            mode=request.mode
        )
        
        job.stage = PipelineStageEnum.PLANNING.value
        job.status = "processing"
        job.progress = {"message": "Planning stage started"}
        
        return {
            "job_id": job_id,
            "status": "processing",
            "stage": PipelineStageEnum.PLANNING.value,
            "status_url": f"/jobs/{job_id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue draft PR job: {e}")
        job.status = "failed"
        job.error = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to create job: {e}")


@router.get("/draft-pr/jobs/{job_id}",
          tags=["Draft PR"],
          summary="Get draft PR job status",
          description="Get the status and current stage of a draft PR job.")
async def get_draft_pr_job(
    job_id: str,
    current_user: str = Depends(get_current_user)
):
    """Get draft PR job status"""
    job_id = _validate_job_id(job_id)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return job


@router.get("/draft-pr/jobs/{job_id}/plan",
          tags=["Draft PR"],
          summary="Get latest plan",
          description="Get the latest plan version for a job.")
async def get_latest_plan(
    job_id: str,
    current_user: str = Depends(get_current_user)
):
    """Get latest plan"""
    job_id = _validate_job_id(job_id)
    artifact_store = get_artifact_store()
    
    # Find latest plan version
    artifacts = artifact_store.list_artifacts(job_id)
    plan_versions = [a for a in artifacts if a.startswith('plan_v')]
    
    if not plan_versions:
        raise HTTPException(status_code=404, detail="No plans found for this job")
    
    # Get latest version
    latest_version = max(plan_versions, key=lambda x: int(x.split('_v')[1]))
    plan = artifact_store.retrieve_artifact(job_id, latest_version)
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    return plan


@router.get("/draft-pr/jobs/{job_id}/plans",
          tags=["Draft PR"],
          summary="List all plan versions",
          description="Get a list of all plan versions with metadata (version, hash, created_at).")
async def list_plan_versions(
    job_id: str,
    current_user: str = Depends(get_current_user)
):
    """List all plan versions with metadata"""
    job_id = _validate_job_id(job_id)
    artifact_store = get_artifact_store()
    
    # Find all plan versions
    artifacts = artifact_store.list_artifacts(job_id)
    plan_versions = [a for a in artifacts if a.startswith('plan_v')]
    
    if not plan_versions:
        return {
            "job_id": job_id,
            "plans": []
        }
    
    # Get metadata for each plan version
    plans_summary = []
    for plan_name in sorted(plan_versions, key=lambda x: int(x.split('_v')[1])):
        try:
            version_num = int(plan_name.split('_v')[1])
            plan_dict = artifact_store.retrieve_artifact(job_id, plan_name)
            if plan_dict:
                plans_summary.append({
                    "version": version_num,
                    "plan_hash": plan_dict.get('plan_hash', ''),
                    "previous_version_hash": plan_dict.get('previous_version_hash'),
                    "generated_by": plan_dict.get('generated_by', 'unknown'),
                    "summary": plan_dict.get('plan_spec', {}).get('summary', '') if isinstance(plan_dict.get('plan_spec'), dict) else ''
                })
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse plan version {plan_name}: {e}")
            continue
    
    return {
        "job_id": job_id,
        "plans": plans_summary
    }


@router.get("/draft-pr/jobs/{job_id}/plans/{version}",
          tags=["Draft PR"],
          summary="Get specific plan version",
          description="Get a specific plan version by version number. Returns the complete plan specification with all sections including summary, scope, files, tests, edge cases, assumptions, unknowns, and rollback strategy. Use this endpoint to view full plan details for any version.")
async def get_plan_version(
    job_id: str,
    version: int,
    current_user: str = Depends(get_current_user)
):
    """
    Get specific plan version with full details.
    
    Returns the complete plan specification including:
    - plan_spec: Full plan specification with all sections
    - plan_hash: Hash of the plan for verification
    - version: Plan version number
    - previous_version_hash: Hash of previous version (if any)
    - generated_by: Method used to generate the plan (LLM or OpenCode)
    """
    job_id = _validate_job_id(job_id)
    if version < 1:
        raise HTTPException(status_code=400, detail="Version must be >= 1")
    artifact_store = get_artifact_store()
    plan = artifact_store.retrieve_artifact(job_id, f"plan_v{version}")
    
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan v{version} not found")
    
    # Ensure we return the full plan spec
    # The artifact should already contain the complete plan_spec
    if isinstance(plan, dict) and 'plan_spec' in plan:
        # Plan is already in correct format
        return plan
    elif isinstance(plan, dict):
        # Plan might be stored directly as plan_spec
        return {
            "version": version,
            "plan_spec": plan,
            "plan_hash": plan.get('plan_hash', ''),
            "previous_version_hash": plan.get('previous_version_hash'),
            "generated_by": plan.get('generated_by', 'unknown')
        }
    else:
        # Fallback - return as-is
        return plan


@router.post("/draft-pr/jobs/{job_id}/revise-plan",
          tags=["Draft PR"],
          summary="Revise plan based on feedback",
          description="Submit feedback to generate a new plan version.")
async def revise_plan(
    job_id: str,
    request: RevisePlanRequest,
    current_user: str = Depends(get_current_user)
):
    """Revise plan based on feedback"""
    job_id = _validate_job_id(job_id)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    # Check job is in WAITING_FOR_APPROVAL stage
    if job.stage != PipelineStageEnum.WAITING_FOR_APPROVAL.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job must be in WAITING_FOR_APPROVAL stage, current: {job.stage}"
        )
    
    # Safety: Prevent revision if plan is already approved
    if job.approved_plan_hash:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot revise plan - plan with hash {job.approved_plan_hash[:8]}... is already approved. "
                   f"Job is in {job.stage} stage. Please cancel approval first or wait for job to complete."
        )
    
    # Get latest plan
    artifact_store = get_artifact_store()
    artifacts = artifact_store.list_artifacts(job_id)
    plan_versions = [a for a in artifacts if a.startswith('plan_v')]
    
    if not plan_versions:
        raise HTTPException(status_code=404, detail="No plans found")
    
    latest_version_name = max(plan_versions, key=lambda x: int(x.split('_v')[1]))
    latest_version_num = int(latest_version_name.split('_v')[1])
    
    plan_dict = artifact_store.retrieve_artifact(job_id, latest_version_name)
    if not plan_dict:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Reconstruct PlanVersion with error handling for corrupted data
    try:
        from src.draft_pr_models import PlanVersion, PlanSpec
        plan_spec_data = plan_dict.get('plan_spec', plan_dict)
        plan_spec = PlanSpec(**plan_spec_data)
        
        # Verify plan hash integrity
        from src.draft_pr_schemas import calculate_plan_hash
        stored_hash = plan_dict.get('plan_hash', '')
        calculated_hash = calculate_plan_hash(plan_spec_data)
        if stored_hash and calculated_hash != stored_hash:
            logger.error(f"Plan hash mismatch for {latest_version_name}: stored={stored_hash[:8]}, calculated={calculated_hash[:8]}")
            raise HTTPException(
                status_code=500,
                detail=f"Plan artifact {latest_version_name} is corrupted (hash mismatch). Cannot revise."
            )
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f"Failed to reconstruct PlanVersion from artifact {latest_version_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Plan artifact {latest_version_name} is corrupted or invalid: {e}"
        )
    previous_version = PlanVersion(
        version=latest_version_num,
        plan_spec=plan_spec,
        plan_hash=plan_dict.get('plan_hash', ''),
        previous_version_hash=plan_dict.get('previous_version_hash'),
        generated_by=plan_dict.get('generated_by')
    )
    
    # Create feedback
    feedback = PlanFeedback(
        feedback_text=request.feedback,
        specific_concerns=request.specific_concerns,
        requested_changes=request.requested_changes,
        feedback_type=request.feedback_type,
        provided_by=current_user
    )
    
    # Generate revised plan
    pipeline = _get_draft_pr_pipeline()
    workspace_path = pipeline.workspace_manager.get_workspace_path(job_id)
    
    # Check if workspace exists - if not and OpenCode is needed, we can't revise
    workspace_exists = workspace_path.exists()
    use_opencode = bool(pipeline.opencode_runner)
    
    if use_opencode and not workspace_exists:
        # Workspace was deleted but OpenCode is required - try to recreate it
        logger.warning(f"Workspace for job {job_id} not found, attempting to recreate for plan revision")
        try:
            input_spec = artifact_store.retrieve_artifact(job_id, "input_spec")
            if input_spec and input_spec.get('repos'):
                workspace_path = await pipeline.workspace_manager.create_workspace(job_id, input_spec.get('repos'))
                workspace_exists = True
                logger.info(f"Recreated workspace for job {job_id} for plan revision")
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Workspace not found and cannot be recreated (no repos in input_spec). Cannot revise plan with OpenCode."
                )
        except Exception as e:
            logger.error(f"Failed to recreate workspace for plan revision: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Workspace not found and recreation failed: {e}. Cannot revise plan with OpenCode."
            )
    
    try:
        new_version = await pipeline.plan_generator.revise_plan(
            job_id=job_id,
            previous_version=previous_version,
            feedback=feedback,
            use_opencode=use_opencode and workspace_exists,
            workspace_path=workspace_path if workspace_exists else None
        )
        
        # Store new version
        artifact_store.store_artifact(job_id, f"plan_v{new_version.version}", new_version.dict())
        
        # Update job
        if not job.plan_versions:
            job.plan_versions = []
        job.plan_versions.append(new_version.dict())
        job.stage = PipelineStageEnum.WAITING_FOR_APPROVAL.value
        
        # Safety: Invalidate any previous approval if plan was revised
        # New plan hash means old approval is no longer valid
        if job.approved_plan_hash and job.approved_plan_hash != new_version.plan_hash:
            logger.info(f"Job {job_id}: Plan revised, invalidating previous approval")
            job.approved_plan_hash = None
        
        # Persist job status to Redis after revision
        try:
            from ..job_queue import persist_job_status
            await persist_job_status(job_id, job.dict())
        except Exception as e:
            logger.warning(f"Failed to persist job status after plan revision: {e}")
        
        # Compare versions
        comparator = PlanComparator()
        comparison = comparator.compare_plans(previous_version, new_version)
        
        return PlanRevisionResponse(
            plan_version=new_version.version,
            plan_hash=new_version.plan_hash,
            changes_summary=comparison.summary
        )
        
    except Exception as e:
        logger.error(f"Failed to revise plan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to revise plan: {e}")


@router.get("/draft-pr/jobs/{job_id}/plans/compare",
          tags=["Draft PR"],
          summary="Compare two plan versions",
          description="Compare two plan versions and get a diff. Supports format parameter: 'summary' (default), 'structured' (detailed), or 'unified' (unified diff format).")
async def compare_plans(
    job_id: str,
    from_version: int = Query(..., description="Source version number"),
    to_version: int = Query(..., description="Target version number"),
    format: str = Query("summary", description="Diff format: 'summary', 'structured', or 'unified'"),
    current_user: str = Depends(get_current_user)
):
    """Compare two plan versions"""
    job_id = _validate_job_id(job_id)
    if from_version < 1 or to_version < 1:
        raise HTTPException(status_code=400, detail="Version numbers must be >= 1")
    if format not in ["summary", "structured", "unified"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid format. Must be 'summary', 'structured', or 'unified'"
        )
    
    artifact_store = get_artifact_store()
    
    # Get both versions
    from_plan_dict = artifact_store.retrieve_artifact(job_id, f"plan_v{from_version}")
    to_plan_dict = artifact_store.retrieve_artifact(job_id, f"plan_v{to_version}")
    
    if not from_plan_dict or not to_plan_dict:
        raise HTTPException(status_code=404, detail="One or both plan versions not found")
    
    # Reconstruct PlanVersion objects
    from src.draft_pr_models import PlanVersion, PlanSpec
    from_spec = PlanSpec(**from_plan_dict.get('plan_spec', from_plan_dict))
    to_spec = PlanSpec(**to_plan_dict.get('plan_spec', to_plan_dict))
    
    from_version_obj = PlanVersion(
        version=from_version,
        plan_spec=from_spec,
        plan_hash=from_plan_dict.get('plan_hash', '')
    )
    to_version_obj = PlanVersion(
        version=to_version,
        plan_spec=to_spec,
        plan_hash=to_plan_dict.get('plan_hash', '')
    )
    
    # Compare
    comparator = PlanComparator()
    comparison = comparator.compare_plans(from_version_obj, to_version_obj)
    
    if format == "summary":
        # Return basic comparison
        return PlanComparisonResponse(
            from_version=comparison.from_version,
            to_version=comparison.to_version,
            changes=comparison.changes,
            summary=comparison.summary,
            changed_sections=comparison.changed_sections
        )
    elif format == "structured":
        # Return structured comparison with detailed diffs
        detailed = comparator.get_detailed_diff(from_version_obj, to_version_obj)
        
        # Extract file changes from scope if present
        file_changes = []
        if "scope" in comparison.changes.get("modified", {}):
            scope_mod = comparison.changes["modified"]["scope"]
            from_files = scope_mod.get("from", {}).get("files", [])
            to_files = scope_mod.get("to", {}).get("files", [])
            
            from_file_paths = {f.get("path", "") for f in from_files if isinstance(f, dict)}
            to_file_paths = {f.get("path", "") for f in to_files if isinstance(f, dict)}
            
            added_files = to_file_paths - from_file_paths
            removed_files = from_file_paths - to_file_paths
            modified_files = from_file_paths & to_file_paths
            
            for path in added_files:
                file_changes.append({"path": path, "change": "added"})
            for path in removed_files:
                file_changes.append({"path": path, "change": "removed"})
            for path in modified_files:
                file_changes.append({"path": path, "change": "modified"})
        
        # Count changes
        additions = len(comparison.changes.get("added", {}))
        deletions = len(comparison.changes.get("removed", {}))
        modifications = len(comparison.changes.get("modified", {}))
        
        # Convert section_diffs dict to list
        section_diffs_list = [
            {"section": section, "diff": diff}
            for section, diff in detailed.get("section_diffs", {}).items()
        ]
        
        return StructuredPlanComparison(
            from_version=comparison.from_version,
            to_version=comparison.to_version,
            summary=comparison.summary,
            changed_sections=comparison.changed_sections,
            file_changes=file_changes,
            section_diffs=section_diffs_list,
            additions=additions,
            deletions=deletions,
            modifications=modifications
        )
    else:  # unified
        # Return unified diff format (text-based)
        import difflib
        
        from_text = json.dumps(from_spec.dict(), indent=2, sort_keys=True)
        to_text = json.dumps(to_spec.dict(), indent=2, sort_keys=True)
        
        unified_diff = list(difflib.unified_diff(
            from_text.splitlines(keepends=True),
            to_text.splitlines(keepends=True),
            fromfile=f"plan_v{from_version}",
            tofile=f"plan_v{to_version}",
            lineterm=''
        ))
        
        return {
            "from_version": from_version,
            "to_version": to_version,
            "format": "unified",
            "diff": "".join(unified_diff)
        }


@router.post("/draft-pr/jobs/{job_id}/approve",
          tags=["Draft PR"],
          summary="Approve plan",
          description="Approve a plan to proceed to APPLY stage.")
async def approve_plan(
    job_id: str,
    request: ApprovePlanRequest,
    current_user: str = Depends(get_current_user)
):
    """Approve plan"""
    job_id = _validate_job_id(job_id)
    # Validate plan_hash format (should be hex string)
    if not request.plan_hash or not re.match(r'^[0-9a-f]{64}$', request.plan_hash, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid plan_hash format (expected 64-character hex string)")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    # Check if job was cancelled
    if job.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} has been cancelled and cannot be approved."
        )
    
    # Check for cancellation flag in Redis (in case job status hasn't been updated yet)
    from ..job_queue import is_job_cancelled
    if await is_job_cancelled(job_id):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} has been cancelled and cannot be approved."
        )
    
    # Check job is in WAITING_FOR_APPROVAL stage
    if job.stage != PipelineStageEnum.WAITING_FOR_APPROVAL.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job must be in WAITING_FOR_APPROVAL stage, current: {job.stage}"
        )
    
    # Safety: Prevent multiple approvals of same plan
    if job.approved_plan_hash == request.plan_hash:
        raise HTTPException(
            status_code=400,
            detail=f"Plan with hash {request.plan_hash[:8]}... is already approved. Pipeline should be executing."
        )
    
    # Acquire distributed lock for approval to prevent race conditions
    from ..job_queue import get_redis_pool
    import asyncio
    
    redis_pool = await get_redis_pool()
    lock_key = f"draft_pr:approval_lock:{job_id}"
    lock_timeout = 60  # Lock expires after 60 seconds (increased for network latency)
    
    # Try to acquire lock with timeout
    lock_acquired = False
    try:
        # Use SET with NX (only if not exists) and EX (expiration)
        lock_acquired = await redis_pool.set(lock_key, current_user, ex=lock_timeout, nx=True)
        
        if not lock_acquired:
            # Check if lock is held by another process
            lock_holder = await redis_pool.get(lock_key)
            raise HTTPException(
                status_code=409,
                detail=f"Another approval request is in progress for this job. Please wait and try again. (Lock held by: {lock_holder or 'unknown'})"
            )
        
        logger.info(f"Acquired approval lock for job {job_id} by user {current_user}")
        
        # Verify plan hash exists and matches latest plan
        artifact_store = get_artifact_store()
        artifacts = artifact_store.list_artifacts(job_id)
        plan_versions = [a for a in artifacts if a.startswith('plan_v')]
        
        if not plan_versions:
            raise HTTPException(status_code=404, detail="No plans found for this job")
        
        # Get latest plan version
        latest_version_name = max(plan_versions, key=lambda x: int(x.split('_v')[1]))
        latest_plan_dict = artifact_store.retrieve_artifact(job_id, latest_version_name)
        
        if not latest_plan_dict:
            raise HTTPException(status_code=404, detail="Latest plan not found")
        
        latest_plan_hash = latest_plan_dict.get('plan_hash')
        
        # Safety check: approved plan hash must match latest plan hash
        # This prevents approving an old plan version
        if request.plan_hash != latest_plan_hash:
            raise HTTPException(
                status_code=400,
                detail=f"Plan hash mismatch. Latest plan hash is {latest_plan_hash[:8]}..., but approval requested for {request.plan_hash[:8]}.... You must approve the latest plan version."
            )
        
        # Create approval record
        approval = Approval(
            job_id=job_id,
            plan_hash=request.plan_hash,
            approver=current_user
        )
        
        # Double-check: Verify job hasn't changed state (race condition protection)
        if job.stage != PipelineStageEnum.WAITING_FOR_APPROVAL.value:
            raise HTTPException(
                status_code=409,
                detail=f"Job state changed during approval. Current stage: {job.stage}. Please refresh and try again."
            )
        
        # Verify plan still exists and matches (prevent TOCTOU - Time Of Check Time Of Use)
        latest_plan_dict_check = artifact_store.retrieve_artifact(job_id, latest_version_name)
        if not latest_plan_dict_check or latest_plan_dict_check.get('plan_hash') != request.plan_hash:
            raise HTTPException(
                status_code=409,
                detail="Plan was modified during approval. Please refresh and approve the latest version."
            )
        
        # Update job (within lock)
        job.approved_plan_hash = request.plan_hash
        job.stage = PipelineStageEnum.APPLYING.value
        job.progress = {"message": "Plan approved, proceeding to APPLY stage"}
        
        # Persist job status to Redis before storing approval
        try:
            from ..job_queue import persist_job_status
            await persist_job_status(job_id, job.dict())
        except Exception as e:
            logger.warning(f"Failed to persist job status before approval: {e}")
        
        # Store approval
        try:
            artifact_store.store_artifact(job_id, "approval", approval.dict())
        except Exception as e:
            # Approval storage failed - rollback job state
            job.approved_plan_hash = None
            job.stage = PipelineStageEnum.WAITING_FOR_APPROVAL.value
            logger.error(f"Failed to store approval artifact for job {job_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to store approval: {e}"
            )
    finally:
        # Always release lock
        if lock_acquired:
            try:
                await redis_pool.delete(lock_key)
                logger.info(f"Released approval lock for job {job_id}")
            except Exception as e:
                logger.warning(f"Failed to release approval lock for job {job_id}: {e}")
    
    # Check for cancellation one more time before continuing pipeline
    from ..job_queue import is_job_cancelled
    if await is_job_cancelled(job_id):
        # Job was cancelled - rollback approval state
        job.approved_plan_hash = None
        job.stage = PipelineStageEnum.WAITING_FOR_APPROVAL.value
        job.progress = {"message": "Job was cancelled before pipeline continuation"}
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} was cancelled and cannot proceed with pipeline execution."
        )
    
    # Continue pipeline execution
    try:
        import asyncio
        pipeline = _get_draft_pr_pipeline()
        
        # Create cancellation event and monitor for cancellation
        cancellation_event = asyncio.Event()
        
        async def monitor_cancellation():
            """Monitor Redis for cancellation flag and set event when detected"""
            from ..job_queue import is_job_cancelled, clear_cancellation_flag
            while not cancellation_event.is_set():
                try:
                    if await is_job_cancelled(job_id):
                        cancellation_event.set()
                        await clear_cancellation_flag(job_id)
                        logger.info(f"Job {job_id} cancellation detected during approval continuation")
                        break
                    await asyncio.sleep(1)  # Check every second
                except Exception as e:
                    logger.warning(f"Error monitoring cancellation for job {job_id}: {e}")
                    await asyncio.sleep(1)
        
        # Start cancellation monitor
        monitor_task = asyncio.create_task(monitor_cancellation())
        
        try:
            results = await pipeline.continue_pipeline_after_approval(
                job_id=job_id,
                approved_plan_hash=request.plan_hash,
                cancellation_event=cancellation_event
            )
        finally:
            # Cancel monitor task
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        # Update job with results
        job.stage = results.get('stage', PipelineStageEnum.APPLYING.value)
        job.results = results
        
        if results.get('stage') == 'COMPLETED':
            job.status = "completed"
            job.completed_at = datetime.now()
            job.progress = {"message": f"Draft PR created: {results.get('pr_results', {}).get('pr_url', 'N/A')}"}
            # Cleanup workspace after successful completion
            workspace_path = pipeline.workspace_manager.get_workspace_path(job_id)
            if workspace_path.exists():
                await pipeline.workspace_manager.cleanup_workspace(job_id)
        elif results.get('stage') == 'FAILED':
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = results.get('error', 'Unknown error')
            job.progress = {"message": f"Pipeline failed: {results.get('error', 'Unknown error')}"}
            # Cleanup workspace on failure
            workspace_path = pipeline.workspace_manager.get_workspace_path(job_id)
            if workspace_path.exists():
                await pipeline.workspace_manager.cleanup_workspace(job_id)
        
        # Persist job status to Redis
        try:
            from ..job_queue import persist_job_status
            await persist_job_status(job_id, job.dict())
        except Exception as e:
            logger.warning(f"Failed to persist job status to Redis: {e}")
        
        return {
            "approved": True,
            "plan_hash": request.plan_hash,
            "stage": results.get('stage', PipelineStageEnum.APPLYING.value),
            "results": results
        }
        
    except asyncio.CancelledError as e:
        logger.info(f"Job {job_id} was cancelled during approval continuation: {e}")
        job.status = "cancelled"
        job.completed_at = datetime.now()
        job.progress = {"message": "Job was cancelled"}
        job.stage = "FAILED"
        
        # Cleanup workspace on cancellation
        try:
            pipeline = _get_draft_pr_pipeline()
            workspace_path = pipeline.workspace_manager.get_workspace_path(job_id)
            if workspace_path.exists():
                await pipeline.workspace_manager.cleanup_workspace(job_id)
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup workspace for job {job_id} after cancellation: {cleanup_error}")
        
        raise HTTPException(status_code=409, detail=f"Job was cancelled: {e}")
        
    except Exception as e:
        logger.error(f"Failed to continue pipeline after approval: {e}", exc_info=True)
        job.status = "failed"
        job.error = str(e)
        
        # Cleanup workspace on exception
        try:
            pipeline = _get_draft_pr_pipeline()
            workspace_path = pipeline.workspace_manager.get_workspace_path(job_id)
            if workspace_path.exists():
                await pipeline.workspace_manager.cleanup_workspace(job_id)
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup workspace for job {job_id} after approval exception: {cleanup_error}")
        
        raise HTTPException(status_code=500, detail=f"Failed to continue pipeline: {e}")


@router.get("/draft-pr/jobs/{job_id}/artifacts",
          tags=["Draft PR"],
          summary="List artifacts",
          description="List all artifacts for a job.")
async def list_artifacts(
    job_id: str,
    current_user: str = Depends(get_current_user)
):
    """List all artifacts"""
    job_id = _validate_job_id(job_id)
    artifact_store = get_artifact_store()
    artifacts = artifact_store.list_artifacts(job_id)
    
    return {
        "job_id": job_id,
        "artifacts": artifacts
    }


@router.get("/draft-pr/jobs/{job_id}/artifacts/{artifact_type}",
          tags=["Draft PR"],
          summary="Get artifact",
          description="Get a specific artifact by type.")
async def get_artifact(
    job_id: str,
    artifact_type: str,
    current_user: str = Depends(get_current_user)
):
    """Get specific artifact"""
    job_id = _validate_job_id(job_id)
    if not artifact_type or len(artifact_type) > 100:
        raise HTTPException(status_code=400, detail="Invalid artifact_type (empty or too long)")
    artifact_store = get_artifact_store()
    artifact = artifact_store.retrieve_artifact(job_id, artifact_type)
    
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_type} not found")
    
    return artifact


@router.get("/draft-pr/jobs/{job_id}/artifacts/{artifact_type}/metadata",
          tags=["Draft PR"],
          response_model=ArtifactMetadata,
          summary="Get artifact metadata",
          description="Get metadata for an artifact (size, content-type, checksum) without loading the full content.")
async def get_artifact_metadata(
    job_id: str,
    artifact_type: str,
    current_user: str = Depends(get_current_user)
):
    """Get artifact metadata"""
    job_id = _validate_job_id(job_id)
    if not artifact_type or len(artifact_type) > 100:
        raise HTTPException(status_code=400, detail="Invalid artifact_type (empty or too long)")
    artifact_store = get_artifact_store()
    metadata = artifact_store.get_artifact_metadata(job_id, artifact_type)
    
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_type} not found")
    
    return ArtifactMetadata(**metadata)


@router.post("/draft-pr/jobs/{job_id}/retry",
          tags=["Draft PR"],
          summary="Retry failed job",
          description="Retry a failed draft PR job from a specific stage. Reconstructs job state from artifacts and re-enqueues the worker.")
async def retry_job(
    job_id: str,
    request: RetryJobRequest,
    current_user: str = Depends(get_current_user)
):
    """Retry a failed draft PR job"""
    job_id = _validate_job_id(job_id)
    if job_id not in jobs:
        # Try to reconstruct from Redis
        from ..job_queue import retrieve_job_status
        redis_status = await retrieve_job_status(job_id)
        if not redis_status:
            raise HTTPException(status_code=404, detail="Job not found")
        # Reconstruct job from Redis
        from ..models.generation import JobStatus
        job = JobStatus(**redis_status)
        jobs[job_id] = job
    else:
        job = jobs[job_id]
    
    # Validate job state
    if not request.force and job.status != "failed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in failed state (current: {job.status}). Use force=true to retry anyway."
        )
    
    # Stage validation is handled by RetryJobRequest validator, but double-check for safety
    if request.stage:
        valid_stages = ["PLANNING", "APPLYING", "VERIFYING", "PACKAGING", "DRAFTING"]
        if request.stage not in valid_stages:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage: {request.stage}. Valid stages: {', '.join(valid_stages)}"
            )
    
    # Reconstruct job state from artifacts
    artifact_store = get_artifact_store()
    input_spec = artifact_store.retrieve_artifact(job_id, "input_spec")
    if not input_spec:
        raise HTTPException(
            status_code=400,
            detail="Cannot retry job: input_spec artifact not found. Job may be too old or corrupted."
        )
    
    # Re-enqueue worker job
    try:
        redis_pool = await get_redis_pool()
        
        # Determine retry stage - if not specified, retry from the failed stage
        retry_stage = request.stage or job.stage
        
        # Create new job ID for retry (or reuse same job_id?)
        # For now, we'll reuse the same job_id and reset its state
        job.status = "started"
        job.stage = retry_stage
        job.progress = {"message": f"Retrying from {retry_stage} stage..."}
        job.error = None
        job.completed_at = None
        
        # Re-enqueue with original parameters
        await redis_pool.enqueue_job(
            'process_draft_pr_worker',
            job_id=job_id,
            story_key=input_spec.get('story_key', job.ticket_key),
            story_summary=input_spec.get('story_summary', ''),
            story_description=input_spec.get('story_description'),
            repos=input_spec.get('repos', []),
            scope=input_spec.get('scope'),
            additional_context=input_spec.get('additional_context'),
            mode=input_spec.get('mode', 'normal'),
            _job_id=job_id
        )
        
        logger.info(f"Retried job {job_id} from stage {retry_stage}")
        
        return {
            "job_id": job_id,
            "status": "started",
            "stage": retry_stage,
            "message": f"Job retry initiated from {retry_stage} stage"
        }
        
    except Exception as e:
        logger.error(f"Failed to retry job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retry job: {e}")


@router.get("/draft-pr/jobs/{job_id}/progress",
          tags=["Draft PR"],
          response_model=ProgressResponse,
          summary="Get job progress",
          description="Get detailed progress information including percentage, ETA, and current step.")
async def get_job_progress(
    job_id: str,
    current_user: str = Depends(get_current_user)
):
    """Get detailed progress for a draft PR job"""
    job_id = _validate_job_id(job_id)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    # Calculate progress based on stage
    stage_progress_map = {
        "CREATED": (0, "Job created"),
        "PLANNING": (10, "Generating plan"),
        "WAITING_FOR_APPROVAL": (30, "Waiting for approval"),
        "REVISING": (25, "Revising plan"),
        "APPLYING": (50, "Applying code changes"),
        "VERIFYING": (70, "Running verification"),
        "PACKAGING": (85, "Packaging changes"),
        "DRAFTING": (95, "Creating draft PR"),
        "COMPLETED": (100, "Completed"),
        "FAILED": (0, "Failed")
    }
    
    stage = job.stage or "CREATED"
    percentage, current_step = stage_progress_map.get(stage, (0, "Unknown stage"))
    
    # Calculate stage duration if available
    stage_started_at = None
    stage_duration = None
    if job.started_at:
        stage_started_at = job.started_at
        if job.completed_at:
            stage_duration = int((job.completed_at - job.started_at).total_seconds())
        else:
            stage_duration = int((datetime.now() - job.started_at).total_seconds())
    
    # Estimate time remaining (rough estimates per stage)
    stage_time_estimates = {
        "PLANNING": 300,  # 5 minutes
        "APPLYING": 600,  # 10 minutes
        "VERIFYING": 180,  # 3 minutes
        "PACKAGING": 60,  # 1 minute
        "DRAFTING": 120,  # 2 minutes
    }
    
    estimated_time_remaining = None
    if stage in stage_time_estimates and stage_duration:
        estimated = stage_time_estimates[stage] - stage_duration
        estimated_time_remaining = max(0, estimated)
    
    # Determine total steps and completed steps
    total_steps = 8  # CREATED, PLANNING, WAITING_FOR_APPROVAL, APPLYING, VERIFYING, PACKAGING, DRAFTING, COMPLETED
    steps_completed = {
        "CREATED": 0,
        "PLANNING": 1,
        "WAITING_FOR_APPROVAL": 2,
        "REVISING": 2,  # Same as WAITING_FOR_APPROVAL
        "APPLYING": 3,
        "VERIFYING": 4,
        "PACKAGING": 5,
        "DRAFTING": 6,
        "COMPLETED": 7,
        "FAILED": 0
    }.get(stage, 0)
    
    return ProgressResponse(
        job_id=job_id,
        stage=stage,
        percentage=percentage,
        current_step=current_step,
        total_steps=total_steps,
        steps_completed=steps_completed,
        estimated_time_remaining=estimated_time_remaining,
        stage_started_at=stage_started_at,
        stage_duration=stage_duration
    )


@router.get("/validate/story/{key}",
          tags=["Draft PR"],
          response_model=StoryValidationResponse,
          summary="Validate story",
          description="Check if a JIRA story exists and is valid for draft PR creation.")
async def validate_story(
    key: str,
    current_user: str = Depends(get_current_user)
):
    """Validate a JIRA story for draft PR"""
    from ..utils import normalize_ticket_key
    from ..dependencies import get_jira_client
    
    # Normalize story key
    story_key = normalize_ticket_key(key)
    if not story_key:
        return StoryValidationResponse(
            exists=False,
            valid=False,
            story_key=key,
            error=f"Invalid story key format: {key}"
        )
    
    jira_client = get_jira_client()
    if not jira_client:
        raise HTTPException(status_code=503, detail="JIRA client not initialized")
    
    try:
        # Get ticket
        ticket_data = jira_client.get_ticket(story_key)
        if not ticket_data:
            return StoryValidationResponse(
                exists=False,
                valid=False,
                story_key=story_key,
                error=f"Story {story_key} not found in JIRA"
            )
        
        # Check ticket type
        ticket_type = jira_client.get_ticket_type(story_key)
        is_story = ticket_type and "story" in ticket_type.lower()
        
        # Get summary and status
        fields = ticket_data.get('fields', {})
        summary = fields.get('summary', '')
        status = fields.get('status', {}).get('name', '')
        
        return StoryValidationResponse(
            exists=True,
            valid=is_story,
            story_key=story_key,
            summary=summary,
            status=status,
            error=None if is_story else f"Ticket {story_key} is not a Story (type: {ticket_type})"
        )
        
    except Exception as e:
        logger.error(f"Error validating story {story_key}: {e}")
        return StoryValidationResponse(
            exists=False,
            valid=False,
            story_key=story_key,
            error=f"Error validating story: {str(e)}"
        )


@router.post("/validate/repo",
          tags=["Draft PR"],
          response_model=RepoValidationResponse,
          summary="Validate repository",
          description="Test repository access and validate URL format. Checks if repository is accessible and branch exists if provided.")
async def validate_repo(
    request: RepoValidationRequest,
    current_user: str = Depends(get_current_user)
):
    """Validate repository access"""
    from src.workspace_manager import WorkspaceManager
    from ..dependencies import get_config
    import re
    
    config = get_config()
    git_creds = config.get_git_credentials()
    
    try:
        # Extract workspace and repo slug from URL
        # Support Bitbucket format: https://bitbucket.org/{workspace}/{repo}.git
        # Support GitHub format: https://github.com/{owner}/{repo}.git
        workspace = None
        repo_slug = None
        
        bitbucket_pattern = r'https?://(?:bitbucket\.org|.*\.bitbucket\.io)/([^/]+)/([^/]+?)(?:\.git)?/?$'
        github_pattern = r'https?://(?:github\.com|.*\.github\.io)/([^/]+)/([^/]+?)(?:\.git)?/?$'
        
        bitbucket_match = re.match(bitbucket_pattern, request.url)
        github_match = re.match(github_pattern, request.url)
        
        if bitbucket_match:
            workspace = bitbucket_match.group(1)
            repo_slug = bitbucket_match.group(2)
        elif github_match:
            workspace = github_match.group(1)
            repo_slug = github_match.group(2)
        else:
            return RepoValidationResponse(
                accessible=False,
                url=request.url,
                branch=request.branch,
                error="Invalid repository URL format. Expected Bitbucket or GitHub URL."
            )
        
        # Test repository access by attempting to clone (shallow, timeout quickly)
        workspace_manager = WorkspaceManager(
            git_username=git_creds.get('username'),
            git_password=git_creds.get('password'),
            clone_timeout_seconds=30,  # Short timeout for validation
            shallow_clone=True
        )
        
        # Create a temporary workspace path for testing
        import tempfile
        import shutil
        from pathlib import Path
        
        temp_dir = Path(tempfile.mkdtemp(prefix="repo_validation_"))
        test_workspace_path = temp_dir / "test_repo"
        
        try:
            # Validate URL format (additional check beyond RepoSpec validation)
            if not request.url or len(request.url) > 2048:
                return RepoValidationResponse(
                    accessible=False,
                    url=request.url,
                    branch=request.branch,
                    error="Invalid URL: empty or too long (max 2048 characters)"
                )
            
            # Validate branch if provided (RepoSpec should have validated, but double-check for safety)
            if request.branch and (".." in request.branch or len(request.branch) > 255):
                return RepoValidationResponse(
                    accessible=False,
                    url=request.url,
                    branch=request.branch,
                    error="Invalid branch name: contains '..' or too long (max 255 characters)"
                )
            
            # Attempt to clone using workspace manager's method
            cloned_repo = await workspace_manager._clone_repo(
                request.url,
                test_workspace_path,
                branch=request.branch
            )
            
            cloned_path = test_workspace_path
            
            # Get default branch if not specified
            default_branch = None
            if cloned_path.exists():
                import subprocess
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=cloned_path,
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        default_branch = result.stdout.strip()
                except Exception:
                    pass
            
            # Check if branch exists if specified
            if request.branch:
                try:
                    # Additional safety check: ensure branch doesn't contain dangerous patterns
                    # (RepoSpec validator should have caught this, but double-check)
                    if ".." in request.branch:
                        return RepoValidationResponse(
                            accessible=True,
                            url=request.url,
                            branch=request.branch,
                            default_branch=default_branch,
                            workspace=workspace,
                            repo_slug=repo_slug,
                            error=f"Invalid branch name: contains '..'"
                        )
                    
                    result = subprocess.run(
                        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{request.branch}"],
                        cwd=cloned_path,
                        capture_output=True,
                        timeout=5
                    )
                    if result.returncode != 0:
                        return RepoValidationResponse(
                            accessible=True,
                            url=request.url,
                            branch=request.branch,
                            default_branch=default_branch,
                            workspace=workspace,
                            repo_slug=repo_slug,
                            error=f"Branch '{request.branch}' does not exist in repository"
                        )
                except Exception as e:
                    logger.warning(f"Could not verify branch {request.branch}: {e}")
            
            return RepoValidationResponse(
                accessible=True,
                url=request.url,
                branch=request.branch,
                default_branch=default_branch,
                workspace=workspace,
                repo_slug=repo_slug,
                error=None
            )
            
        except Exception as e:
            logger.error(f"Error validating repository {request.url}: {e}")
            return RepoValidationResponse(
                accessible=False,
                url=request.url,
                branch=request.branch,
                error=f"Repository not accessible: {str(e)}"
            )
        finally:
            # Cleanup temp directory
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp directory {temp_dir}: {cleanup_error}")
                
    except Exception as e:
        logger.error(f"Error validating repository: {e}")
        return RepoValidationResponse(
            accessible=False,
            url=request.url,
            branch=request.branch,
            error=f"Validation error: {str(e)}"
        )


# Template Management Endpoints

@router.get("/draft-pr/templates",
          tags=["Draft PR"],
          response_model=List[TemplateSummary],
          summary="List templates",
          description="List all templates for the current user.")
async def list_templates(
    current_user: str = Depends(get_current_user)
):
    """List all templates for the current user"""
    template_store = get_template_store()
    templates = template_store.list_templates(current_user)
    return [TemplateSummary(**t) for t in templates]


@router.get("/draft-pr/templates/{template_id}",
          tags=["Draft PR"],
          response_model=TemplateResponse,
          summary="Get template",
          description="Get a specific template by ID.")
async def get_template(
    template_id: str,
    current_user: str = Depends(get_current_user)
):
    """Get a specific template"""
    template_id = _validate_template_id(template_id)
    template_store = get_template_store()
    template = template_store.get_template(current_user, template_id)
    
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    
    return TemplateResponse(**template)


@router.post("/draft-pr/templates",
          tags=["Draft PR"],
          response_model=TemplateResponse,
          summary="Create template",
          description="Create a new template for saving draft PR configurations.")
async def create_template(
    request: TemplateCreateRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new template"""
    template_store = get_template_store()
    template_id = template_store.create_template(
        user=current_user,
        name=request.name,
        repos=request.repos,
        scope=request.scope,
        additional_context=request.additional_context,
        description=request.description
    )
    
    template = template_store.get_template(current_user, template_id)
    return TemplateResponse(**template)


@router.put("/draft-pr/templates/{template_id}",
          tags=["Draft PR"],
          response_model=TemplateResponse,
          summary="Update template",
          description="Update an existing template.")
async def update_template(
    template_id: str,
    request: TemplateUpdateRequest,
    current_user: str = Depends(get_current_user)
):
    """Update a template"""
    template_id = _validate_template_id(template_id)
    template_store = get_template_store()
    
    # Check if template exists
    existing = template_store.get_template(current_user, template_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    
    # Update
    success = template_store.update_template(
        user=current_user,
        template_id=template_id,
        name=request.name,
        repos=request.repos,
        scope=request.scope,
        additional_context=request.additional_context,
        description=request.description
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update template")
    
    template = template_store.get_template(current_user, template_id)
    return TemplateResponse(**template)


@router.delete("/draft-pr/templates/{template_id}",
          tags=["Draft PR"],
          summary="Delete template",
          description="Delete a template.")
async def delete_template(
    template_id: str,
    current_user: str = Depends(get_current_user)
):
    """Delete a template"""
    template_id = _validate_template_id(template_id)
    template_store = get_template_store()
    
    # Check if template exists
    existing = template_store.get_template(current_user, template_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    
    success = template_store.delete_template(current_user, template_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete template")
    
    return {"message": f"Template {template_id} deleted successfully"}


# Bulk Operations Endpoints

@router.post("/draft-pr/bulk/create",
          tags=["Draft PR"],
          response_model=BulkResponse,
          summary="Create multiple draft PR jobs",
          description="Create multiple draft PR jobs in parallel with rate limiting.")
async def bulk_create_jobs(
    request: BulkCreateRequest,
    current_user: str = Depends(get_current_user)
):
    """Create multiple draft PR jobs"""
    import asyncio
    
    # Validate bulk operation limits
    if len(request.jobs) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 jobs can be created at once")
    
    results = []
    successful = 0
    failed = 0
    
    # Process jobs with concurrency limit
    semaphore = asyncio.Semaphore(request.max_concurrent)
    
    async def create_single_job(job_request: CreateDraftPRRequest, index: int):
        async with semaphore:
            try:
                # Use the existing create endpoint logic
                from ..dependencies import get_active_job_for_ticket, register_ticket_job
                active_job_id = get_active_job_for_ticket(job_request.story_key)
                if active_job_id:
                    if active_job_id in jobs:
                        active_job = jobs[active_job_id]
                        if active_job.status in ["created", "processing", "started"]:
                            return {
                                "index": index,
                                "story_key": job_request.story_key,
                                "success": False,
                                "error": f"Story {job_request.story_key} is already being processed in job {active_job_id}"
                            }
                
                job_id = str(uuid.uuid4())
                
                job = JobStatus(
                    job_id=job_id,
                    job_type="draft_pr",
                    status="started",
                    progress={"message": "Creating draft PR job..."},
                    started_at=datetime.now(),
                    stage=PipelineStageEnum.CREATED.value,
                    ticket_key=job_request.story_key,
                    mode=job_request.mode
                )
                jobs[job_id] = job
                register_ticket_job(job_request.story_key, job_id)
                
                redis_pool = await get_redis_pool()
                await redis_pool.enqueue_job(
                    'process_draft_pr_worker',
                    job_id=job_id,
                    story_key=job_request.story_key,
                    story_summary="",
                    story_description=None,
                    repos=job_request.repos,
                    scope=job_request.scope,
                    additional_context=job_request.additional_context,
                    mode=job_request.mode,
                    _job_id=job_id
                )
                
                job.stage = PipelineStageEnum.PLANNING.value
                job.status = "processing"
                job.progress = {"message": "Planning stage started"}
                
                return {
                    "index": index,
                    "story_key": job_request.story_key,
                    "success": True,
                    "job_id": job_id,
                    "status_url": f"/jobs/{job_id}"
                }
            except Exception as e:
                logger.error(f"Failed to create job for story {job_request.story_key}: {e}")
                return {
                    "index": index,
                    "story_key": job_request.story_key,
                    "success": False,
                    "error": str(e)
                }
    
    # Create all jobs
    tasks = [create_single_job(job_req, i) for i, job_req in enumerate(request.jobs)]
    results = await asyncio.gather(*tasks)
    
    # Count successes and failures
    for result in results:
        if result.get("success"):
            successful += 1
        else:
            failed += 1
    
    return BulkResponse(
        total=len(request.jobs),
        successful=successful,
        failed=failed,
        results=results
    )


@router.post("/draft-pr/jobs/bulk/approve",
          tags=["Draft PR"],
          response_model=BulkResponse,
          summary="Approve multiple plans",
          description="Approve multiple plans in parallel.")
async def bulk_approve_plans(
    request: BulkApproveRequest,
    current_user: str = Depends(get_current_user)
):
    """Approve multiple plans"""
    import asyncio
    
    # Validate bulk operation limits
    if len(request.approvals) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 approvals can be processed at once")
    
    results = []
    successful = 0
    failed = 0
    
    async def approve_single(raw_job_id: str, plan_hash: str, index: int):
        try:
            # Validate inputs
            job_id = _validate_job_id(raw_job_id)
            if not plan_hash or not re.match(r'^[0-9a-f]{64}$', plan_hash, re.IGNORECASE):
                return {
                    "index": index,
                    "job_id": raw_job_id,
                    "success": False,
                    "error": "Invalid plan_hash format (expected 64-character hex string)"
                }
            
            # Note: Bulk approval is complex due to distributed locks and pipeline continuation
            # For safety, we validate but recommend individual approvals
            if job_id not in jobs:
                # Try Redis
                from ..job_queue import retrieve_job_status
                redis_status = await retrieve_job_status(job_id)
                if not redis_status:
                    return {
                        "index": index,
                        "job_id": job_id,
                        "success": False,
                        "error": "Job not found"
                    }
                from ..models.generation import JobStatus
                job = JobStatus(**redis_status)
                jobs[job_id] = job
            else:
                job = jobs[job_id]
            
            if job.stage != PipelineStageEnum.WAITING_FOR_APPROVAL.value:
                return {
                    "index": index,
                    "job_id": job_id,
                    "success": False,
                    "error": f"Job must be in WAITING_FOR_APPROVAL stage, current: {job.stage}"
                }
            
            # For bulk operations, we recommend individual approvals to avoid lock contention
            # This endpoint validates but doesn't actually approve
            # To approve, use the individual approve endpoint
            return {
                "index": index,
                "job_id": job_id,
                "success": False,
                "error": "Bulk approval requires individual approval calls to ensure proper locking. Use POST /draft-pr/jobs/{job_id}/approve for each job."
            }
        except HTTPException as e:
            return {
                "index": index,
                "job_id": raw_job_id,
                "success": False,
                "error": e.detail
            }
        except Exception as e:
            logger.error(f"Error in bulk approve for job {raw_job_id}: {e}")
            return {
                "index": index,
                "job_id": raw_job_id,
                "success": False,
                "error": str(e)
            }
    
    tasks = [
        approve_single(approval.get("job_id"), approval.get("plan_hash"), i)
        for i, approval in enumerate(request.approvals)
    ]
    results = await asyncio.gather(*tasks)
    
    for result in results:
        if result.get("success"):
            successful += 1
        else:
            failed += 1
    
    return BulkResponse(
        total=len(request.approvals),
        successful=successful,
        failed=failed,
        results=results
    )


@router.post("/draft-pr/jobs/bulk/cancel",
          tags=["Draft PR"],
          response_model=BulkResponse,
          summary="Cancel multiple jobs",
          description="Cancel multiple jobs in parallel.")
async def bulk_cancel_jobs(
    job_ids: List[str] = Query(..., description="List of job IDs to cancel"),
    current_user: str = Depends(get_current_user)
):
    """Cancel multiple jobs"""
    from ..routes.jobs import cancel_job as cancel_job_endpoint
    
    # Validate and limit bulk operations
    if len(job_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 jobs can be cancelled at once")
    
    results = []
    successful = 0
    failed = 0
    
    for raw_job_id in job_ids:
        try:
            job_id = _validate_job_id(raw_job_id)
            # Use existing cancel logic
            from ..job_queue import request_job_cancellation
            await request_job_cancellation(job_id)
            
            if job_id in jobs:
                job = jobs[job_id]
                if job.status in ["started", "processing"]:
                    job.status = "cancelled"
                    job.completed_at = datetime.now()
                    job.progress = {"message": "Job cancelled"}
            
            results.append({
                "job_id": job_id,
                "success": True
            })
            successful += 1
        except HTTPException as e:
            results.append({
                "job_id": raw_job_id,
                "success": False,
                "error": e.detail
            })
            failed += 1
        except Exception as e:
            logger.error(f"Error cancelling job {raw_job_id}: {e}")
            results.append({
                "job_id": raw_job_id,
                "success": False,
                "error": str(e)
            })
            failed += 1
    
    return BulkResponse(
        total=len(job_ids),
        successful=successful,
        failed=failed,
        results=results
    )


# Analytics Endpoints

@router.get("/draft-pr/analytics/stats",
          tags=["Draft PR"],
          response_model=AnalyticsStats,
          summary="Get analytics statistics",
          description="Get overall statistics for draft PR jobs including success rates, durations, and failure reasons.")
async def get_analytics_stats(
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    current_user: str = Depends(get_current_user)
):
    """Get analytics statistics"""
    # Get all draft PR jobs from in-memory store and Redis
    from ..job_queue import get_redis_pool
    from ..routes.jobs import _reconstruct_job_from_redis
    
    all_jobs = []
    
    # Get jobs from in-memory store
    for job_id, job in jobs.items():
        if job.job_type == "draft_pr":
            all_jobs.append(job.dict())
    
    # Get jobs from Redis
    try:
        redis_pool = await get_redis_pool()
        all_results = await redis_pool.all_job_results()
        for job_result in all_results:
            if job_result.job_id not in jobs:
                # Try to reconstruct
                reconstructed = await _reconstruct_job_from_redis(job_result.job_id)
                if reconstructed and reconstructed.job_type == "draft_pr":
                    all_jobs.append(reconstructed.dict())
    except Exception as e:
        logger.warning(f"Error loading jobs from Redis for analytics: {e}")
    
    # Filter by date range
    if start_date:
        all_jobs = [j for j in all_jobs if j.get("started_at") and j["started_at"] >= start_date]
    if end_date:
        all_jobs = [j for j in all_jobs if j.get("started_at") and j["started_at"] <= end_date]
    
    # Filter by status
    if status:
        all_jobs = [j for j in all_jobs if j.get("status") == status]
    
    # Calculate stats
    total_jobs = len(all_jobs)
    successful_jobs = sum(1 for j in all_jobs if j.get("status") == "completed")
    failed_jobs = sum(1 for j in all_jobs if j.get("status") == "failed")
    success_rate = (successful_jobs / total_jobs * 100) if total_jobs > 0 else 0.0
    
    # Calculate durations
    durations = []
    for job in all_jobs:
        if job.get("started_at") and job.get("completed_at"):
            if isinstance(job["started_at"], str):
                from datetime import datetime
                started = datetime.fromisoformat(job["started_at"].replace('Z', '+00:00'))
                completed = datetime.fromisoformat(job["completed_at"].replace('Z', '+00:00'))
            else:
                started = job["started_at"]
                completed = job["completed_at"]
            duration = (completed - started).total_seconds()
            durations.append(duration)
    
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    
    # Count jobs by stage
    jobs_by_stage = Counter(j.get("stage", "UNKNOWN") for j in all_jobs)
    
    # Common failure reasons
    failure_reasons = []
    for job in all_jobs:
        if job.get("status") == "failed" and job.get("error"):
            failure_reasons.append(job["error"])
    
    failure_counter = Counter(failure_reasons)
    common_failures = [
        {"reason": reason, "count": count}
        for reason, count in failure_counter.most_common(10)
    ]
    
    return AnalyticsStats(
        total_jobs=total_jobs,
        successful_jobs=successful_jobs,
        failed_jobs=failed_jobs,
        success_rate=round(success_rate, 2),
        avg_duration_seconds=round(avg_duration, 2),
        avg_planning_duration=None,  # Would need stage timing tracking
        avg_applying_duration=None,  # Would need stage timing tracking
        avg_verifying_duration=None,  # Would need stage timing tracking
        common_failure_reasons=common_failures,
        jobs_by_stage=dict(jobs_by_stage)
    )


@router.get("/draft-pr/analytics/jobs",
          tags=["Draft PR"],
          summary="Get job-level analytics",
          description="Get analytics for individual jobs with filtering options.")
async def get_job_analytics(
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    current_user: str = Depends(get_current_user)
):
    """Get job-level analytics"""
    # Similar to stats endpoint but return individual job data
    from ..job_queue import get_redis_pool
    from ..routes.jobs import _reconstruct_job_from_redis
    
    all_jobs = []
    
    # Get jobs from in-memory store
    for job_id, job in jobs.items():
        if job.job_type == "draft_pr":
            all_jobs.append(job.dict())
    
    # Get jobs from Redis
    try:
        redis_pool = await get_redis_pool()
        all_results = await redis_pool.all_job_results()
        for job_result in all_results:
            if job_result.job_id not in jobs:
                reconstructed = await _reconstruct_job_from_redis(job_result.job_id)
                if reconstructed and reconstructed.job_type == "draft_pr":
                    all_jobs.append(reconstructed.dict())
    except Exception as e:
        logger.warning(f"Error loading jobs from Redis for analytics: {e}")
    
    # Filter
    if start_date:
        all_jobs = [j for j in all_jobs if j.get("started_at") and j["started_at"] >= start_date]
    if end_date:
        all_jobs = [j for j in all_jobs if j.get("started_at") and j["started_at"] <= end_date]
    if status:
        all_jobs = [j for j in all_jobs if j.get("status") == status]
    
    # Format analytics
    analytics = []
    for job in all_jobs:
        duration = None
        if job.get("started_at") and job.get("completed_at"):
            if isinstance(job["started_at"], str):
                started = datetime.fromisoformat(job["started_at"].replace('Z', '+00:00'))
                completed = datetime.fromisoformat(job["completed_at"].replace('Z', '+00:00'))
            else:
                started = job["started_at"]
                completed = job["completed_at"]
            duration = (completed - started).total_seconds()
        
        analytics.append({
            "job_id": job.get("job_id"),
            "story_key": job.get("ticket_key"),
            "status": job.get("status"),
            "stage": job.get("stage"),
            "duration_seconds": duration,
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "error": job.get("error")
        })
    
    return analytics
