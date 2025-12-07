"""
JIRA Operations Routes
Endpoints for JIRA ticket operations
"""
from fastapi import APIRouter, HTTPException, Depends
import logging

from ..models.jira_operations import (
    UpdateTicketRequest,
    CreateTicketRequest,
    CreateStoryTicketRequest,
    UpdateStoryTicketRequest,
    UpdateTicketResponse,
    CreateTicketResponse
)
from ..dependencies import get_jira_client
from ..auth import get_current_user

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
                        # Story -> Task: split to (outward)
                        elif "story" in source_type and "task" in target_type:
                            direction = "outward"
                            logger.info(f"Story -> Task detected, using 'split to' (outward)")
                
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
    
    try:
        logger.info(f"User {current_user} creating ticket (create_ticket={request.create_ticket})")
        
        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")
        
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
            raw_description=request.description
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
            inward_key=request.story_key,
            outward_key=task_key,
            link_type="Work item split"
        )
        
        if link_created:
            links_created.append({
                "link_type": "Work item split",
                "source_key": request.story_key,
                "target_key": task_key,
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
    
    try:
        logger.info(f"User {current_user} creating story ticket (create_ticket={request.create_ticket})")
        
        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")
        
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
        # This will match "As a [role]," or "As an [role],"
        as_a_pattern = r'\s*(As\s+(?:an?\s+)?[^,]+,\s*I\s+want\s+to\s+[^.]*(?:\s+so\s+that\s+[^.]*)?)\.?'
        
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
            project_key=project_key
        )
        
        if not story_key:
            raise HTTPException(status_code=500, detail="Failed to create story ticket")
        
        # Add test cases if provided (via update)
        if request.test_cases:
            update_success = jira_client.update_test_case_custom_field(story_key, request.test_cases)
            if update_success:
                logger.info(f"Added test cases to story {story_key}")
        
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
                        
                        # Story -> Task: split to (outward)
                        if "story" in source_type and "task" in target_type:
                            direction = "outward"
                            logger.info(f"Story -> Task detected, using 'split to' (outward)")
                
                # Create the link
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