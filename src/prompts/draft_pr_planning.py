"""
Draft PR Planning Prompts
Prompts for generating structured plans for draft PR orchestrator
"""
import json
from typing import Optional, Dict, Any


class DraftPRPlanningPrompts:
    """Prompts for draft PR plan generation"""
    
    @staticmethod
    def get_plan_generation_prompt(
        story_key: str,
        story_summary: str,
        story_description: Optional[str],
        scope: Optional[Dict[str, Any]],
        repos: Optional[list] = None,
        additional_context: Optional[str] = None
    ) -> str:
        """
        Get prompt for initial plan generation.
        
        Args:
            story_key: JIRA story key
            story_summary: Story summary
            story_description: Story description
            scope: Optional scope constraints
            repos: List of repositories
            additional_context: Additional context
            
        Returns:
            Formatted prompt string
        """
        repos_info = ""
        if repos:
            repos_list = "\n".join([f"- {repo.get('url', repo) if isinstance(repo, dict) else repo}" for repo in repos])
            repos_info = f"\n**Repositories:**\n{repos_list}\n"
        
        scope_info = ""
        if scope:
            scope_info = f"\n**Scope Constraints:**\n{json.dumps(scope, indent=2)}\n"
        
        context_info = ""
        if additional_context:
            context_info = f"\n**Additional Context:**\n{additional_context}\n"
        
        return f"""You are a technical planning assistant tasked with creating a comprehensive, structured plan for implementing a JIRA story.

**STORY:**
- Key: {story_key}
- Summary: {story_summary}
- Description: {story_description or 'No description provided'}

{repos_info}{scope_info}{context_info}

**YOUR TASK:**
Generate a structured plan that will be used to automatically implement code changes. This plan must be:
1. **Complete**: All sections must be filled (empty sections = failure)
2. **Specific**: Concrete file paths, test targets, rollback steps
3. **Safe**: Identify risks, failure modes, and mitigation strategies
4. **Testable**: Specify tests that will validate the implementation

**REQUIRED PLAN STRUCTURE:**

You MUST return a valid JSON object with this exact structure:

```json
{{
  "summary": "High-level summary of what this plan accomplishes",
  "scope": {{
    "files": [
      {{
        "path": "src/api/users.py",
        "change": "modify"
      }},
      {{
        "path": "tests/test_users.py",
        "change": "create"
      }}
    ]
  }},
  "happy_paths": [
    "User successfully creates account with valid email",
    "User receives confirmation email"
  ],
  "edge_cases": [
    "User provides duplicate email",
    "Email service is unavailable",
    "Database connection fails"
  ],
  "failure_modes": [
    {{
      "trigger": "Database connection timeout",
      "impact": "User registration fails, no account created",
      "mitigation": "Retry with exponential backoff, show user-friendly error"
    }}
  ],
  "assumptions": [
    "Database is accessible and properly configured",
    "Email service API is available",
    "User input validation happens at API level"
  ],
  "unknowns": [
    "Current database schema for user table",
    "Existing email service integration patterns"
  ],
  "tests": [
    {{
      "type": "unit",
      "target": "UserService.create_user()"
    }},
    {{
      "type": "integration",
      "target": "POST /api/users endpoint"
    }},
    {{
      "type": "e2e",
      "target": "User registration flow"
    }}
  ],
  "rollback": [
    "Revert database migration if applied",
    "Remove new API endpoints",
    "Restore previous version of modified files"
  ],
  "cross_repo_impacts": [
    {{
      "repo": "frontend-app",
      "reason": "May need to update API client for new endpoints"
    }}
  ]
}}
```

**CRITICAL REQUIREMENTS:**

1. **Empty sections are NOT allowed** - Every section must have at least one entry
2. **Be specific** - Use actual file paths, function names, endpoint URLs
3. **Think adversarially** - What can go wrong? How do we detect and recover?
4. **Consider dependencies** - What other systems/repos are affected?
5. **Plan for rollback** - How do we undo if something goes wrong?

**OUTPUT:**
Return ONLY the JSON object, no additional text or markdown formatting.
"""

    @staticmethod
    def get_plan_revision_prompt(
        previous_plan: Dict[str, Any],
        feedback: str,
        specific_concerns: Optional[list] = None,
        feedback_type: Optional[str] = None
    ) -> str:
        """
        Get prompt for revising a plan based on feedback.
        
        Args:
            previous_plan: The previous plan version (as dict)
            feedback: User feedback text
            specific_concerns: List of specific concerns
            feedback_type: Type of feedback (general, scope, tests, safety, other)
            
        Returns:
            Formatted prompt string
        """
        concerns_text = ""
        if specific_concerns:
            concerns_list = "\n".join([f"- {concern}" for concern in specific_concerns])
            concerns_text = f"\n**Specific Concerns:**\n{concerns_list}\n"
        
        previous_plan_json = json.dumps(previous_plan, indent=2)
        
        return f"""You are a technical planning assistant tasked with revising a plan based on user feedback.

**PREVIOUS PLAN (v{previous_plan.get('version', 'N/A')}):**
```json
{previous_plan_json}
```

**USER FEEDBACK:**
{feedback}

{concerns_text}

**YOUR TASK:**
Revise the plan to address the user's feedback while maintaining the plan structure and completeness.

**REQUIREMENTS:**
1. **Address all feedback** - Every concern must be addressed
2. **Maintain structure** - Keep the same JSON structure
3. **Don't remove valid content** - Only modify what needs to change based on feedback
4. **Keep completeness** - All sections must still be filled (no empty sections)
5. **Version increment** - This will become the next version (v{previous_plan.get('version', 1) + 1})

**OUTPUT:**
Return ONLY the revised JSON object with the same structure as the previous plan, no additional text or markdown formatting.
"""
