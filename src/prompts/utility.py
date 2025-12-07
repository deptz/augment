"""
Utility Prompts
Utility prompts for summarization, guidance templates, and JSON instructions.
"""

from typing import Dict


class UtilityPrompts:
    """Utility prompts for various operations"""
    
    @staticmethod
    def get_summarization_prompt_template() -> str:
        """Get template for text summarization"""
        return """Please summarize the following JIRA story description, preserving the most important information for understanding the business requirements, acceptance criteria, and implementation context. 

Target length: approximately {target_length} characters.

Focus on:
- Business value and user requirements
- Acceptance criteria or success metrics  
- Key technical constraints or requirements
- Important context for related development work

Original description:
{description}

Summary:"""
    
    @staticmethod
    def get_effort_estimation_guidance_template() -> str:
        """Get template for effort estimation guidance"""
        return """
**ESTIMATION CATEGORIES:**
Provide estimates for:
1. **Development Days**: Core implementation time
2. **Testing Days**: Test creation and execution
3. **Review Days**: Code review and feedback cycles
4. **Deployment Days**: Release and deployment activities

**CONFIDENCE LEVELS:**
- 0.9+: Very confident (simple, well-understood work)
- 0.7-0.9: Confident (some uncertainty but manageable)
- 0.5-0.7: Moderate confidence (significant unknowns)
- <0.5: Low confidence (high risk, needs investigation)

**3-DAY RULE:**
If total exceeds 3 days, recommend splitting with:
- Split reasoning
- Suggested breakdown approach
- Dependencies between split tasks"""
    
    @staticmethod
    def get_legacy_build_prompt_template() -> str:
        """Get template for legacy prompt building (deprecated - use centralized templates)"""
        return """Please generate a comprehensive Jira ticket description based on the following information:

**Ticket Information:**
{ticket_info}

{prd_content_section}

{commits_section}

{pull_requests_section}

{code_changes_section}

**Please format the description with:**
1. A brief summary of what was implemented
2. Technical details and implementation approach
3. Key changes and files affected
4. Any relevant context or background

Use proper Jira formatting with headers, bullet points, and code blocks where appropriate.
"""
    
    @staticmethod
    def get_story_generation_gwt_guidance_template() -> str:
        """Get Given/When/Then guidance template for story generation"""
        return """
**ACCEPTANCE CRITERIA FORMAT:**
Use this structure for all acceptance criteria:
- **Scenario**: Brief scenario description
- **Given**: Initial state/preconditions
- **When**: User action/trigger
- **Then**: Expected outcome/result

Example:
- **Scenario**: User Login Authentication
- **Given**: User has valid credentials
- **When**: User submits login form
- **Then**: User is authenticated and redirected to dashboard
"""
    
    @staticmethod
    def get_task_breakdown_pso_guidance_template() -> str:
        """Get Purpose/Scopes/Outcome guidance template for task breakdown"""
        return """
**TASK FORMAT REQUIREMENTS:**
For each task, provide:

1. **Purpose**: Why this task is needed (1-2 sentences)
2. **Scopes**: Specific work items (3-5 bullet points with deliverables)
3. **Expected Outcomes**: What will be completed (2-3 concrete results)

**Scope Item Format:**
Each scope should include:
- Description: What needs to be done
- Complexity: low/medium/high
- Dependencies: What must be done first
- Deliverable: Concrete output/artifact

Example Task Structure:
```
**Purpose**: Implement user authentication to secure application access
**Scopes**:
- Create JWT token service (medium complexity, depends on user model, deliverable: token service)
- Add login API endpoint (low complexity, depends on token service, deliverable: working API)
- Implement session management (medium complexity, depends on login API, deliverable: session handling)
**Expected Outcomes**:
- Users can authenticate with username/password
- JWT tokens are generated and validated
- User sessions are properly managed
```
"""
    
    @staticmethod
    def get_json_response_instruction() -> str:
        """Get standard JSON response instruction"""
        return "IMPORTANT: Return ONLY valid JSON, no other text or markdown."
    
    @staticmethod
    def get_claude_json_response_instruction() -> str:
        """Get Claude-specific JSON response instruction (more forceful for prompt-based generation)"""
        return """CRITICAL JSON FORMAT REQUIREMENTS:
- You MUST return ONLY valid JSON format
- Return a JSON OBJECT (starts with {), NOT an array (starts with [)
- Do NOT include any markdown code blocks (no ```json or ```)
- Do NOT include any explanatory text before or after the JSON
- Do NOT include comments or notes
- Start the response directly with { (opening brace)
- End the response directly with } (closing brace)
- Ensure all strings are properly quoted and escaped
- Ensure all brackets and braces are properly matched
- The response must be parseable as valid JSON by json.loads()

Return ONLY the raw JSON object (not array), nothing else."""
    
    @staticmethod
    def get_comprehensive_task_prompt_context_template() -> str:
        """Get template for comprehensive task prompt context additions"""
        return """**ENHANCED DOCUMENT CONTEXT:**

{prd_context}

{rfc_context}

{testing_focus}"""
    
    @staticmethod
    def get_prd_context_section_template() -> str:
        """Get template for PRD context section"""
        return """**PRD Context - {prd_title}:

{prd_sections}

**Use PRD for:** Business logic validation, user scenario testing, constraint verification"""
    
    @staticmethod
    def get_rfc_context_section_template() -> str:
        """Get template for RFC context section"""
        return """**RFC Context - {rfc_title}:

{rfc_sections}

**Use RFC for:** API contract testing, technical edge cases, integration validation, performance requirements"""
    
    @staticmethod
    def get_testing_focus_template() -> str:
        """Get template for testing focus guidance"""
        return """**TESTING FOCUS:** {focus_message}"""
    
    @staticmethod
    def get_story_context_addition_template() -> str:
        """Get template for adding story context to prompts"""
        return """
{prd_section}

{rfc_section}"""
    
    @staticmethod
    def get_prd_usage_guidance() -> str:
        """Get PRD usage guidance text"""
        return "**Use PRD for:** Business logic validation, user scenario testing, constraint verification"
    
    @staticmethod
    def get_rfc_usage_guidance() -> str:
        """Get RFC usage guidance text"""
        return "**Use RFC for:** API contract testing, technical edge cases, integration validation, performance requirements"
    
    @staticmethod
    def get_testing_focus_messages() -> Dict[str, str]:
        """Get testing focus messages for different context scenarios"""
        return {
            "limited_context": "Limited context - emphasize technical validation, implementation quality, and comprehensive edge case coverage.",
            "story_only": "Story-aligned testing - ensure task implementation supports parent story requirements.",
            "document_only": "Document-driven testing - validate against business requirements (PRD) and technical constraints (RFC).",
            "full_context": "Comprehensive context-aware testing - align with story goals while validating business rules and technical implementation."
        }

