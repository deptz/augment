"""
Draft PR Routes
API endpoints for draft PR orchestrator
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from datetime import datetime
import logging
import uuid

from ..models.draft_pr import (
    CreateDraftPRRequest,
    RevisePlanRequest,
    ApprovePlanRequest,
    PlanRevisionResponse,
    PlanComparisonResponse
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

router = APIRouter()
logger = logging.getLogger(__name__)


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
        ticket_key=request.story_key
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


@router.get("/draft-pr/jobs/{job_id}/plans/{version}",
          tags=["Draft PR"],
          summary="Get specific plan version",
          description="Get a specific plan version by version number.")
async def get_plan_version(
    job_id: str,
    version: int,
    current_user: str = Depends(get_current_user)
):
    """Get specific plan version"""
    artifact_store = get_artifact_store()
    plan = artifact_store.retrieve_artifact(job_id, f"plan_v{version}")
    
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan v{version} not found")
    
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
    
    try:
        new_version = await pipeline.plan_generator.revise_plan(
            job_id=job_id,
            previous_version=previous_version,
            feedback=feedback,
            use_opencode=bool(pipeline.opencode_runner),
            workspace_path=workspace_path if workspace_path.exists() else None
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
          description="Compare two plan versions and get a diff.")
async def compare_plans(
    job_id: str,
    from_version: int = Query(..., description="Source version number"),
    to_version: int = Query(..., description="Target version number"),
    current_user: str = Depends(get_current_user)
):
    """Compare two plan versions"""
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
    
    return PlanComparisonResponse(
        from_version=comparison.from_version,
        to_version=comparison.to_version,
        changes=comparison.changes,
        summary=comparison.summary,
        changed_sections=comparison.changed_sections
    )


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
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
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
    
    # Update job
    job.approved_plan_hash = request.plan_hash
    job.stage = PipelineStageEnum.APPLYING.value
    job.progress = {"message": "Plan approved, proceeding to APPLY stage"}
    
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
    
    # Continue pipeline execution
    try:
        pipeline = _get_draft_pr_pipeline()
        results = await pipeline.continue_pipeline_after_approval(
            job_id=job_id,
            approved_plan_hash=request.plan_hash,
            cancellation_event=None
        )
        
        # Update job with results
        job.stage = results.get('stage', PipelineStageEnum.APPLYING.value)
        job.results = results
        
        if results.get('stage') == 'COMPLETED':
            job.status = "completed"
            job.completed_at = datetime.now()
            job.progress = {"message": f"Draft PR created: {results.get('pr_results', {}).get('pr_url', 'N/A')}"}
        elif results.get('stage') == 'FAILED':
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = results.get('error', 'Unknown error')
            job.progress = {"message": f"Pipeline failed: {results.get('error', 'Unknown error')}"}
        
        return {
            "approved": True,
            "plan_hash": request.plan_hash,
            "stage": results.get('stage', PipelineStageEnum.APPLYING.value),
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Failed to continue pipeline after approval: {e}", exc_info=True)
        job.status = "failed"
        job.error = str(e)
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
    artifact_store = get_artifact_store()
    artifact = artifact_store.retrieve_artifact(job_id, artifact_type)
    
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_type} not found")
    
    return artifact
