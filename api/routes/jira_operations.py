"""
JIRA Operations Routes
Endpoints for JIRA ticket operations
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Union, Dict, Any
import logging

from ..models.jira_operations import (
    UpdateTicketRequest,
    CreateTicketRequest,
    CreateStoryTicketRequest,
    UpdateStoryTicketRequest,
    UpdateTicketResponse,
    CreateTicketResponse,
    BulkUpdateStoriesRequest,
    BulkUpdateStoriesResponse,
    StoryUpdateItem,
    StoryUpdateResult,
    BulkCreateTasksRequest,
    BulkCreateTasksResponse,
    BulkCreateStoriesRequest,
    BulkCreateStoriesResponse,
    BulkCreateResult,
    BulkCreateTaskItem,
    BulkCreateStoryItem
)
from ..models.generation import BatchResponse, JobStatus
from ..dependencies import get_jira_client, get_active_job_for_ticket, register_ticket_job, jobs
from ..models.generation import BatchResponse, JobStatus
from ..auth import get_current_user
from datetime import datetime
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/jira/update-ticket",
         tags=["JIRA Operations"],
         response_model=UpdateTicketResponse,
         summary="Update JIRA ticket with partial updates and link management",
         description="Update a JIRA ticket with partial updates: summary, description, test cases, and issue links. Preview mode by default. Set update_jira=true to apply changes.")
async def update_jira_ticket(
    request: UpdateTicketRequest,
    current_user: str = Depends(get_current_user)
):
    """Update a JIRA ticket with partial updates and link management"""
    jira_client = get_jira_client()
    from ..dependencies import get_confluence_client

    try:
        logger.info(f"User {current_user} updating ticket {request.ticket_key} (update_jira={request.update_jira})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Verify ticket exists
        ticket_data = jira_client.get_ticket(request.ticket_key)
        if not ticket_data:
            raise HTTPException(status_code=404, detail=f"Ticket {request.ticket_key} not found")

        # Track what updates were applied
        updates_applied = {}
        links_created = []

        if not request.update_jira:
            # Preview mode - just return what would be updated
            logger.info(f"Preview mode for {request.ticket_key} - not updating JIRA")

            preview_data = {
                "ticket_key": request.ticket_key,
                "current_summary": ticket_data.get('fields', {}).get('summary', ''),
                "current_description": jira_client._extract_text_from_adf(
                    ticket_data.get('fields', {}).get('description', {})
                ) if isinstance(ticket_data.get('fields', {}).get('description'), dict) else ticket_data.get('fields', {}).get('description', ''),
            }

            if request.summary:
                preview_data["new_summary"] = request.summary
            if request.description:
                preview_data["new_description"] = request.description
            if request.test_cases:
                preview_data["new_test_cases"] = request.test_cases
            if request.links:
                preview_data["links_to_create"] = [
                    {
                        "link_type": link.link_type,
                        "target_key": link.target_key,
                        "direction": link.direction
                    }
                    for link in request.links
                ]

            return UpdateTicketResponse(
                success=True,
                ticket_key=request.ticket_key,
                updated_in_jira=False,
                updates_applied={},
                links_created=[],
                preview=preview_data,
                message=f"Preview: Ticket {request.ticket_key} would be updated. Set update_jira=true to commit."
            )

        # Actually update JIRA
        logger.info(f"Updating ticket {request.ticket_key} in JIRA")

        # Update summary if provided
        if request.summary:
            logger.info(f"Updating summary for {request.ticket_key}")
            summary_updated = jira_client.update_ticket_summary(
                ticket_key=request.ticket_key,
                summary=request.summary
            )
            updates_applied["summary"] = summary_updated
            if not summary_updated:
                logger.warning(f"Failed to update summary for {request.ticket_key}")

        # Update description if provided
        if request.description:
            logger.info(f"Updating description for {request.ticket_key}")
            description_updated = jira_client.update_ticket_description(
                ticket_key=request.ticket_key,
                description=request.description,
                dry_run=False
            )
            updates_applied["description"] = description_updated
            if not description_updated:
                logger.warning(f"Failed to update description for {request.ticket_key}")
            else:
                # Handle image attachments if description contains images
                confluence_client = get_confluence_client()
                confluence_server_url = None
                if confluence_client:
                    confluence_server_url = confluence_client.server_url

                jira_client._attach_images_from_description(
                    request.ticket_key,
                    request.description,
                    confluence_server_url
                )

        # Update test cases if provided
        if request.test_cases:
            logger.info(f"Updating test cases for {request.ticket_key}")
            test_cases_updated = jira_client.update_test_case_custom_field(
                ticket_key=request.ticket_key,
                test_cases_content=request.test_cases
            )
            updates_applied["test_cases"] = test_cases_updated
            if not test_cases_updated:
                logger.warning(f"Failed to update test cases for {request.ticket_key}")

        # Process links if provided
        if request.links:
            logger.info(f"Processing {len(request.links)} link(s) for {request.ticket_key}")

            for link_req in request.links:
                link_type = link_req.link_type
                target_key = link_req.target_key
                direction = link_req.direction

                # Smart split detection
                if "split" in link_type.lower():
                    logger.info(f"Detected split link type, applying smart direction logic")

                    # Get ticket types
                    source_type = jira_client.get_ticket_type(request.ticket_key)
                    target_type = jira_client.get_ticket_type(target_key)

                    if source_type and target_type:
                        logger.info(f"Source type: {source_type}, Target type: {target_type}")

                        # Task -> Story: split from (inward)
                        if "task" in source_type and "story" in target_type:
                            direction = "inward"
                            logger.info(f"Task -> Story detected, using 'split from' (inward)")
                        # Story -> Task: split to (inward - so Task is inward, Story is outward)
                        elif "story" in source_type and "task" in target_type:
                            direction = "inward"
                            logger.info(f"Story -> Task detected, using 'split to' (inward - Task split from Story)")

                # Create the link
                link_created = jira_client.create_issue_link_generic(
                    source_key=request.ticket_key,
                    target_key=target_key,
                    link_type=link_type,
                    direction=direction
                )

                if link_created:
                    links_created.append({
                        "link_type": link_type,
                        "target_key": target_key,
                        "direction": direction,
                        "status": "created"
                    })
                else:
                    links_created.append({
                        "link_type": link_type,
                        "target_key": target_key,
                        "direction": direction,
                        "status": "failed"
                    })

        # Build success message
        updated_fields = [field for field, success in updates_applied.items() if success]
        message_parts = []

        if updated_fields:
            message_parts.append(f"Updated fields: {', '.join(updated_fields)}")

        if links_created:
            successful_links = [l for l in links_created if l["status"] == "created"]
            if successful_links:
                message_parts.append(f"Created {len(successful_links)} link(s)")

        if not message_parts:
            message = f"No updates were applied to ticket {request.ticket_key}"
        else:
            message = f"Successfully updated ticket {request.ticket_key}. " + "; ".join(message_parts)

        logger.info(message)

        return UpdateTicketResponse(
            success=True,
            ticket_key=request.ticket_key,
            updated_in_jira=True,
            updates_applied=updates_applied,
            links_created=links_created,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating ticket {request.ticket_key}: {str(e)}", exc_info=True)
        return UpdateTicketResponse(
            success=False,
            ticket_key=request.ticket_key,
            updated_in_jira=False,
            updates_applied={},
            links_created=[],
            message=f"Failed to update ticket",
            error=str(e)
        )


@router.post("/jira/create-ticket",
         tags=["JIRA Operations"],
         response_model=CreateTicketResponse,
         summary="Create a new JIRA Task ticket",
         description="Create a new JIRA Task ticket. Automatically links to parent epic and story. Supports test cases and blocking relationships. Preview mode by default. Set create_ticket=true to create.")
async def create_jira_ticket(
    request: CreateTicketRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new JIRA Task ticket"""
    jira_client = get_jira_client()
    from ..dependencies import get_confluence_client

    try:
        logger.info(f"User {current_user} creating ticket (create_ticket={request.create_ticket})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Get Confluence server URL if available
        confluence_client = get_confluence_client()
        confluence_server_url = None
        if confluence_client:
            confluence_server_url = confluence_client.server_url

        # Get project key from parent epic
        project_key = jira_client.get_project_key_from_epic(request.parent_key)
        if not project_key:
            raise HTTPException(status_code=400, detail=f"Could not determine project key from epic {request.parent_key}")

        if not request.create_ticket:
            # Preview mode
            logger.info(f"Preview mode - not creating ticket in JIRA")
            return CreateTicketResponse(
                success=True,
                ticket_key=None,
                created_in_jira=False,
                links_created=[],
                preview={
                    "parent_key": request.parent_key,
                    "story_key": request.story_key,
                    "summary": request.summary,
                    "description": request.description,
                    "test_cases": request.test_cases,
                    "mandays": request.mandays,
                    "blocks": request.blocks or []
                },
                message=f"Preview: Task ticket would be created. Set create_ticket=true to commit."
            )

        # Actually create ticket
        logger.info(f"Creating task ticket in JIRA")

        # Prepare task data
        from src.planning_models import TaskPlan, CycleTimeEstimate, TaskScope

        # Create cycle time estimate only if mandays is provided
        cycle_time_estimate = None
        if request.mandays is not None:
            # Create minimal estimate with provided mandays as total_days
            # Distribute proportionally: 60% dev, 20% test, 15% review, 5% deploy
            cycle_time_estimate = CycleTimeEstimate(
                development_days=request.mandays * 0.6,
                testing_days=request.mandays * 0.2,
                review_days=request.mandays * 0.15,
                deployment_days=request.mandays * 0.05,
                total_days=request.mandays,
                confidence_level=0.7
            )

        # Create minimal TaskPlan with required fields
        # Use description as purpose, create minimal scope and expected outcome
        task_plan = TaskPlan(
            summary=request.summary,
            purpose=request.description,  # Use description as purpose
            scopes=[TaskScope(
                description=request.description,
                deliverable="Task completion"
            )],
            expected_outcomes=["Task completed successfully"],
            test_cases=[],  # Empty - will update test_case_custom_field separately
            cycle_time_estimate=cycle_time_estimate,
            epic_key=request.parent_key
        )

        # Create the task ticket with raw description to avoid duplication
        task_key = jira_client.create_task_ticket(
            task_plan=task_plan,
            project_key=project_key,
            story_key=request.story_key,
            raw_description=request.description,
            confluence_server_url=confluence_server_url
        )

        # task_key will be set if creation succeeds, otherwise an exception is raised

        # Update test cases separately if provided (as raw string for custom field)
        if request.test_cases:
            test_cases_updated = jira_client.update_test_case_custom_field(
                ticket_key=task_key,
                test_cases_content=request.test_cases
            )
            if test_cases_updated:
                logger.info(f"Added test cases to task {task_key}")

        links_created = []

        # Link to story
        link_created = jira_client.create_issue_link(
            inward_key=task_key,      # Task is inward (split from)
            outward_key=request.story_key,  # Story is outward (split to)
            link_type="Work item split"
        )

        if link_created:
            links_created.append({
                "link_type": "Work item split",
                "source_key": task_key,
                "target_key": request.story_key,
                "status": "created"
            })

        # Create blocking links if provided
        if request.blocks:
            for blocked_key in request.blocks:
                block_link_created = jira_client.create_issue_link_generic(
                    source_key=task_key,
                    target_key=blocked_key,
                    link_type="Blocks",
                    direction="outward"
                )

                if block_link_created:
                    links_created.append({
                        "link_type": "Blocks",
                        "source_key": task_key,
                        "target_key": blocked_key,
                        "status": "created"
                    })

        logger.info(f"Successfully created task {task_key}")

        return CreateTicketResponse(
            success=True,
            ticket_key=task_key,
            created_in_jira=True,
            links_created=links_created,
            message=f"Successfully created task {task_key}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating ticket: {str(e)}", exc_info=True)
        return CreateTicketResponse(
            success=False,
            ticket_key=None,
            created_in_jira=False,
            links_created=[],
            message=f"Failed to create ticket",
            error=str(e)
        )


@router.post("/jira/create-story-ticket",
         tags=["JIRA Operations"],
         response_model=CreateTicketResponse,
         summary="Create a new JIRA Story ticket",
         description="Create a new JIRA Story ticket. Automatically links to parent epic. Supports test cases. Mandays are calculated from child tasks if provided. Preview mode by default. Set create_ticket=true to create.")
async def create_story_ticket(
    request: CreateStoryTicketRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new JIRA Story ticket"""
    jira_client = get_jira_client()
    from ..dependencies import get_confluence_client

    try:
        logger.info(f"User {current_user} creating story ticket (create_ticket={request.create_ticket})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Get Confluence server URL if available
        confluence_client = get_confluence_client()
        confluence_server_url = None
        if confluence_client:
            confluence_server_url = confluence_client.server_url

        # Get project key from parent epic
        project_key = jira_client.get_project_key_from_epic(request.parent_key)
        if not project_key:
            raise HTTPException(status_code=400, detail=f"Could not determine project key from epic {request.parent_key}")

        # Process summary and description (for both preview and actual creation)
        # Extract title (everything before "As a...") and keep in summary
        # Move "As a... I want to... So that..." to description
        # Ensure summary is under 255 characters
        import re

        summary = request.summary
        description = request.description

        # Pattern to match "As a..." at the start of the user story part
        # This will match "As a [role]," or "As an [role]," or "As a [role]" (with or without comma)
        # Updated to handle both "I want to" and "I want a" formats
        # Pattern matches: "As a [role], I want [anything] [so that...]" or "As a [role] I want [anything] [so that...]"
        # Uses non-greedy match to stop before "I want" when there's no comma
        as_a_pattern = r'\s*(As\s+(?:an?\s+)?.+?(?:,\s*)?I\s+want\s+[^.]*(?:\s+[Ss]o\s+that\s+[^.]*)?)\.?'

        # Find where "As a..." starts in the summary
        as_a_match = re.search(as_a_pattern, summary, re.IGNORECASE)

        if as_a_match:
            # Get the position where "As a..." starts
            as_a_start = as_a_match.start()

            # Extract title (everything before "As a...")
            title = summary[:as_a_start].strip()

            # Extract user story (from "As a..." onwards)
            user_story_text = as_a_match.group(1).strip()

            # Use title as summary (or fallback to original if no title found)
            if title:
                summary = title
            else:
                # If no title before "As a...", remove the user story part
                summary = re.sub(as_a_pattern, '', summary, flags=re.IGNORECASE).strip()

            # Clean up summary
            summary = re.sub(r'\s+', ' ', summary).strip()

            # Add user story to description if not already there
            if user_story_text.lower() not in description.lower():
                if description:
                    description = f"{user_story_text}\n\n{description}"
                else:
                    description = user_story_text

        # Ensure summary is under 255 characters
        summary_was_truncated = False
        if len(summary) > 255:
            # Truncate at word boundary
            truncated = summary[:252]
            last_space = truncated.rfind(' ')
            if last_space > 200:  # Only truncate at word if we have enough content
                summary = truncated[:last_space] + "..."
            else:
                summary = truncated + "..."
            summary_was_truncated = True
            logger.warning(f"Summary truncated to {len(summary)} characters to meet JIRA limit")

        if not request.create_ticket:
            # Preview mode
            logger.info(f"Preview mode - not creating story ticket in JIRA")
            preview_message = f"Preview: Story ticket would be created. Set create_ticket=true to commit."
            if summary_was_truncated:
                preview_message += f" Note: Summary was truncated to {len(summary)} characters."
            return CreateTicketResponse(
                success=True,
                ticket_key=None,
                created_in_jira=False,
                links_created=[],
                preview={
                    "parent_key": request.parent_key,
                    "summary": summary,
                    "description": description,
                    "test_cases": request.test_cases,
                    "summary_length": len(summary),
                    "summary_was_truncated": summary_was_truncated
                },
                message=preview_message
            )

        # Actually create ticket
        logger.info(f"Creating story ticket in JIRA")

        # Prepare story data (summary and description already processed above)
        from src.planning_models import StoryPlan

        story_plan = StoryPlan(
            summary=summary,
            description=description,
            acceptance_criteria=[],  # Empty - can be added later if needed
            test_cases=[],
            tasks=[],  # No tasks at creation time - can be added later
            epic_key=request.parent_key,
            priority="medium"
        )

        # Create the story ticket
        story_key = jira_client.create_story_ticket(
            story_plan=story_plan,
            project_key=project_key,
            confluence_server_url=confluence_server_url
        )

        if not story_key:
            raise HTTPException(status_code=500, detail="Failed to create story ticket")

        # Add test cases if provided (via update)
        if request.test_cases:
            update_success = jira_client.update_test_case_custom_field(story_key, request.test_cases)
            if update_success:
                logger.info(f"Added test cases to story {story_key}")

        # Update PRD table with JIRA link if possible
        try:
            from ..dependencies import get_confluence_client, get_llm_client
            from src.planning_service import PlanningService
            
            confluence_client = get_confluence_client()
            llm_client = get_llm_client()
            
            if confluence_client and llm_client:
                planning_service = PlanningService(jira_client, confluence_client, llm_client)
                prd_updated = planning_service._update_prd_table_for_story(
                    story_summary=summary,
                    story_key=story_key,
                    epic_key=request.parent_key,
                    prd_row_uuid=request.prd_row_uuid
                )
                if prd_updated:
                    logger.info(f"Updated PRD table with JIRA link for story {story_key}")
                else:
                    logger.debug(f"PRD table not updated for story {story_key} (may not have PRD or no matching row)")
            else:
                logger.debug("Confluence or LLM client not available, skipping PRD update")
        except Exception as e:
            # Don't fail story creation if PRD update fails
            logger.warning(f"Error updating PRD table for story {story_key}: {e}")

        logger.info(f"Successfully created story {story_key}")

        return CreateTicketResponse(
            success=True,
            ticket_key=story_key,
            created_in_jira=True,
            links_created=[],
            message=f"Successfully created story {story_key}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating story ticket: {str(e)}", exc_info=True)
        return CreateTicketResponse(
            success=False,
            ticket_key=None,
            created_in_jira=False,
            links_created=[],
            message=f"Failed to create story ticket",
            error=str(e)
        )


@router.post("/jira/update-story-ticket",
         tags=["JIRA Operations"],
         response_model=UpdateTicketResponse,
         summary="Update a story ticket",
         description="Update an existing story ticket. Only works on Story tickets - will return an error if you try to update a different ticket type. You can update the title, description, test cases, parent epic, or add links. By default, this shows you what would change without actually updating anything. Set update_jira=true when you're ready to make the changes.")
async def update_story_ticket(
    request: UpdateStoryTicketRequest,
    current_user: str = Depends(get_current_user)
):
    """Update an existing JIRA Story ticket"""
    jira_client = get_jira_client()

    try:
        logger.info(f"User {current_user} updating story ticket {request.story_key} (update_jira={request.update_jira})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Verify ticket exists
        ticket_data = jira_client.get_ticket(request.story_key)
        if not ticket_data:
            raise HTTPException(status_code=404, detail=f"Ticket {request.story_key} not found")

        # Validate ticket type is Story
        ticket_type = jira_client.get_ticket_type(request.story_key)
        if not ticket_type or "story" not in ticket_type.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Ticket {request.story_key} is not a Story ticket (type: {ticket_type}). This endpoint only works with Story tickets."
            )

        # Track what updates were applied
        updates_applied = {}
        links_created = []

        if not request.update_jira:
            # Preview mode - just return what would be updated
            logger.info(f"Preview mode for {request.story_key} - not updating JIRA")

            preview_data = {
                "story_key": request.story_key,
                "current_summary": ticket_data.get('fields', {}).get('summary', ''),
                "current_description": jira_client._extract_text_from_adf(
                    ticket_data.get('fields', {}).get('description', {})
                ) if isinstance(ticket_data.get('fields', {}).get('description'), dict) else ticket_data.get('fields', {}).get('description', ''),
            }

            # Get current parent epic
            current_parent = ticket_data.get('fields', {}).get('parent', {})
            if current_parent:
                preview_data["current_parent_key"] = current_parent.get('key', '')

            if request.summary:
                preview_data["new_summary"] = request.summary
            if request.description:
                preview_data["new_description"] = request.description
            if request.test_cases:
                preview_data["new_test_cases"] = request.test_cases
            if request.parent_key:
                preview_data["new_parent_key"] = request.parent_key
            if request.links:
                preview_data["links_to_create"] = [
                    {
                        "link_type": link.link_type,
                        "target_key": link.target_key,
                        "direction": link.direction
                    }
                    for link in request.links
                ]

            return UpdateTicketResponse(
                success=True,
                ticket_key=request.story_key,
                updated_in_jira=False,
                updates_applied={},
                links_created=[],
                preview=preview_data,
                message=f"Preview: Story ticket {request.story_key} would be updated. Set update_jira=true to commit."
            )

        # Actually update JIRA
        logger.info(f"Updating story ticket {request.story_key} in JIRA")

        # Update summary if provided
        if request.summary:
            logger.info(f"Updating summary for {request.story_key}")
            summary_updated = jira_client.update_ticket_summary(
                ticket_key=request.story_key,
                summary=request.summary
            )
            updates_applied["summary"] = summary_updated
            if not summary_updated:
                logger.warning(f"Failed to update summary for {request.story_key}")

        # Update description if provided
        if request.description:
            logger.info(f"Updating description for {request.story_key}")
            description_updated = jira_client.update_ticket_description(
                ticket_key=request.story_key,
                description=request.description,
                dry_run=False
            )
            updates_applied["description"] = description_updated
            if not description_updated:
                logger.warning(f"Failed to update description for {request.story_key}")
            else:
                # Handle image attachments if description contains images
                from ..dependencies import get_confluence_client
                confluence_client = get_confluence_client()
                confluence_server_url = None
                if confluence_client:
                    confluence_server_url = confluence_client.server_url

                jira_client._attach_images_from_description(
                    request.story_key,
                    request.description,
                    confluence_server_url
                )

        # Update test cases if provided
        if request.test_cases:
            logger.info(f"Updating test cases for {request.story_key}")
            test_cases_updated = jira_client.update_test_case_custom_field(
                ticket_key=request.story_key,
                test_cases_content=request.test_cases
            )
            updates_applied["test_cases"] = test_cases_updated
            if not test_cases_updated:
                logger.warning(f"Failed to update test cases for {request.story_key}")

        # Update parent epic if provided
        if request.parent_key:
            logger.info(f"Updating parent epic for {request.story_key} to {request.parent_key}")
            parent_updated = jira_client.update_ticket_parent(
                ticket_key=request.story_key,
                parent_key=request.parent_key
            )
            updates_applied["parent_key"] = parent_updated
            if not parent_updated:
                logger.warning(f"Failed to update parent epic for {request.story_key}")

        # Process links if provided
        if request.links:
            logger.info(f"Processing {len(request.links)} link(s) for {request.story_key}")

            for link_req in request.links:
                link_type = link_req.link_type
                target_key = link_req.target_key
                direction = link_req.direction

                # Smart split detection
                if "split" in link_type.lower():
                    logger.info(f"Detected split link type, applying smart direction logic")

                    # Get ticket types
                    source_type = jira_client.get_ticket_type(request.story_key)
                    target_type = jira_client.get_ticket_type(target_key)

                    if source_type and target_type:
                        logger.info(f"Source type: {source_type}, Target type: {target_type}")

                        # Story -> Task: need to swap to get correct relationship
                        # With direction="outward": inwardIssue=source, outwardIssue=target
                        # So: source=story, target=task, direction="outward"
                        # This creates: inwardIssue=story, outwardIssue=task
                        if "story" in source_type and "task" in target_type:
                            direction = "outward"
                            logger.info(f"Story -> Task detected, using 'split to' (outward - swapped for correct relationship)")

                # Create the link
                # Smart detection already sets direction="outward" for Story->Task with "Work item split"
                # With direction="outward": inwardIssue=source, outwardIssue=target
                # So: source=story, target=task, direction="outward" creates: inwardIssue=story, outwardIssue=task
                link_created = jira_client.create_issue_link_generic(
                    source_key=request.story_key,
                    target_key=target_key,
                    link_type=link_type,
                    direction=direction
                )

                if link_created:
                    links_created.append({
                        "link_type": link_type,
                        "target_key": target_key,
                        "direction": direction,
                        "status": "created"
                    })
                else:
                    links_created.append({
                        "link_type": link_type,
                        "target_key": target_key,
                        "direction": direction,
                        "status": "failed"
                    })

        # Build success message
        updated_fields = [field for field, success in updates_applied.items() if success]
        message_parts = []

        if updated_fields:
            message_parts.append(f"Updated fields: {', '.join(updated_fields)}")

        if links_created:
            successful_links = [l for l in links_created if l["status"] == "created"]
            if successful_links:
                message_parts.append(f"Created {len(successful_links)} link(s)")

        if not message_parts:
            message = f"No updates were applied to story ticket {request.story_key}"
        else:
            message = f"Successfully updated story ticket {request.story_key}. " + "; ".join(message_parts)

        logger.info(message)

        # Update PRD table with JIRA link if possible
        try:
            from ..dependencies import get_confluence_client, get_llm_client
            from src.planning_service import PlanningService
            
            confluence_client = get_confluence_client()
            llm_client = get_llm_client()
            
            if confluence_client and llm_client:
                planning_service = PlanningService(jira_client, confluence_client, llm_client)
                
                # Get epic_key from ticket (use updated parent if changed, otherwise current parent)
                epic_key = None
                if request.parent_key:
                    epic_key = request.parent_key
                else:
                    # Get current parent from ticket
                    current_parent = ticket_data.get('fields', {}).get('parent', {})
                    if current_parent:
                        epic_key = current_parent.get('key')
                
                # Get story summary (use updated summary if changed, otherwise current summary)
                story_summary = request.summary if request.summary else ticket_data.get('fields', {}).get('summary', '')
                
                if epic_key and story_summary:
                    prd_updated = planning_service._update_prd_table_for_story(
                        story_summary=story_summary,
                        story_key=request.story_key,
                        epic_key=epic_key,
                        prd_row_uuid=None  # No UUID available for manual updates
                    )
                    if prd_updated:
                        logger.info(f"Updated PRD table with JIRA link for story {request.story_key}")
                    else:
                        logger.debug(f"PRD table not updated for story {request.story_key} (may not have PRD or no matching row)")
                else:
                    logger.debug(f"Cannot update PRD table: epic_key={epic_key}, story_summary={bool(story_summary)}")
            else:
                logger.debug("Confluence or LLM client not available, skipping PRD update")
        except Exception as e:
            # Don't fail story update if PRD update fails
            logger.warning(f"Error updating PRD table for story {request.story_key}: {e}")

        return UpdateTicketResponse(
            success=True,
            ticket_key=request.story_key,
            updated_in_jira=True,
            updates_applied=updates_applied,
            links_created=links_created,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating story ticket {request.story_key}: {str(e)}", exc_info=True)
        return UpdateTicketResponse(
            success=False,
            ticket_key=request.story_key,
            updated_in_jira=False,
            updates_applied={},
            links_created=[],
            message=f"Failed to update story ticket",
            error=str(e)
        )


def _process_single_story_update(
    jira_client,
    story_item: StoryUpdateItem,
    dry_run: bool
) -> StoryUpdateResult:
    """
    Process a single story update (helper function for bulk operations)

    Args:
        jira_client: JiraClient instance
        story_item: StoryUpdateItem with update data
        dry_run: Whether to actually update JIRA

    Returns:
        StoryUpdateResult with update status
    """
    from ..dependencies import get_confluence_client

    story_key = story_item.story_key
    updates_applied = {}
    links_created = []
    preview_data = None
    error = None

    try:
        # Verify ticket exists
        ticket_data = jira_client.get_ticket(story_key)
        if not ticket_data:
            return StoryUpdateResult(
                story_key=story_key,
                success=False,
                updated_in_jira=False,
                updates_applied={},
                links_created=[],
                error=f"Ticket {story_key} not found"
            )

        # Validate ticket type is Story
        ticket_type = jira_client.get_ticket_type(story_key)
        if not ticket_type or "story" not in ticket_type.lower():
            return StoryUpdateResult(
                story_key=story_key,
                success=False,
                updated_in_jira=False,
                updates_applied={},
                links_created=[],
                error=f"Ticket {story_key} is not a Story ticket (type: {ticket_type})"
            )

        # Preview mode
        if dry_run:
            preview_data = {
                "story_key": story_key,
                "current_summary": ticket_data.get('fields', {}).get('summary', ''),
                "current_description": jira_client._extract_text_from_adf(
                    ticket_data.get('fields', {}).get('description', {})
                ) if isinstance(ticket_data.get('fields', {}).get('description'), dict) else ticket_data.get('fields', {}).get('description', ''),
            }

            current_parent = ticket_data.get('fields', {}).get('parent', {})
            if current_parent:
                preview_data["current_parent_key"] = current_parent.get('key', '')

            if story_item.summary:
                preview_data["new_summary"] = story_item.summary
            if story_item.description:
                preview_data["new_description"] = story_item.description
            if story_item.test_cases:
                preview_data["new_test_cases"] = story_item.test_cases
            if story_item.parent_key:
                preview_data["new_parent_key"] = story_item.parent_key
            if story_item.links:
                preview_data["links_to_create"] = [
                    {
                        "link_type": link.link_type,
                        "target_key": link.target_key,
                        "direction": link.direction
                    }
                    for link in story_item.links
                ]

            return StoryUpdateResult(
                story_key=story_key,
                success=True,
                updated_in_jira=False,
                updates_applied={},
                links_created=[],
                preview=preview_data,
                error=None
            )

        # Actually update JIRA
        logger.info(f"Updating story ticket {story_key} in JIRA")

        # Update summary if provided
        if story_item.summary:
            logger.info(f"Updating summary for {story_key}")
            summary_updated = jira_client.update_ticket_summary(
                ticket_key=story_key,
                summary=story_item.summary
            )
            updates_applied["summary"] = summary_updated
            if not summary_updated:
                logger.warning(f"Failed to update summary for {story_key}")

        # Update description if provided
        if story_item.description:
            logger.info(f"Updating description for {story_key}")
            description_updated = jira_client.update_ticket_description(
                ticket_key=story_key,
                description=story_item.description,
                dry_run=False
            )
            updates_applied["description"] = description_updated
            if not description_updated:
                logger.warning(f"Failed to update description for {story_key}")
            else:
                # Handle image attachments if description contains images
                confluence_client = get_confluence_client()
                confluence_server_url = None
                if confluence_client:
                    confluence_server_url = confluence_client.server_url

                jira_client._attach_images_from_description(
                    story_key,
                    story_item.description,
                    confluence_server_url
                )

        # Update test cases if provided
        if story_item.test_cases:
            logger.info(f"Updating test cases for {story_key}")
            test_cases_updated = jira_client.update_test_case_custom_field(
                ticket_key=story_key,
                test_cases_content=story_item.test_cases
            )
            updates_applied["test_cases"] = test_cases_updated
            if not test_cases_updated:
                logger.warning(f"Failed to update test cases for {story_key}")

        # Update parent epic if provided
        if story_item.parent_key:
            logger.info(f"Updating parent epic for {story_key} to {story_item.parent_key}")
            parent_updated = jira_client.update_ticket_parent(
                ticket_key=story_key,
                parent_key=story_item.parent_key
            )
            updates_applied["parent_key"] = parent_updated
            if not parent_updated:
                logger.warning(f"Failed to update parent epic for {story_key}")

        # Process links if provided
        if story_item.links:
            logger.info(f"Processing {len(story_item.links)} link(s) for {story_key}")

            for link_req in story_item.links:
                link_type = link_req.link_type
                target_key = link_req.target_key
                direction = link_req.direction

                # Smart split detection
                if "split" in link_type.lower():
                    logger.info(f"Detected split link type, applying smart direction logic")

                    # Get ticket types
                    source_type = jira_client.get_ticket_type(story_key)
                    target_type = jira_client.get_ticket_type(target_key)

                    if source_type and target_type:
                        logger.info(f"Source type: {source_type}, Target type: {target_type}")

                        # Story -> Task: need to swap to get correct relationship
                        # With direction="outward": inwardIssue=source, outwardIssue=target
                        # So: source=story, target=task, direction="outward"
                        # This creates: inwardIssue=story, outwardIssue=task
                        if "story" in source_type and "task" in target_type:
                            direction = "outward"
                            logger.info(f"Story -> Task detected, using 'split to' (outward - swapped for correct relationship)")

                # Create the link
                # Smart detection already sets direction="outward" for Story->Task with "Work item split"
                # With direction="outward": inwardIssue=source, outwardIssue=target
                # So: source=story, target=task, direction="outward" creates: inwardIssue=story, outwardIssue=task
                link_created = jira_client.create_issue_link_generic(
                    source_key=story_key,
                    target_key=target_key,
                    link_type=link_type,
                    direction=direction
                )

                if link_created:
                    links_created.append({
                        "link_type": link_type,
                        "target_key": target_key,
                        "direction": direction,
                        "status": "created"
                    })
                else:
                    links_created.append({
                        "link_type": link_type,
                        "target_key": target_key,
                        "direction": direction,
                        "status": "failed"
                    })

        # Update PRD table with JIRA link if possible
        try:
            from ..dependencies import get_confluence_client, get_llm_client
            from src.planning_service import PlanningService
            
            confluence_client = get_confluence_client()
            llm_client = get_llm_client()
            
            if confluence_client and llm_client:
                planning_service = PlanningService(jira_client, confluence_client, llm_client)
                
                # Get epic_key from ticket (use updated parent if changed, otherwise current parent)
                epic_key = None
                if story_item.parent_key:
                    epic_key = story_item.parent_key
                else:
                    # Get current parent from ticket
                    current_parent = ticket_data.get('fields', {}).get('parent', {})
                    if current_parent:
                        epic_key = current_parent.get('key')
                
                # Get story summary (use updated summary if changed, otherwise current summary)
                story_summary = story_item.summary if story_item.summary else ticket_data.get('fields', {}).get('summary', '')
                
                if epic_key and story_summary:
                    prd_updated = planning_service._update_prd_table_for_story(
                        story_summary=story_summary,
                        story_key=story_key,
                        epic_key=epic_key,
                        prd_row_uuid=None  # No UUID available for manual updates
                    )
                    if prd_updated:
                        logger.info(f"Updated PRD table with JIRA link for story {story_key}")
                    else:
                        logger.debug(f"PRD table not updated for story {story_key} (may not have PRD or no matching row)")
                else:
                    logger.debug(f"Cannot update PRD table: epic_key={epic_key}, story_summary={bool(story_summary)}")
            else:
                logger.debug("Confluence or LLM client not available, skipping PRD update")
        except Exception as e:
            # Don't fail story update if PRD update fails
            logger.warning(f"Error updating PRD table for story {story_key}: {e}")

        return StoryUpdateResult(
            story_key=story_key,
            success=True,
            updated_in_jira=True,
            updates_applied=updates_applied,
            links_created=links_created,
            error=None
        )

    except Exception as e:
        logger.error(f"Error updating story ticket {story_key}: {str(e)}", exc_info=True)
        return StoryUpdateResult(
            story_key=story_key,
            success=False,
            updated_in_jira=False,
            updates_applied={},
            links_created=[],
            error=str(e)
        )


@router.post("/jira/bulk-update-stories",
         tags=["JIRA Operations"],
         response_model=Union[BulkUpdateStoriesResponse, BatchResponse],
         summary="Bulk update multiple story tickets",
         description="Update multiple story tickets in a single request. Each story can have different update values. Supports preview mode and async processing.")
async def bulk_update_stories(
    request: BulkUpdateStoriesRequest,
    current_user: str = Depends(get_current_user)
):
    """Bulk update multiple story tickets"""
    jira_client = get_jira_client()

    try:
        logger.info(f"User {current_user} bulk updating {len(request.stories)} story tickets (dry_run={request.dry_run}, async_mode={request.async_mode})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Validate request
        if not request.stories:
            raise HTTPException(status_code=400, detail="At least one story must be provided")

        if len(request.stories) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 stories can be updated in a single request")

        # If async mode, enqueue job
        if request.async_mode:
            from ..job_queue import get_redis_pool
            from ..dependencies import jobs

            job_id = str(uuid.uuid4())

            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="bulk_story_update",
                status="started",
                progress={"message": f"Queued for bulk updating {len(request.stories)} stories"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                story_keys=[item.story_key for item in request.stories]
            )

            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_bulk_story_update_worker',
                job_id=job_id,
                stories_data=[item.dict() for item in request.stories],
                dry_run=request.dry_run,
                _job_id=job_id
            )

            logger.info(f"Enqueued bulk story update job {job_id} for {len(request.stories)} stories")

            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Bulk story update queued for {len(request.stories)} stories",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=len(request.stories),
                update_jira=not request.dry_run,
                safety_note="JIRA will only be updated if dry_run is false"
            )

        # Synchronous mode - process all stories
        results = []
        successful = 0
        failed = 0

        for i, story_item in enumerate(request.stories, 1):
            logger.info(f"Processing story {i}/{len(request.stories)}: {story_item.story_key}")

            result = _process_single_story_update(
                jira_client=jira_client,
                story_item=story_item,
                dry_run=request.dry_run
            )

            results.append(result)

            if result.success:
                successful += 1
            else:
                failed += 1

        message = f"Bulk update completed: {successful} successful, {failed} failed"
        if request.dry_run:
            message += " (preview mode - no JIRA changes made)"

        logger.info(message)

        return BulkUpdateStoriesResponse(
            total_stories=len(request.stories),
            successful=successful,
            failed=failed,
            results=results,
            job_id=None,
            status_url=None,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk story update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to bulk update stories: {str(e)}")


@router.post("/jira/bulk-create-tasks",
         tags=["JIRA Operations"],
         response_model=Union[BulkCreateTasksResponse, BatchResponse],
         summary="Bulk create multiple task tickets",
         description="Create multiple task tickets in a single request. All tickets are created first, then all links are created. Preview mode by default. Set create_tickets=true to create. Supports async_mode for background processing.")
async def bulk_create_tasks(
    request: BulkCreateTasksRequest,
    current_user: str = Depends(get_current_user)
):
    """Bulk create multiple task tickets"""
    jira_client = get_jira_client()
    from ..dependencies import get_confluence_client
    from ..job_queue import get_redis_pool

    try:
        logger.info(f"User {current_user} bulk creating {len(request.tasks)} task tickets (create_tickets={request.create_tickets}, async_mode={request.async_mode})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Validate request
        if not request.tasks:
            raise HTTPException(status_code=400, detail="At least one task must be provided")

        if len(request.tasks) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 tasks can be created in a single request")

        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active jobs on task story keys
            duplicate_stories = []
            story_keys = list(set([task.story_key for task in request.tasks]))
            for story_key in story_keys:
                active_job_id = get_active_job_for_ticket(story_key)
                if active_job_id:
                    duplicate_stories.append(story_key)
                    logger.warning(f"Skipping story {story_key} - already being processed in job {active_job_id}")
            
            if duplicate_stories:
                raise HTTPException(
                    status_code=409,
                    detail=f"Some stories are already being processed: {', '.join(duplicate_stories)}",
                    headers={"X-Duplicate-Stories": ",".join(duplicate_stories)}
                )
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="bulk_task_creation",
                status="started",
                progress={"message": f"Queued for creating {len(request.tasks)} task tickets"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                story_keys=story_keys
            )
            
            # Register all story keys for duplicate prevention
            for story_key in story_keys:
                register_ticket_job(story_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_bulk_task_creation_worker',
                job_id=job_id,
                tasks_data=[task.dict() for task in request.tasks],
                create_tickets=request.create_tickets,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued bulk task creation job {job_id} for {len(request.tasks)} tasks")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Bulk task creation queued for {len(request.tasks)} tasks",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=len(request.tasks),
                update_jira=request.create_tickets,
                safety_note="JIRA will only be updated if create_tickets is true"
            )

        if not request.create_tickets:
            # Preview mode
            logger.info(f"Preview mode - not creating tickets in JIRA")
            preview_results = []
            for i, task_item in enumerate(request.tasks):
                preview_results.append(BulkCreateResult(
                    index=i,
                    success=True,
                    ticket_key=None,
                    error=None,
                    links_created=[]
                ))
            
            return BulkCreateTasksResponse(
                total_tasks=len(request.tasks),
                successful=len(request.tasks),
                failed=0,
                results=preview_results,
                created_tickets=[],
                message=f"Preview: {len(request.tasks)} task tickets would be created. Set create_tickets=true to commit."
            )

        # Get Confluence server URL if available
        confluence_client = get_confluence_client()
        confluence_server_url = None
        if confluence_client:
            confluence_server_url = confluence_client.server_url

        # Get project key from first task's parent epic
        project_key = jira_client.get_project_key_from_epic(request.tasks[0].parent_key)
        if not project_key:
            raise HTTPException(status_code=400, detail=f"Could not determine project key from epic {request.tasks[0].parent_key}")

        # Build issue data for all tasks
        from src.planning_models import TaskPlan, CycleTimeEstimate, TaskScope
        
        tickets_data = []
        task_index_to_item = {}  # Map index to task item for link creation later
        pending_links = []  # Collect all links to create after tickets are created
        
        for i, task_item in enumerate(request.tasks):
            # Create cycle time estimate if mandays provided
            cycle_time_estimate = None
            if task_item.mandays is not None:
                cycle_time_estimate = CycleTimeEstimate(
                    development_days=task_item.mandays * 0.6,
                    testing_days=task_item.mandays * 0.2,
                    review_days=task_item.mandays * 0.15,
                    deployment_days=task_item.mandays * 0.05,
                    total_days=task_item.mandays,
                    confidence_level=0.7
                )

            # Create TaskPlan
            task_plan = TaskPlan(
                summary=task_item.summary,
                purpose=task_item.description,
                scopes=[TaskScope(
                    description=task_item.description,
                    deliverable="Task completion"
                )],
                expected_outcomes=["Task completed successfully"],
                test_cases=[],
                cycle_time_estimate=cycle_time_estimate,
                epic_key=task_item.parent_key
            )

            # Build issue data (similar to create_task_ticket)
            description_adf = jira_client._convert_markdown_to_adf(task_item.description)
            
            issue_data = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": task_item.summary,
                    "description": description_adf,
                    "issuetype": {"name": "Task"}
                }
            }

            # Add parent epic
            if task_item.parent_key:
                epic_type = jira_client.get_ticket_type(task_item.parent_key)
                if epic_type and 'epic' in epic_type.lower():
                    issue_data["fields"]["parent"] = {"key": task_item.parent_key}

            # Add mandays if available
            if cycle_time_estimate and jira_client.mandays_custom_field:
                issue_data["fields"][jira_client.mandays_custom_field] = cycle_time_estimate.total_days

            # Add test cases if available
            if task_item.test_cases and jira_client.test_case_custom_field:
                test_cases_adf = jira_client._convert_markdown_to_adf(task_item.test_cases)
                issue_data["fields"][jira_client.test_case_custom_field] = test_cases_adf

            tickets_data.append(issue_data)
            task_index_to_item[i] = task_item

            # Collect link information for later
            if task_item.story_key:
                pending_links.append({
                    "index": i,
                    "from": None,  # Will be set after ticket creation
                    "to": task_item.story_key,
                    "type": "Work item split",
                    "direction": "outward"  # Task (source) is inward (split from), Story (target) is outward (split to)
                })
            
            if task_item.blocks:
                for blocked_key in task_item.blocks:
                    pending_links.append({
                        "index": i,
                        "from": None,  # Will be set after ticket creation
                        "to": blocked_key,
                        "type": "Blocks",
                        "direction": "outward"
                    })

        # Create all tickets first
        logger.info(f"Creating {len(tickets_data)} task tickets in bulk...")
        bulk_results = jira_client.bulk_create_tickets(tickets_data)
        
        created_ticket_keys = bulk_results.get("created_tickets", [])
        failed_tickets = bulk_results.get("failed_tickets", [])
        
        # Build results
        results = []
        successful = 0
        failed = 0
        index_to_ticket_key = {}  # Map index to created ticket key
        
        for i in range(len(request.tasks)):
            if i < len(created_ticket_keys):
                ticket_key = created_ticket_keys[i]
                index_to_ticket_key[i] = ticket_key
                results.append(BulkCreateResult(
                    index=i,
                    success=True,
                    ticket_key=ticket_key,
                    error=None,
                    links_created=[]
                ))
                successful += 1
            else:
                error_msg = "Failed to create ticket"
                if i < len(failed_tickets):
                    error_msg = str(failed_tickets[i])
                results.append(BulkCreateResult(
                    index=i,
                    success=False,
                    ticket_key=None,
                    error=error_msg,
                    links_created=[]
                ))
                failed += 1

        # Now create all links after all tickets are created
        logger.info(f"All tickets created. Creating {len(pending_links)} pending links...")
        
        for link_info in pending_links:
            index = link_info["index"]
            if index not in index_to_ticket_key:
                continue  # Skip if ticket creation failed
            
            source_key = index_to_ticket_key[index]
            target_key = link_info["to"]
            link_type = link_info["type"]
            direction = link_info.get("direction", "outward")
            
            # For "Work item split", we need to swap source and target to get correct relationship
            # With direction="outward": inwardIssue=source, outwardIssue=target
            # So: source=story, target=task, direction="outward"
            # This creates: inwardIssue=story, outwardIssue=task
            # This makes Task show "split from" Story correctly
            if link_type == "Work item split":
                # Swap: Story as source, Task as target, direction="outward"
                # This creates: inwardIssue=story, outwardIssue=task
                link_success = jira_client.create_issue_link_generic(
                    source_key=target_key,  # Story as source
                    target_key=source_key,  # Task as target
                    link_type=link_type,
                    direction="outward"  # This makes: inwardIssue=source (story), outwardIssue=target (task)
                )
            else:
                # For other link types, use original parameters
                link_success = jira_client.create_issue_link_generic(
                    source_key=source_key,
                    target_key=target_key,
                    link_type=link_type,
                    direction=direction
                )
            
            if link_success:
                results[index].links_created.append({
                    "link_type": link_type,
                    "source_key": source_key,
                    "target_key": target_key,
                    "status": "created"
                })
            else:
                results[index].links_created.append({
                    "link_type": link_type,
                    "source_key": source_key,
                    "target_key": target_key,
                    "status": "failed"
                })

        message = f"Bulk creation completed: {successful} successful, {failed} failed"
        logger.info(message)

        return BulkCreateTasksResponse(
            total_tasks=len(request.tasks),
            successful=successful,
            failed=failed,
            results=results,
            created_tickets=created_ticket_keys,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk task creation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to bulk create tasks: {str(e)}")


@router.post("/jira/bulk-create-stories",
         tags=["JIRA Operations"],
         response_model=BulkCreateStoriesResponse,
         summary="Bulk create multiple story tickets",
         description="Create multiple story tickets in a single request. All tickets are created first, then all links are created. Preview mode by default. Set create_tickets=true to create.")
async def bulk_create_stories(
    request: BulkCreateStoriesRequest,
    current_user: str = Depends(get_current_user)
):
    """Bulk create multiple story tickets"""
    jira_client = get_jira_client()
    from ..dependencies import get_confluence_client

    try:
        logger.info(f"User {current_user} bulk creating {len(request.stories)} story tickets (create_tickets={request.create_tickets})")

        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")

        # Validate request
        if not request.stories:
            raise HTTPException(status_code=400, detail="At least one story must be provided")

        if len(request.stories) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 stories can be created in a single request")

        if not request.create_tickets:
            # Preview mode
            logger.info(f"Preview mode - not creating tickets in JIRA")
            preview_results = []
            for i, story_item in enumerate(request.stories):
                preview_results.append(BulkCreateResult(
                    index=i,
                    success=True,
                    ticket_key=None,
                    error=None,
                    links_created=[]
                ))
            
            return BulkCreateStoriesResponse(
                total_stories=len(request.stories),
                successful=len(request.stories),
                failed=0,
                results=preview_results,
                created_tickets=[],
                message=f"Preview: {len(request.stories)} story tickets would be created. Set create_tickets=true to commit."
            )

        # Get Confluence server URL if available
        confluence_client = get_confluence_client()
        confluence_server_url = None
        if confluence_client:
            confluence_server_url = confluence_client.server_url

        # Get project key from first story's parent epic
        project_key = jira_client.get_project_key_from_epic(request.stories[0].parent_key)
        if not project_key:
            raise HTTPException(status_code=400, detail=f"Could not determine project key from epic {request.stories[0].parent_key}")

        # Build issue data for all stories
        from src.planning_models import StoryPlan
        
        tickets_data = []
        
        for story_item in request.stories:
            # Create StoryPlan
            story_plan = StoryPlan(
                summary=story_item.summary,
                description=story_item.description,
                acceptance_criteria=[],
                epic_key=story_item.parent_key
            )

            # Build issue data (similar to create_story_ticket)
            description_adf = jira_client._convert_markdown_to_adf(story_item.description)
            
            issue_data = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": story_item.summary,
                    "description": description_adf,
                    "issuetype": {"name": "Story"}
                }
            }

            # Add parent epic
            if story_item.parent_key:
                issue_data["fields"]["parent"] = {"key": story_item.parent_key}

            # Add test cases if available
            if story_item.test_cases and jira_client.test_case_custom_field:
                test_cases_adf = jira_client._convert_markdown_to_adf(story_item.test_cases)
                issue_data["fields"][jira_client.test_case_custom_field] = test_cases_adf

            tickets_data.append(issue_data)

        # Create all tickets first
        logger.info(f"Creating {len(tickets_data)} story tickets in bulk...")
        bulk_results = jira_client.bulk_create_tickets(tickets_data)
        
        created_ticket_keys = bulk_results.get("created_tickets", [])
        failed_tickets = bulk_results.get("failed_tickets", [])
        
        # Build results
        results = []
        successful = 0
        failed = 0
        
        for i in range(len(request.stories)):
            if i < len(created_ticket_keys):
                ticket_key = created_ticket_keys[i]
                results.append(BulkCreateResult(
                    index=i,
                    success=True,
                    ticket_key=ticket_key,
                    error=None,
                    links_created=[]
                ))
                successful += 1
            else:
                error_msg = "Failed to create ticket"
                if i < len(failed_tickets):
                    error_msg = str(failed_tickets[i])
                results.append(BulkCreateResult(
                    index=i,
                    success=False,
                    ticket_key=None,
                    error=error_msg,
                    links_created=[]
                ))
                failed += 1

        # Update PRD tables with JIRA links (group by epic for efficiency)
        try:
            from ..dependencies import get_confluence_client, get_llm_client
            from src.planning_service import PlanningService
            
            confluence_client = get_confluence_client()
            llm_client = get_llm_client()
            
            if confluence_client and llm_client:
                planning_service = PlanningService(jira_client, confluence_client, llm_client)
                
                # Group stories by epic for batch PRD updates
                stories_by_epic = {}
                for i, story_item in enumerate(request.stories):
                    if i < len(created_ticket_keys):
                        epic_key = story_item.parent_key
                        if epic_key not in stories_by_epic:
                            stories_by_epic[epic_key] = []
                        stories_by_epic[epic_key].append({
                            'story_item': story_item,
                            'story_key': created_ticket_keys[i],
                            'index': i
                        })
                
                # Update PRD for each epic
                for epic_key, epic_stories in stories_by_epic.items():
                    for story_info in epic_stories:
                        try:
                            prd_updated = planning_service._update_prd_table_for_story(
                                story_summary=story_info['story_item'].summary,
                                story_key=story_info['story_key'],
                                epic_key=epic_key,
                                prd_row_uuid=story_info['story_item'].prd_row_uuid
                            )
                            if prd_updated:
                                logger.info(f"Updated PRD table with JIRA link for story {story_info['story_key']}")
                        except Exception as e:
                            logger.warning(f"Error updating PRD table for story {story_info['story_key']}: {e}")
            else:
                logger.debug("Confluence or LLM client not available, skipping PRD updates")
        except Exception as e:
            # Don't fail bulk creation if PRD updates fail
            logger.warning(f"Error updating PRD tables during bulk creation: {e}")

        message = f"Bulk creation completed: {successful} successful, {failed} failed"
        logger.info(message)

        return BulkCreateStoriesResponse(
            total_stories=len(request.stories),
            successful=successful,
            failed=failed,
            results=results,
            created_tickets=created_ticket_keys,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk story creation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to bulk create stories: {str(e)}")