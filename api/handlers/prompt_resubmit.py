"""
Prompt Resubmit Handlers
Handler functions for prompt resubmission operations
"""
from typing import Optional, Dict, Any
import logging

from ..utils import create_custom_llm_client_with_prompts
from ..dependencies import get_generator, get_jira_client

logger = logging.getLogger(__name__)


async def _handle_generate_single_resubmit(
    original_request: Dict[str, Any],
    modified_system_prompt: Optional[str],
    modified_user_prompt: str,
    llm_provider: Optional[str],
    llm_model: Optional[str],
    original_result: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Handle resubmission for /generate/single operation"""
    generator = get_generator()
    jira_client = get_jira_client()
    
    try:
        # Create custom LLM client with modified prompts
        custom_llm_client = create_custom_llm_client_with_prompts(
            provider=llm_provider,
            model=llm_model,
            system_prompt=modified_system_prompt
        )
        
        # Get ticket key from original request
        ticket_key = original_request.get('ticket_key')
        if not ticket_key:
            raise ValueError("ticket_key is required in original_request")
        
        # Build context for generation
        ticket_data = jira_client.get_ticket(ticket_key)
        if not ticket_data:
            raise ValueError(f"Ticket {ticket_key} not found")
        
        # Use the modified prompt directly with the custom LLM client
        # Generate description using the modified prompt
        description_text = custom_llm_client.generate_content(
            prompt=modified_user_prompt,
            system_prompt=modified_system_prompt
        )
        
        new_result = {
            "ticket_key": ticket_key,
            "generated_description": description_text,
            "system_prompt": modified_system_prompt or custom_llm_client.get_system_prompt(),
            "user_prompt": modified_user_prompt,
            "llm_provider": custom_llm_client.provider_name,
            "llm_model": custom_llm_client.provider.model
        }
        
        return new_result
        
    except Exception as e:
        logger.error(f"Error in generate_single resubmit: {str(e)}")
        raise


async def _handle_plan_tasks_resubmit(
    original_request: Dict[str, Any],
    modified_system_prompt: Optional[str],
    modified_user_prompt: str,
    llm_provider: Optional[str],
    llm_model: Optional[str],
    original_result: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Handle resubmission for /plan/tasks/generate operation"""
    try:
        # Note: Planning uses multiple prompts for different stories
        # This is a simplified implementation for A/B testing
        new_result = {
            "message": "Planning task resubmission is complex due to multiple story prompts",
            "note": "For now, this returns the modified prompt that would be used",
            "modified_system_prompt": modified_system_prompt,
            "modified_user_prompt": modified_user_prompt,
            "original_request": original_request
        }
        
        return new_result
        
    except Exception as e:
        logger.error(f"Error in plan_tasks resubmit: {str(e)}")
        raise


async def _handle_coverage_analysis_resubmit(
    original_request: Dict[str, Any],
    modified_system_prompt: Optional[str],
    modified_user_prompt: str,
    llm_provider: Optional[str],
    llm_model: Optional[str],
    original_result: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Handle resubmission for /analyze/story-coverage operation"""
    try:
        # Create custom LLM client with modified prompts
        custom_llm_client = create_custom_llm_client_with_prompts(
            provider=llm_provider,
            model=llm_model,
            system_prompt=modified_system_prompt
        )
        
        # Get story key from original request
        story_key = original_request.get('story_key')
        if not story_key:
            raise ValueError("story_key is required in original_request")
        
        # Use the LLM client directly with the modified prompt (using enforced JSON mode)
        # Coverage analysis expects JSON responses, so use generate_content_json
        # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
        response_text = custom_llm_client.generate_content_json(
            prompt=modified_user_prompt,
            system_prompt=modified_system_prompt,
            max_tokens=None
        )
        
        # Parse JSON response (should already be valid JSON from generate_content_json)
        import json
        try:
            parsed_result = json.loads(response_text)
        except json.JSONDecodeError as e:
            # Fallback extraction if needed (shouldn't happen with enforced JSON, but defensive)
            logger.warning(f"JSON parsing failed in resubmit, attempting extraction: {e}")
            if '```json' in response_text:
                json_start = response_text.find('```json') + 7
                json_end = response_text.find('```', json_start)
                json_str = response_text[json_start:json_end].strip()
            elif '```' in response_text:
                json_start = response_text.find('```') + 3
                json_end = response_text.find('```', json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                json_str = response_text.strip()
            
            try:
                parsed_result = json.loads(json_str)
            except json.JSONDecodeError:
                parsed_result = {"raw_response": response_text, "parse_error": str(e)}
        
        new_result = {
            "story_key": story_key,
            "analysis_result": parsed_result,
            "system_prompt": modified_system_prompt or custom_llm_client.get_system_prompt(),
            "user_prompt": modified_user_prompt,
            "llm_provider": custom_llm_client.provider_name,
            "llm_model": custom_llm_client.provider.model
        }
        
        return new_result
        
    except Exception as e:
        logger.error(f"Error in coverage_analysis resubmit: {str(e)}")
        raise
