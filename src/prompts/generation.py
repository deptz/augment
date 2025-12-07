"""
Generation Prompts
Prompts for generating ticket descriptions and other content.
"""


class GenerationPrompts:
    """Prompts for content generation"""
    
    @staticmethod
    def get_description_template() -> str:
        """Get the template for generating ticket descriptions"""
        return """You are an archival assistant tasked with generating a structured Jira ticket description by analyzing the specific implementation details of this ticket and combining them with broader context from design documents and linked stories.

**PRIORITIZATION ORDER:**
1. Focus primarily on what THIS SPECIFIC TICKET accomplished (title, existing description, file changes, PR details)
2. Use story context to understand the broader business requirements and user journey
3. Use design document context (PRD/RFC) to understand the overall goals and expected outcomes

**Primary Context Documents:**
- PRD Title: {{prd_title}}
- PRD Goals/Objectives: {{prd_goals}}
- PRD Summary: {{prd_summary}}

**RFC Technical Context:**
{{rfc_technical_summary}}

**RFC Implementation Context:**
{{rfc_implementation_summary}}

**RFC Security & Performance Context:**
{{rfc_security_performance_summary}}

**THIS TICKET'S SPECIFIC IMPLEMENTATION:**
- Ticket: {{ticket_key}} - {{ticket_title}}
- Current Description: {{ticket_description}}
- Code Changes Summary: {{code_changes_summary}}
- Pull Request Details: {{pull_request_details}}
- Commit Messages: {{commit_messages}}
- Changed Files: {{changed_files}}

**Broader Story Context:**
{{story_information}}

**Parent Context:**
- Parent Story: {{parent_summary}}

**Additional Context:**
{{additional_context}}

Based on the provided information, generate a description that captures what THIS SPECIFIC TICKET accomplished. 

For PRD-based tickets: Focus on user requirements, business value, and feature implementation.
For RFC-based tickets: Focus on technical architecture, implementation details, security considerations, and system design.

The "Purpose" should explain why THIS TICKET was needed within the broader context. The "Scopes" should describe exactly what THIS TICKET implemented (derived primarily from the ticket title, PR details, commits, and file changes). The "Expected Outcome" should describe the specific result of THIS TICKET's work.

Use the Story and document context to understand WHY this work was needed and how it fits into the overall design, but focus the description on what THIS SPECIFIC TICKET delivered.

STRICT REQUIREMENTS:
- Generate ONLY the ticket description in the specified format
- Do NOT include suggestions, recommendations, or follow-up actions
- Do NOT offer to provide additional information or assistance
- Do NOT ask questions or make proposals
- Focus solely on documenting what was accomplished

Output in this exact format:

**Purpose:**
<A 1-2 sentence summary of *why* THIS SPECIFIC TICKET was necessary, based on the ticket title, story context, and design document goals.>

**Scopes:**
- <A bulleted list of the concrete work that was done IN THIS TICKET, derived primarily from PR details, commit messages, changed files, and ticket title.>
- <Another scope item specific to this ticket.>

**Expected Outcome:**
- <A bulleted list describing the final state or result of THIS TICKET's work, based on what was actually implemented.>"""

