"""
Analysis Prompts
Prompts for analyzing stories, coverage, and requirements.
"""


class AnalysisPrompts:
    """Prompts for analysis operations"""
    
    @staticmethod
    def get_story_coverage_analysis_template() -> str:
        """Get the template for story coverage analysis"""
        return """Analyze whether the following task tickets adequately cover ALL requirements from the story.

**Story: {story_key}**
**Summary:** {story_summary}

**Story Description:**
{story_description}

**Story Test Cases:**
{story_test_cases}

{additional_context}
**Existing Tasks ({tasks_count} tasks):**
{tasks_summary}

**Task Details with Test Cases:**
{tasks_details}

**Analysis Required:**
1. Identify which story requirements are covered by existing tasks
2. Identify which story requirements are NOT covered (gaps)
3. Rate severity of each gap (critical/important/minor)
4. Provide ready-to-copy suggestions for:
   - Updates to existing tasks (if task partially covers requirement but needs enhancement)
   - New tasks to create (if requirement completely missing)
5. Calculate coverage percentage (0-100)

**IMPORTANT:** Return ONLY valid JSON in this exact format:
{{
  "coverage_percentage": <float 0-100>,
  "overall_assessment": "<brief summary of coverage>",
  "covered_requirements": ["<requirement 1>", "<requirement 2>"],
  "gaps": [
    {{
      "requirement": "<missing requirement description>",
      "severity": "critical|important|minor",
      "suggestion": "<what needs to be done>"
    }}
  ],
  "suggestions_for_updates": {{
    "<TASK-KEY>": {{
      "description": "**Purpose:**\\n<purpose>\\n\\n**Scopes:**\\n- <scope 1>\\n- <scope 2>\\n\\n**Expected Outcome:**\\n- <outcome>",
      "test_cases": "**Test Case 1:**\\n<test case details>"
    }}
  }},
  "suggestions_for_new_tasks": [
    {{
      "summary": "<task summary>",
      "description": "**Purpose:**\\n<purpose>\\n\\n**Scopes:**\\n- <scope>\\n\\n**Expected Outcome:**\\n- <outcome>",
      "test_cases": "**Test Case 1:**\\n<test case details>",
      "gap_addressed": "<which gap this addresses>"
    }}
  ]
}}

Return ONLY the JSON object, no additional text or explanation."""

