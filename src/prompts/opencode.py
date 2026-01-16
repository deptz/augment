"""
OpenCode Prompts
Code-aware prompt templates for OpenCode execution
"""
import json
from typing import Dict, Any, List, Optional

from ..opencode_schemas import (
    TICKET_DESCRIPTION_SCHEMA,
    TASK_BREAKDOWN_SCHEMA,
    COVERAGE_CHECK_SCHEMA,
    get_schema_for_prompt
)


def ticket_description_prompt(
    ticket_data: Dict[str, Any],
    repos: List[str],
    additional_context: Optional[str] = None
) -> str:
    """
    Generate a code-aware prompt for ticket description generation.
    
    Args:
        ticket_data: Dict with ticket info (key, summary, description, etc.)
        repos: List of repository names in workspace
        additional_context: Optional additional context
        
    Returns:
        Formatted prompt string
    """
    ticket_key = ticket_data.get('key', 'UNKNOWN')
    summary = ticket_data.get('summary', 'No summary')
    existing_description = ticket_data.get('description', 'No existing description')
    parent_summary = ticket_data.get('parent_summary', 'N/A')
    
    repos_str = ', '.join(repos) if repos else 'No repositories'
    
    context_section = ""
    if additional_context:
        context_section = f"""
**Additional Context:**
{additional_context}
"""
    
    schema_json = get_schema_for_prompt("ticket_description")
    
    return f"""You have full filesystem access to these repositories: {repos_str}

You are analyzing the codebase to generate a comprehensive ticket description.

**Ticket Information:**
- Key: {ticket_key}
- Summary: {summary}
- Parent/Epic: {parent_summary}

**Current Description:**
{existing_description}
{context_section}
**Your Task:**

1. **Search the codebase** to identify relevant files, modules, and components related to this ticket
2. **Analyze the code structure** to understand what needs to be modified
3. **Reference actual file paths** and code patterns you find

Generate a ticket description that:
- References real modules/files from the codebase when applicable
- Describes impacted components based on actual code structure
- Lists assumptions grounded in what you find in the code
- Proposes acceptance criteria tied to specific code paths
- Does NOT hallucinate components - only reference what actually exists

**IMPORTANT - OUTPUT INSTRUCTIONS:**

After completing your analysis, you MUST write your result to `/workspace/result.json`

The JSON must follow this exact schema:
```json
{schema_json}
```

Use the `write_file` tool to save the result. This is REQUIRED.

Example of how to write the result:
1. Analyze the codebase thoroughly
2. Formulate your findings
3. Use write_file to save to /workspace/result.json with the schema above

Do NOT just output the JSON - you must actually write it to the file.
"""


def task_breakdown_prompt(
    story_data: Dict[str, Any],
    repos: List[str],
    additional_context: Optional[str] = None,
    max_tasks: int = 10
) -> str:
    """
    Generate a code-aware prompt for task breakdown.
    
    Args:
        story_data: Dict with story info (key, summary, description, etc.)
        repos: List of repository names in workspace
        additional_context: Optional additional context
        max_tasks: Maximum number of tasks to generate
        
    Returns:
        Formatted prompt string
    """
    story_key = story_data.get('key', 'UNKNOWN')
    summary = story_data.get('summary', 'No summary')
    description = story_data.get('description', 'No description')
    acceptance_criteria = story_data.get('acceptance_criteria', [])
    
    repos_str = ', '.join(repos) if repos else 'No repositories'
    
    ac_section = ""
    if acceptance_criteria:
        ac_items = '\n'.join(f"- {ac}" for ac in acceptance_criteria)
        ac_section = f"""
**Acceptance Criteria:**
{ac_items}
"""
    
    context_section = ""
    if additional_context:
        context_section = f"""
**Additional Context:**
{additional_context}
"""
    
    schema_json = get_schema_for_prompt("task_breakdown")
    
    return f"""You have full filesystem access to these repositories: {repos_str}

You are analyzing the codebase to create implementation-grade tasks for a story.

**Story Information:**
- Key: {story_key}
- Summary: {summary}

**Story Description:**
{description}
{ac_section}{context_section}
**Your Task:**

1. **Search the codebase** using grep, find, or file exploration tools
2. **Identify the actual files** that need to be modified
3. **Understand the project structure** (backend, frontend, tests, etc.)
4. **Create specific, actionable tasks** referencing real code

Create an implementation task breakdown that:
- References actual files/modules you find in the codebase
- Separates tasks by actual project structure (backend/frontend/infra/etc.)
- Includes test tasks based on existing test patterns in the repo
- Includes dependencies between tasks where appropriate
- Does NOT hallucinate components - only reference what actually exists
- Creates no more than {max_tasks} tasks

**Guidelines for Tasks:**
- Each task should be completable in 1-3 days
- Tasks should have clear deliverables
- Include file paths where changes are needed
- Note any dependencies between tasks

**IMPORTANT - OUTPUT INSTRUCTIONS:**

After completing your analysis, you MUST write your result to `/workspace/result.json`

The JSON must follow this exact schema:
```json
{schema_json}
```

Use the `write_file` tool to save the result. This is REQUIRED.

Do NOT just output the JSON - you must actually write it to the file.
"""


def coverage_check_prompt(
    story_data: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    repos: List[str],
    additional_context: Optional[str] = None
) -> str:
    """
    Generate a code-aware prompt for coverage checking.
    
    Args:
        story_data: Dict with story info
        tasks: List of existing tasks with summary and description
        repos: List of repository names in workspace
        additional_context: Optional additional context
        
    Returns:
        Formatted prompt string
    """
    story_key = story_data.get('key', 'UNKNOWN')
    summary = story_data.get('summary', 'No summary')
    description = story_data.get('description', 'No description')
    
    repos_str = ', '.join(repos) if repos else 'No repositories'
    
    # Format tasks
    tasks_section = ""
    if tasks:
        task_items = []
        for i, task in enumerate(tasks, 1):
            task_key = task.get('key', f'TASK-{i}')
            task_summary = task.get('summary', 'No summary')
            task_desc = task.get('description', 'No description')
            task_items.append(f"""
**Task {i}: {task_key}**
- Summary: {task_summary}
- Description: {task_desc[:500]}{'...' if len(task_desc) > 500 else ''}
""")
        tasks_section = '\n'.join(task_items)
    else:
        tasks_section = "No existing tasks"
    
    context_section = ""
    if additional_context:
        context_section = f"""
**Additional Context:**
{additional_context}
"""
    
    schema_json = get_schema_for_prompt("coverage_check")
    
    return f"""You have full filesystem access to these repositories: {repos_str}

You are analyzing whether the existing tasks adequately cover all requirements from the story.

**Story Information:**
- Key: {story_key}
- Summary: {summary}

**Story Description:**
{description}
{context_section}
**Existing Tasks:**
{tasks_section}

**Your Task:**

1. **Analyze the story** to extract all requirements
2. **Search the codebase** to understand what code changes are actually needed
3. **Map requirements to tasks** and identify gaps
4. **Identify files** that need changes but aren't covered by tasks
5. **Generate actionable suggestions** for improving coverage

Verify task coverage by examining the actual codebase:
- Map each story requirement to existing tasks AND actual code locations
- Identify gaps where code changes are needed but no task exists
- Identify tasks that reference non-existent code (hallucinations)
- Suggest missing tasks with specific file references
- Flag risky assumptions about the codebase

**For each gap identified, provide:**
- `suggestions_for_updates`: If an existing task needs modification, include:
  - `task_key`: The JIRA key of the task to update
  - `current_description`: Current task description
  - `suggested_description`: Your improved description referencing actual code
  - `suggested_test_cases`: Test cases based on code patterns you found
  - `ready_to_submit`: A dict with fields ready for the update API

- `suggestions_for_new_tasks`: If a new task is needed, include:
  - `summary`: Concise task title
  - `description`: Detailed description referencing actual files/code
  - `test_cases`: Suggested test cases
  - `gap_addressed`: Which requirement gap this task addresses
  - `ready_to_submit`: A dict with fields ready for the create API

**IMPORTANT - OUTPUT INSTRUCTIONS:**

After completing your analysis, you MUST write your result to `/workspace/result.json`

The JSON must follow this exact schema:
```json
{schema_json}
```

Use the `write_file` tool to save the result. This is REQUIRED.

Do NOT just output the JSON - you must actually write it to the file.
"""


def get_prompt_for_job_type(
    job_type: str,
    data: Dict[str, Any],
    repos: List[str],
    additional_context: Optional[str] = None
) -> str:
    """
    Get the appropriate prompt for a job type.
    
    Args:
        job_type: One of 'ticket_description', 'task_breakdown', 'coverage_check'
        data: Job-specific data (ticket_data, story_data, etc.)
        repos: List of repository names
        additional_context: Optional additional context
        
    Returns:
        Formatted prompt string
        
    Raises:
        ValueError: If job_type is unknown
    """
    if job_type == "ticket_description":
        return ticket_description_prompt(
            ticket_data=data.get('ticket_data', data),
            repos=repos,
            additional_context=additional_context
        )
    elif job_type == "task_breakdown":
        return task_breakdown_prompt(
            story_data=data.get('story_data', data),
            repos=repos,
            additional_context=additional_context,
            max_tasks=data.get('max_tasks', 10)
        )
    elif job_type == "coverage_check":
        return coverage_check_prompt(
            story_data=data.get('story_data', data),
            tasks=data.get('tasks', []),
            repos=repos,
            additional_context=additional_context
        )
    else:
        raise ValueError(
            f"Unknown job type: {job_type}. "
            f"Valid types: ticket_description, task_breakdown, coverage_check"
        )
