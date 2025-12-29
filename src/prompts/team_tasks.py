"""
Team Task Generation Prompts
Prompts for generating team-separated tasks and unified task+test generation.
"""


class TeamTasksPrompts:
    """Prompts for team-based task generation"""
    
    @staticmethod
    def get_team_separation_prompt_template() -> str:
        """Get the template for team-separated task generation"""
        return """Break down this user story into separate tasks. Only include tasks for teams (Backend, Frontend, Mobile, QA) that are actually needed based on the requirements.

**STORY:** {story_summary}
**DESCRIPTION:** {story_description}
**STORY TYPE:** {story_type}
**MAX CYCLE TIME:** {max_cycle_days} days per task

**ACCEPTANCE CRITERIA:**
{acceptance_criteria}

{document_context}

{additional_context}

**ANALYSIS REQUIRED:**
- Analyze the story description and acceptance criteria
- Identify which teams (Backend/Frontend/Mobile/QA) are actually needed
- Only generate tasks for teams that are relevant to implementing this story
- If a team is not mentioned or needed, do NOT create tasks for that team

**BACKEND TASKS** should include:
- API endpoints and business logic
- Database design and data processing
- Service integrations and external APIs
- Security and authentication implementation
- The Ticket Summary must start with [BE]

**FRONTEND TASKS** should include:
- User interface components and pages
- User experience and interactions
- Client-side logic and state management
- UI/UX implementation
- Responsive design and accessibility
- The Ticket Summary must start with [FE]

**QA TASKS** should include:
- Test plan creation and test case design
- Manual testing and exploratory testing
- Automated test implementation
- Integration testing coordination
- Performance and security testing
- The Ticket Summary must start with [QA]

**MOBILE TASKS** should include:
- Mobile app UI/UX implementation
- Native mobile components and screens
- Mobile-specific integrations (push notifications, device APIs)
- Mobile platform considerations (iOS/Android)
- Mobile performance and optimization
- The Ticket Summary must start with [MOBILE]

**REQUIRED OUTPUT FORMAT:**
Return ONLY a valid JSON array with this exact structure:

```json
[
  {{
    "team": "Backend",
    "title": "[BE] Clear, actionable task name",
    "purpose": "Why this task is needed",
    "scope": "What exactly needs to be done",
    "expected_outcome": "What deliverable is produced",
    "depends_on_tasks": ["List of task titles this task depends on"],
    "blocked_by_teams": ["List of team names that block this task"]
  }},
  {{
    "team": "Frontend", 
    "title": "[FE] Build user login interface",
    "purpose": "Allow users to authenticate",
    "scope": "Create login form with validation",
    "expected_outcome": "Working login UI component",
    "depends_on_tasks": ["Implement user authentication API"],
    "blocked_by_teams": ["Backend"]
  }},
  {{
    "team": "QA",
    "title": "[QA] Test authentication flow", 
    "purpose": "Validate login functionality works end-to-end",
    "scope": "Manual and automated testing of auth flow",
    "expected_outcome": "Comprehensive test coverage",
    "depends_on_tasks": ["Build user login interface", "Implement user authentication API"],
    "blocked_by_teams": ["Frontend", "Backend"]
  }},
  {{
    "team": "Mobile",
    "title": "[MOBILE] Build mobile login screen",
    "purpose": "Allow mobile users to authenticate",
    "scope": "Create native mobile login UI with platform-specific design",
    "expected_outcome": "Working mobile login screen",
    "depends_on_tasks": ["Implement user authentication API"],
    "blocked_by_teams": ["Backend"]
  }}
]
```

**DEPENDENCY GUIDELINES:**
- **depends_on_tasks**: List the exact titles of tasks that must be completed before this task can start
- **blocked_by_teams**: List team names (Backend/Frontend/Mobile/QA) that must complete their work first
- Use exact task titles for dependencies - AI should determine logical dependencies
- Typical flow: Backend APIs → Frontend UI / Mobile App → QA Testing
- Backend tasks usually have fewer dependencies
- Frontend tasks often depend on Backend APIs
- Mobile tasks often depend on Backend APIs and may depend on Frontend for design patterns
- QA tasks often depend on both Backend and Frontend/Mobile completion
- Consider data flow: databases → APIs → UI/Mobile → testing

**GUIDELINES:**
- Return ONLY valid JSON, no other text
- Each task should be completable in {max_cycle_days} days or less
- Team values must be exactly: "Backend", "Frontend", "Mobile", or "QA"
- Ticket Title/Summary must start with exactly: "[BE]", "[FE]", "[MOBILE]", or "[QA]"
- Only generate tasks for teams that are relevant to this story. For example:
  - If the story mentions 'mobile app' or 'iOS/Android', include Mobile tasks
  - If the story mentions 'API' or 'backend', include Backend tasks  
  - If the story mentions 'web interface' or 'UI', include Frontend tasks
  - QA tasks should be included if testing is needed for the feature
  - Do NOT create tasks for teams that are not relevant to the requirements
- Tasks should have clear team ownership (no shared tasks)
- Backend tasks focus on data and business logic
- Frontend tasks focus on user interface and experience  
- Mobile tasks focus on native mobile app implementation
- QA tasks focus on testing and quality validation
- Consider dependencies between teams (Backend → Frontend/Mobile → QA)
"""
    
    @staticmethod
    def get_unified_task_test_prompt_template() -> str:
        """Get the template for unified task+test generation"""
        return """Generate complete team-separated implementation plan with embedded test cases:

**STORY:** {story_summary}
**DESCRIPTION:** {story_description}
**STORY TYPE:** {story_type}
**MAX CYCLE TIME:** {max_cycle_days} days per task
**TEST COVERAGE:** {test_coverage_level} ({test_count} tests per task)

**ACCEPTANCE CRITERIA:**
{acceptance_criteria}

{document_context}

{additional_context}

**ANALYSIS REQUIRED:**
- Analyze the story description and acceptance criteria
- Identify which teams (Backend/Frontend/Mobile/QA) are actually needed
- Only generate tasks for teams that are relevant to implementing this story
- If a team is not mentioned or needed, do NOT create tasks for that team

Generate tasks (2-4) only for teams that are needed based on the requirements. Analyze the story to determine which teams are relevant. Include EMBEDDED test cases:

```json
[
  {{
    "summary": "[BE] Backend implementation for [specific feature]",
    "team": "backend",
    "purpose": "Clear implementation purpose and deliverables",
    "scopes": [
      {{
        "description": "Specific scope description",
        "deliverable": "What gets delivered"
      }}
    ],
    "test_cases": [
      {{
        "title": "Clear test case title",
        "type": "unit|integration|e2e|acceptance",
        "description": "Test description with business context",
        "priority": "P0|P1|P2",
        "test_steps": "Given [setup condition]\\nWhen [specific action]\\nThen [expected result]",
        "expected_result": "Specific expected outcome"
      }}
    ],
    "depends_on_tasks": ["Task summary it depends on"],
    "cycle_time_estimate": {{
      "development_days": 2.0,
      "testing_days": 0.5,
      "total_days": 2.5
    }}
  }}
]
```

**TEAM REQUIREMENTS:**

**BACKEND TASKS** ([BE] prefix):
- API endpoints and business logic
- Database design and data processing
- Service integrations and security
- Tests: unit tests for APIs, integration tests for services

**FRONTEND TASKS** ([FE] prefix):
- UI components and user interactions
- Client-side logic and state management
- Responsive design and accessibility
- Tests: component tests, user journey tests, accessibility tests

**QA TASKS** ([QA] prefix):
- Test plan creation and manual testing
- Automated test implementation
- Integration and performance testing
- Tests: end-to-end scenarios, edge cases, regression tests

**MOBILE TASKS** ([MOBILE] prefix):
- Mobile app components and user interactions
- Native mobile logic and state management
- Platform-specific implementations (iOS/Android)
- Mobile testing: device tests, platform tests, app store validation
- Tests: mobile component tests, device-specific tests, platform compatibility tests

**TEST GENERATION REQUIREMENTS:**

## Coverage Requirements ({test_coverage_level} level)
* **{test_count} test cases per task** covering:
  1. **Happy Path** - Core functionality with valid inputs
  2. **Error Handling** - Invalid inputs, permission errors, system failures  
  3. **Edge Cases** - Boundary conditions, extreme values, unusual scenarios
  4. **Integration Points** - API contracts, data flow, external dependencies

## Test Quality Standards
* Use **Given/When/Then** format for test steps
* Specify **exact inputs and expected outputs**
* Include **setup and teardown** requirements
* Define **acceptance criteria** clearly
* Link tests to **business requirements**

## Test Steps Format
* Use CLEAN Given/When/Then format WITHOUT numbering
* Separate clauses with \\n (newline characters)
* NO "1.", "2.", "3." prefixes
* Example: "Given user is logged in\\nWhen they click submit\\nThen form is submitted"

**IMPORTANT:** Return ONLY the JSON array, no explanations or markdown."""

