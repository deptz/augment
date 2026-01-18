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
from .utility import UtilityPrompts


def ticket_description_prompt(
    ticket_data: Dict[str, Any],
    repos: List[str],
    additional_context: Optional[str] = None,
    pull_requests: Optional[List[Dict[str, Any]]] = None,
    commits: Optional[List[Dict[str, Any]]] = None,
    prd_url: Optional[str] = None,
    rfc_url: Optional[str] = None
) -> str:
    """
    Generate a code-aware prompt for ticket description generation.
    
    Args:
        ticket_data: Dict with ticket info (key, summary, description, etc.)
        repos: List of repository names in workspace
        additional_context: Optional additional context
        pull_requests: Optional list of pull requests related to the ticket
        commits: Optional list of commits related to the ticket
        prd_url: Optional PRD document URL (OpenCode should fetch via MCP)
        rfc_url: Optional RFC document URL (OpenCode should fetch via MCP)
        
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
    
    # PRD/RFC section with MCP instructions
    prd_rfc_section = ""
    if prd_url or rfc_url:
        prd_rfc_section = "\n**PRD/RFC DOCUMENTATION:**\n\n"
        prd_rfc_section += "This ticket/epic has associated PRD/RFC documentation:\n"
        if prd_url:
            prd_rfc_section += f"- PRD URL: {prd_url}\n"
        if rfc_url:
            prd_rfc_section += f"- RFC URL: {rfc_url}\n"
        prd_rfc_section += """
**IMPORTANT**: Use the Atlassian MCP server (configured in /app/opencode.json) to fetch the full PRD/RFC content directly from Confluence:

1. Check if Atlassian MCP is available in your opencode.json configuration
2. Use the MCP server to read the Confluence pages referenced by the URLs above
3. Extract requirements, acceptance criteria, and technical specifications from the PRD/RFC
4. Use this information to inform your description generation

If MCP is not available or the documents cannot be fetched, proceed with the information provided in the ticket description.

For MCP usage instructions, refer to /app/opencode_agents.md.
"""
    
    # Format PR/commit information if available
    pr_commits_section = ""
    has_prs_or_commits = (pull_requests and len(pull_requests) > 0) or (commits and len(commits) > 0)
    
    if has_prs_or_commits:
        pr_commits_section = "\n**Related Code Changes:**\n"
        
        if pull_requests and len(pull_requests) > 0:
            pr_commits_section += "\n**Pull Requests:**\n"
            for i, pr in enumerate(pull_requests, 1):
                pr_title = pr.get('title', 'No title')
                pr_desc = str(pr.get('description') or '')
                pr_state = pr.get('state', 'unknown')
                pr_commits_section += f"{i}. **{pr_title}** ({pr_state})\n"
                if pr_desc:
                    pr_commits_section += f"   Description: {pr_desc[:200]}{'...' if len(pr_desc) > 200 else ''}\n"
                if pr.get('diff'):
                    pr_commits_section += f"   Includes code changes (diff available)\n"
        
        if commits and len(commits) > 0:
            pr_commits_section += "\n**Commits:**\n"
            for i, commit in enumerate(commits[:10], 1):  # Limit to first 10 commits
                commit_message = str(commit.get('message') or 'No message')
                commit_hash_str = str(commit.get('hash') or '')
                commit_hash = commit_hash_str[:8] if commit_hash_str else 'unknown'
                pr_commits_section += f"{i}. [{commit_hash}] {commit_message[:100]}{'...' if len(commit_message) > 100 else ''}\n"
                if commit.get('diff'):
                    pr_commits_section += f"   Includes code changes (diff available)\n"
    
    schema_json = get_schema_for_prompt("ticket_description")
    
    # Conditional section instructions based on whether PRs/commits are available
    conditional_section = ""
    if has_prs_or_commits:
        conditional_section = """
**CODE CHANGES SECTION REQUIREMENTS:**

Since this ticket has associated pull requests or commits, you MUST add a **Code Changes** section at the end of the description that includes:

1. **Changed Files**: List the actual file paths that were modified (from PR/commit diffs)
   - Use exact paths relative to repository root
   - Only reference files that actually exist in the codebase
   - Do NOT invent or hallucinate file paths

2. **Commit Summary**: Provide a summary of commit messages related to this ticket
   - Extract key changes from commit messages
   - Group related changes together

3. **PR Details**: If pull requests exist, include:
   - PR titles and descriptions
   - Summary of changes from PR diffs

**Example Code Changes Format:**
```
**Code Changes:**
- Changed files: `src/api/users.py`, `src/models/user.py`, `tests/test_users.py`
- Commits: 
  - "Add user authentication endpoint"
  - "Update user model with new fields"
- Pull Request: "Implement user management feature" - Added REST endpoints for user CRUD operations
```

**IMPORTANT**: Only include this section if you can identify actual commits or PRs related to this ticket. If no code changes are found, omit this section entirely.
"""
    else:
        conditional_section = """
**IMPLEMENTATION PLAN SECTION REQUIREMENTS:**

Since this ticket does not have associated pull requests or commits, you MUST add an **Implementation Plan** section at the end of the description that provides code-aware implementation details. This section must:

1. **Files to Modify**: List the actual file paths you found in the codebase that need changes
   - Use exact paths relative to repository root (e.g., `src/api/users.py`, `tests/test_users.py`)
   - Only reference files that actually exist in the codebase
   - Do NOT invent or hallucinate file paths

2. **Implementation Steps**: Provide step-by-step implementation guidance based on existing code patterns
   - Reference how similar features are implemented in the codebase
   - Follow existing architectural patterns you observe
   - Include specific code locations or modules to modify

3. **Dependencies**: Note any dependencies on other tasks or components
   - Reference other tasks by their summary/title if applicable
   - Note integration points with existing services or modules

4. **Code Structure Considerations**: Mention any important architectural or structural considerations
   - Database changes needed
   - API contract changes
   - Integration with existing services
   - Testing approach based on existing test patterns

**Example Implementation Plan Format:**
```
**Implementation Plan:**
- Files to modify: `src/api/users.py`, `src/models/user.py`, `tests/test_users.py`
- Implementation steps:
  1. Add new endpoint in `src/api/users.py` following the existing REST pattern (see `src/api/auth.py` for reference)
  2. Update user model in `src/models/user.py` to include new field, following existing model structure
  3. Add unit tests in `tests/test_users.py` following existing test patterns (see `tests/test_auth.py` for reference)
- Dependencies: Requires database migration from task "[BE] Create user profile migration"
- Integration points: Connects with authentication service in `src/services/auth_service.py`
- Code structure considerations: Follow existing error handling pattern in `src/api/base.py`
```
"""
    
    return f"""You have full filesystem access to these repositories: {repos_str}

You are analyzing the codebase to generate a comprehensive ticket description.

**Ticket Information:**
- Key: {ticket_key}
- Summary: {summary}
- Parent/Epic: {parent_summary}

**Current Description:**
{existing_description}
{context_section}{prd_rfc_section}{pr_commits_section}
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
{conditional_section}
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
    max_tasks: int = 10,
    max_task_cycle_days: Optional[float] = None,
    generate_test_cases: bool = False,
    prd_url: Optional[str] = None,
    rfc_url: Optional[str] = None
) -> str:
    """
    Generate a code-aware prompt for task breakdown.
    
    Args:
        story_data: Dict with story info (key, summary, description, etc.)
        repos: List of repository names in workspace
        additional_context: Optional additional context
        max_tasks: Maximum number of tasks to generate
        max_task_cycle_days: Maximum cycle time in days for each task
        generate_test_cases: Whether to generate test cases for tasks
        prd_url: Optional PRD document URL (OpenCode should fetch via MCP)
        rfc_url: Optional RFC document URL (OpenCode should fetch via MCP)
        
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
    
    # PRD/RFC section with MCP instructions
    prd_rfc_section = ""
    if prd_url or rfc_url:
        prd_rfc_section = "\n**PRD/RFC DOCUMENTATION:**\n\n"
        prd_rfc_section += "This story/epic has associated PRD/RFC documentation:\n"
        if prd_url:
            prd_rfc_section += f"- PRD URL: {prd_url}\n"
        if rfc_url:
            prd_rfc_section += f"- RFC URL: {rfc_url}\n"
        prd_rfc_section += """
**IMPORTANT**: Use the Atlassian MCP server (configured in /app/opencode.json) to fetch the full PRD/RFC content directly from Confluence:

1. Check if Atlassian MCP is available in your opencode.json configuration
2. Use the MCP server to read the Confluence pages referenced by the URLs above
3. Extract requirements, acceptance criteria, and technical specifications from the PRD/RFC
4. Use this information to inform your task breakdown analysis

If MCP is not available or the documents cannot be fetched, proceed with the information provided in the story description.

For MCP usage instructions, refer to /app/opencode_agents.md.
"""
    
    # Cycle time constraint section
    cycle_time_section = ""
    if max_task_cycle_days:
        cycle_time_section = f"""
**CYCLE TIME CONSTRAINT:**
Each task must be completable within {max_task_cycle_days} days maximum. If a task would exceed this limit, break it down into smaller subtasks.
"""
    
    # Test case generation section
    test_cases_section = ""
    if generate_test_cases:
        test_cases_section = """
**TEST CASE GENERATION:**
You MUST generate test cases for each task. Include test cases in the `test_cases` field of each task object. Test cases should:
- Cover the main functionality described in the task
- Include edge cases and error scenarios
- Reference actual test files/patterns found in the codebase
- Follow existing test patterns in the repository
"""
    
    schema_json = get_schema_for_prompt("task_breakdown")
    
    # Get Purpose/Scopes/Outcome guidance template
    pso_guidance = UtilityPrompts.get_task_breakdown_pso_guidance_template()
    
    return f"""You have full filesystem access to these repositories: {repos_str}

You are analyzing the codebase to create implementation-grade tasks for a story.

**Story Information:**
- Key: {story_key}
- Summary: {summary}

**Story Description:**
{description}
{ac_section}{context_section}{prd_rfc_section}{cycle_time_section}{test_cases_section}
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

{pso_guidance}

**IMPLEMENTATION PLAN REQUIREMENTS:**

After the Expected Outcomes section, add an **Implementation Plan** section that provides code-aware implementation details. This section must:

1. **Files to Modify**: List the actual file paths you found in the codebase that need changes
   - Use exact paths relative to repository root (e.g., `src/api/users.py`, `tests/test_users.py`)
   - Only reference files that actually exist in the codebase
   - Do NOT invent or hallucinate file paths

2. **Implementation Steps**: Provide step-by-step implementation guidance based on existing code patterns
   - Reference how similar features are implemented in the codebase
   - Follow existing architectural patterns you observe
   - Include specific code locations or modules to modify

3. **Dependencies**: Note any dependencies on other tasks or components
   - Reference other tasks by their summary/title if applicable
   - Note integration points with existing services or modules

4. **Code Structure Considerations**: Mention any important architectural or structural considerations
   - Database changes needed
   - API contract changes
   - Integration with existing services
   - Testing approach based on existing test patterns

**Example Implementation Plan Format:**
```
**Implementation Plan:**
- Files to modify: `src/api/users.py`, `src/models/user.py`, `tests/test_users.py`
- Implementation steps:
  1. Add new endpoint in `src/api/users.py` following the existing REST pattern (see `src/api/auth.py` for reference)
  2. Update user model in `src/models/user.py` to include new field, following existing model structure
  3. Add unit tests in `tests/test_users.py` following existing test patterns (see `tests/test_auth.py` for reference)
- Dependencies: Requires database migration from task "[BE] Create user profile migration"
- Integration points: Connects with authentication service in `src/services/auth_service.py`
- Code structure considerations: Follow existing error handling pattern in `src/api/base.py`
```

**IMPORTANT - OUTPUT INSTRUCTIONS:**

For each task, the `description` field in the JSON must contain markdown-formatted text with these sections in order:
1. **Purpose** (1-2 sentences)
2. **Scopes** (3-5 bullet points with deliverables)
3. **Expected Outcomes** (2-3 concrete results)
4. **Implementation Plan** (code-aware implementation details as described above)

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
    additional_context: Optional[str] = None,
    include_test_cases: bool = True,
    prd_url: Optional[str] = None,
    rfc_url: Optional[str] = None
) -> str:
    """
    Generate a code-aware prompt for coverage checking.
    
    Args:
        story_data: Dict with story info
        tasks: List of existing tasks with summary and description
        repos: List of repository names in workspace
        additional_context: Optional additional context
        include_test_cases: Whether to analyze test case coverage
        prd_url: Optional PRD document URL (OpenCode should fetch via MCP)
        rfc_url: Optional RFC document URL (OpenCode should fetch via MCP)
        
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
            task_summary = str(task.get('summary') or 'No summary')
            task_desc = str(task.get('description') or 'No description')
            task_item = f"""
**Task {i}: {task_key}**
- Summary: {task_summary}
- Description: {task_desc[:500]}{'...' if len(task_desc) > 500 else ''}
"""
            # Include test cases if available and requested
            if include_test_cases and task.get('test_cases'):
                test_cases = str(task.get('test_cases') or '')
                task_item += f"- Test Cases: {test_cases[:300]}{'...' if len(test_cases) > 300 else ''}\n"
            task_items.append(task_item)
        tasks_section = '\n'.join(task_items)
    else:
        tasks_section = "No existing tasks"
    
    context_section = ""
    if additional_context:
        context_section = f"""
**Additional Context:**
{additional_context}
"""
    
    # PRD/RFC section with MCP instructions
    prd_rfc_section = ""
    if prd_url or rfc_url:
        prd_rfc_section = "\n**PRD/RFC DOCUMENTATION:**\n\n"
        prd_rfc_section += "This story/epic has associated PRD/RFC documentation:\n"
        if prd_url:
            prd_rfc_section += f"- PRD URL: {prd_url}\n"
        if rfc_url:
            prd_rfc_section += f"- RFC URL: {rfc_url}\n"
        prd_rfc_section += """
**IMPORTANT**: Use the Atlassian MCP server (configured in /app/opencode.json) to fetch the full PRD/RFC content directly from Confluence:

1. Check if Atlassian MCP is available in your opencode.json configuration
2. Use the MCP server to read the Confluence pages referenced by the URLs above
3. Extract requirements, acceptance criteria, and technical specifications from the PRD/RFC
4. Use this information to inform your coverage analysis

If MCP is not available or the documents cannot be fetched, proceed with the information provided in the story description.

For MCP usage instructions, refer to /app/opencode_agents.md.
"""
    
    # Test case analysis section
    test_cases_section = ""
    if include_test_cases:
        test_cases_section = """
**TEST CASE COVERAGE ANALYSIS:**
You MUST analyze test case coverage for each requirement:
- Check if test cases exist for each requirement
- Identify requirements that lack test coverage
- Suggest test cases for uncovered requirements
- Include test case gaps in your analysis
"""
    
    schema_json = get_schema_for_prompt("coverage_check")
    
    return f"""You have full filesystem access to these repositories: {repos_str}

You are analyzing whether the existing tasks adequately cover all requirements from the story.

**Story Information:**
- Key: {story_key}
- Summary: {summary}

**Story Description:**
{description}
{context_section}{prd_rfc_section}{test_cases_section}
**Existing Tasks:**
{tasks_section}

**Your Task:**

1. **Analyze the story** to extract all requirements
2. **Search the codebase** to understand what code changes are actually needed
3. **Verify actual implementation** (see Implementation Verification section below)
4. **Map requirements to tasks** and identify gaps
5. **Identify files** that need changes but aren't covered by tasks
6. **Generate actionable suggestions** for improving coverage

**IMPLEMENTATION VERIFICATION:**

Before analyzing coverage gaps, you MUST verify the actual implementation status:

**For each existing task:**
- Check if the code/files described in the task actually exist in the codebase
  - If task describes files/modules that don't exist → flag as "implementation missing"
  - If task describes functionality that isn't implemented → flag as "implementation gap"
  - If task references code that exists but doesn't match description → flag as "implementation mismatch"
- Search the codebase for each file/module mentioned in task descriptions
- Verify that the functionality described in tasks is actually present in the code

**For each story requirement:**
- Check if it's actually implemented in code
  - Search codebase for implementation of each requirement
  - Identify requirements that are described but not implemented
  - Identify requirements that are implemented but not covered by tasks
- Map story requirements to actual code locations
- Verify that implemented code matches the story requirements

**Report implementation status in gaps:**
- Tasks with missing implementation (code described but doesn't exist)
- Story requirements not implemented in code
- Implementation gaps (what should exist but doesn't)
- Include `implementation_status` field in gap objects when applicable (e.g., "missing", "partial", "mismatch")

Verify task coverage by examining the actual codebase:
- Map each story requirement to existing tasks AND actual code locations
- Identify gaps where code changes are needed but no task exists
- Identify tasks that reference non-existent code (hallucinations)
- Suggest missing tasks with specific file references
- Flag risky assumptions about the codebase

**IMPLEMENTATION PLAN REQUIREMENTS FOR TASK SUGGESTIONS:**

For both `suggestions_for_updates` and `suggestions_for_new_tasks`, the `suggested_description` (or `description` for new tasks) must include an **Implementation Plan** section at the end, similar to task breakdown format.

The Implementation Plan section must:

1. **Files to Modify**: List the actual file paths you found in the codebase that need changes
   - Use exact paths relative to repository root (e.g., `src/api/users.py`, `tests/test_users.py`)
   - Only reference files that actually exist in the codebase
   - Do NOT invent or hallucinate file paths

2. **Implementation Steps**: Provide step-by-step implementation guidance based on existing code patterns
   - Reference how similar features are implemented in the codebase
   - Follow existing architectural patterns you observe
   - Include specific code locations or modules to modify

3. **Dependencies**: Note any dependencies on other tasks or components
   - Reference other tasks by their summary/title if applicable
   - Note integration points with existing services or modules

4. **Code Structure Considerations**: Mention any important architectural or structural considerations
   - Database changes needed
   - API contract changes
   - Integration with existing services
   - Testing approach based on existing test patterns

**Example Implementation Plan Format:**
```
**Implementation Plan:**
- Files to modify: `src/api/users.py`, `src/models/user.py`, `tests/test_users.py`
- Implementation steps:
  1. Add new endpoint in `src/api/users.py` following the existing REST pattern (see `src/api/auth.py` for reference)
  2. Update user model in `src/models/user.py` to include new field, following existing model structure
  3. Add unit tests in `tests/test_users.py` following existing test patterns (see `tests/test_auth.py` for reference)
- Dependencies: Requires database migration from task "[BE] Create user profile migration"
- Integration points: Connects with authentication service in `src/services/auth_service.py`
- Code structure considerations: Follow existing error handling pattern in `src/api/base.py`
```

**IMPORTANT**: For `suggestions_for_updates`, the `suggested_description` should include the existing task description PLUS the Implementation Plan section. The Implementation Plan should be appended after the existing description content.

**For each gap identified, provide:**
- `suggestions_for_updates`: If an existing task needs modification, include:
  - `task_key`: The JIRA key of the task to update
  - `current_description`: Current task description
  - `suggested_description`: Your improved description referencing actual code, with Implementation Plan section appended
  - `suggested_test_cases`: Test cases based on code patterns you found
  - `ready_to_submit`: A dict with fields ready for the update API

- `suggestions_for_new_tasks`: If a new task is needed, include:
  - `summary`: Concise task title
  - `description`: Detailed description referencing actual files/code, with Implementation Plan section included
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
    additional_context: Optional[str] = None,
    **kwargs
) -> str:
    """
    Get the appropriate prompt for a job type.
    
    Args:
        job_type: One of 'ticket_description', 'task_breakdown', 'coverage_check'
        data: Job-specific data (ticket_data, story_data, etc.)
        repos: List of repository names
        additional_context: Optional additional context
        **kwargs: Additional optional parameters (prd_url, rfc_url, max_task_cycle_days, generate_test_cases, include_test_cases, pull_requests, commits)
        
    Returns:
        Formatted prompt string
        
    Raises:
        ValueError: If job_type is unknown
    """
    if job_type == "ticket_description":
        return ticket_description_prompt(
            ticket_data=data.get('ticket_data', data),
            repos=repos,
            additional_context=additional_context,
            pull_requests=kwargs.get('pull_requests'),
            commits=kwargs.get('commits'),
            prd_url=kwargs.get('prd_url'),
            rfc_url=kwargs.get('rfc_url')
        )
    elif job_type == "task_breakdown":
        return task_breakdown_prompt(
            story_data=data.get('story_data', data),
            repos=repos,
            additional_context=additional_context,
            max_tasks=data.get('max_tasks', 10),
            max_task_cycle_days=kwargs.get('max_task_cycle_days'),
            generate_test_cases=kwargs.get('generate_test_cases', False),
            prd_url=kwargs.get('prd_url'),
            rfc_url=kwargs.get('rfc_url')
        )
    elif job_type == "coverage_check":
        return coverage_check_prompt(
            story_data=data.get('story_data', data),
            tasks=data.get('tasks', []),
            repos=repos,
            additional_context=additional_context,
            include_test_cases=kwargs.get('include_test_cases', True),
            prd_url=kwargs.get('prd_url'),
            rfc_url=kwargs.get('rfc_url')
        )
    else:
        raise ValueError(
            f"Unknown job type: {job_type}. "
            f"Valid types: ticket_description, task_breakdown, coverage_check"
        )
