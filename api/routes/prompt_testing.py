"""
Prompt Testing Routes
Endpoints for prompt resubmission (A/B testing)
"""
from fastapi import APIRouter, HTTPException, Depends
import logging

from ..models.prompt_testing import PromptResubmitRequest, PromptResubmitResponse
from ..handlers.prompt_resubmit import (
    _handle_generate_single_resubmit,
    _handle_plan_tasks_resubmit,
    _handle_coverage_analysis_resubmit
)
from ..auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/prompt/resubmit",
         tags=["Prompt A/B Testing"],
         response_model=PromptResubmitResponse,
         summary="Resubmit prompt with modifications for A/B testing",
         description="""
         Resubmit a modified prompt to compare results with the original generation.
         Use after calling any generation endpoint to test prompt modifications.
         
         **Supported Operations:**
         - `generate_single`: Generate single ticket description
         - `plan_tasks`: Generate tasks for stories (simplified for A/B testing)
         - `analyze_coverage`: Analyze story coverage by tasks
         
         **Use Cases:**
         - Test different prompt phrasings
         - Compare system prompt variations
         - Evaluate different LLM models
         - Fine-tune generation quality
         
         **Note:** Original result must be provided for comparison.
         """)
async def resubmit_prompt(
    request: PromptResubmitRequest,
    current_user: str = Depends(get_current_user)
):
    """Resubmit a modified prompt for A/B testing"""
    try:
        logger.info(f"User {current_user} resubmitting prompt for operation: {request.operation_type}")
        
        # Validate operation type
        valid_operations = ['generate_single', 'plan_tasks', 'analyze_coverage']
        if request.operation_type not in valid_operations:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid operation_type. Must be one of: {', '.join(valid_operations)}"
            )
        
        # Route to appropriate handler
        handler_map = {
            'generate_single': _handle_generate_single_resubmit,
            'plan_tasks': _handle_plan_tasks_resubmit,
            'analyze_coverage': _handle_coverage_analysis_resubmit
        }
        
        handler = handler_map[request.operation_type]
        
        # Execute resubmission
        new_result = await handler(
            original_request=request.original_request,
            modified_system_prompt=request.modified_system_prompt,
            modified_user_prompt=request.modified_user_prompt,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            original_result=None  # We don't need original result for generation
        )
        
        # Build prompts comparison
        prompts_used = {
            "modified_system_prompt": request.modified_system_prompt or "Using default system prompt",
            "modified_user_prompt": request.modified_user_prompt,
            "llm_provider": request.llm_provider or "default",
            "llm_model": request.llm_model or "default"
        }
        
        # Generate comparison notes
        comparison_notes = f"Resubmitted {request.operation_type} operation with modified prompt"
        if request.modified_system_prompt:
            comparison_notes += " (custom system prompt)"
        if request.llm_provider or request.llm_model:
            comparison_notes += f" using {request.llm_provider or 'default'}/{request.llm_model or 'default'}"
        
        return PromptResubmitResponse(
            success=True,
            operation_type=request.operation_type,
            original_result=None,  # Could be added if user provides it
            new_result=new_result,
            prompts_used=prompts_used,
            comparison_notes=comparison_notes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in prompt resubmission: {str(e)}", exc_info=True)
        return PromptResubmitResponse(
            success=False,
            operation_type=request.operation_type,
            original_result=None,
            new_result={},
            prompts_used={},
            error=str(e)
        )
