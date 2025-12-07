"""
Test Generation Prompts
Prompts for generating test cases and test data.
"""


class TestGenerationPrompts:
    """Prompts for test generation"""
    
    @staticmethod
    def get_test_data_prompt_template() -> str:
        """Get template for test data generation prompt"""
        return """Generate realistic test data for the following test case:

**Test Case:** {test_case_title}
**Type:** {test_case_type}
**Description:** {test_case_description}

**Required Data Types:**
{required_data_types}

Generate varied, realistic test data that covers:
- Valid input scenarios
- Invalid input scenarios  
- Boundary values and edge cases
- Security testing payloads (if applicable)
- Performance testing data sets (if applicable)

Format as JSON with clear labeling for each data type.

{additional_context}"""
    
    @staticmethod
    def get_story_test_generation_prompt_template() -> str:
        """Get template for story test case generation"""
        return """Generate comprehensive test cases for the following user story:

**Story Summary:** {story_summary}
**Story Description:** {story_description}
**Coverage Level:** {coverage_level}
**Domain Context:** {domain_context}

**Acceptance Criteria:**
{acceptance_criteria}

Generate {test_count} test cases in the following JSON format:

```json
[
  {{
    "title": "Clear, descriptive test case title",
    "type": "acceptance|integration|unit|e2e|performance|security",
    "description": "Detailed test description",
    "priority": "P0|P1|P2",
    "test_steps": "Given the system is in initial state\\nWhen user performs action\\nThen expected result occurs",
    "expected_result": "Specific expected outcome"
  }}
]
```

**Test Case Requirements:**
1. Use proper Gherkin format (Given/When/Then) in test_steps
2. Cover all acceptance criteria scenarios
3. Include both positive and negative test cases
4. Add edge cases for {coverage_level} coverage
5. Consider {domain_context} domain-specific scenarios
6. Ensure each test case is independent and executable

{domain_specific_guidance}"""
    
    @staticmethod
    def get_task_test_generation_prompt_template() -> str:
        """Get template for task test case generation"""
        return """Generate comprehensive test cases for the following development task:

**Task Summary:** {task_summary}
**Task Purpose:** {task_purpose}
**Technical Context:** {technical_context}
**Coverage Level:** {coverage_level}

**Task Scopes:**
{task_scopes}

**Expected Outcomes:**
{expected_outcomes}

Generate {test_count} test cases in the following JSON format:

```json
[
  {{
    "title": "Clear, descriptive test case title",
    "type": "unit|integration|component|contract|performance",
    "description": "Technical test description",
    "priority": "P0|P1|P2",
    "test_steps": "Given the system/component is properly configured\\nWhen the technical operation is performed\\nThen the expected technical result occurs",
    "expected_result": "Specific technical outcome"
  }}
]
```

**Technical Test Requirements:**
1. Use proper Gherkin format (Given/When/Then) in test_steps
2. Focus on implementation-level testing
3. Include unit tests for individual components
4. Add integration tests for component interactions
5. Consider {technical_context} specific test patterns
6. Include error handling and edge case scenarios
7. Ensure tests are automatable and maintainable

{technical_specific_guidance}"""
    
    @staticmethod
    def get_enhanced_story_test_prompt_template() -> str:
        """Get enhanced template for story test case generation (detailed version)"""
        return """Generate comprehensive test cases for the following user story:

**Story Summary:** {story_summary}
**Story Description:** {story_description}
**Coverage Level:** standard

{acceptance_criteria_section}

**RESPONSE FORMAT:** Return ONLY a valid JSON array with this exact structure:

[
  {{
    "title": "Clear, descriptive test case title",
    "type": "acceptance|integration|e2e|performance|security",
    "description": "Detailed test description",
    "priority": "P0|P1|P2",
    "test_steps": "Given the system is in initial state\\nWhen user performs action\\nThen expected result occurs",
    "expected_result": "Specific expected outcome"
  }}
]

**REQUIREMENTS:**
## Coverage

* **3-5 test cases covering at least:**
  1. **Happy Path** - Primary user journey with valid inputs
  2. **Error Handling** - Invalid inputs, permission errors, system errors
  3. **Edge Cases** - Boundary conditions, interruptions, timeout scenarios
  4. **User Experience** - Accessibility, responsive design, user feedback

Each case must map to at least one **Acceptance Criterion** or user story requirement.

## Data Usage Policy (No Guessing)

* **Use only story-provided data** (user roles, workflows, UI elements, business rules).
* **Do NOT invent** specific URLs, IDs, or technical details not mentioned.
* If data is missing, insert the marker: **`NEEDS_DATA:<what>`**

## Executability Rules

* Steps must be runnable by any tester **without domain knowledge**.
* Use **Given/When/Then** format WITHOUT numbers - clean format only.
* Use actual newlines (\\n) to separate Given/When/Then clauses.
* Specify **where to verify**:
  * **UI Elements**: buttons, forms, messages, navigation states
  * **User Feedback**: success messages, error displays, loading states
  * **Business Logic**: data persistence, calculations, workflow states

## Validation Depth (what each case should verify)

* **User Input**: form validation, required fields, input constraints
* **System Response**: success feedback, error messages, state changes
* **User Experience**: navigation flow, accessibility, responsive behavior
* **Business Rules**: workflow validation, permission checks, data integrity

## Output Format (per Test Case)

* **Title**: `[USER_FLOW] brief behavior description`
* **Traceability**: link to acceptance criteria
* **Preconditions**: user state, system state, test data setup
* **Test Steps (Given/When/Then)**: exact user actions and verification points
* **Expected Result**: specific UI state, user feedback, business outcome

## Quality Gate (reject cases that violate)

* Any **guessed** technical details not in story
* Steps that lack **clear verification points**
* Expectations without **specific user feedback**
* "Should" language without **binary pass/fail criteria**

**TEST STEPS FORMAT:**
- Use CLEAN Given/When/Then format WITHOUT numbering
- Separate with \\n: "Given [condition]\\nWhen [action]\\nThen [result]"
- NO "1.", "2.", "3." prefixes or bullet points

**IMPORTANT:** Return ONLY the JSON array, no explanations or markdown."""
    
    @staticmethod
    def get_enhanced_task_test_prompt_template() -> str:
        """Get enhanced template for task test case generation (detailed version)"""
        return """Generate test cases for development task: {task_summary}

**DESCRIPTION:** {task_description}
**COVERAGE:** Standard technical validation

**RESPONSE FORMAT:** Return ONLY a valid JSON array with this exact structure:

[
  {{
    "title": "Test case title",
    "type": "unit|integration|e2e",
    "priority": "P0|P1|P2", 
    "description": "Detailed test description with preconditions and context",
    "test_steps": "Given [setup]\\nWhen [action]\\nThen [result]",
    "expected_result": "Clear expected outcome"
  }}
]

**REQUIREMENTS:**
## Coverage

* **3-4 test cases per task covering at least:**
  1. **Happy Path** - Core functionality with valid inputs
  2. **Error Handling** - Invalid inputs, permission errors, system failures
  3. **Edge Cases** - Boundary conditions, timeouts, resource limits
  4. **Integration** - Component interactions, data flow validation

## Data Usage Policy (No Guessing)

* **Use only task-provided data** (endpoints, data structures, business rules).
* **Do NOT invent** URLs, IDs, error codes, or technical specs not mentioned.
* If data is missing, insert the marker: **`NEEDS_DATA:<what>`**

## Executability Rules

* Steps must be runnable by any developer/tester **without domain knowledge**.
* Use **Given/When/Then** format WITHOUT numbers - clean format only.
* Use actual newlines (\\n) to separate Given/When/Then clauses.
* Specify **where to verify**:
  * **API Testing**: request/response validation, status codes, payload structure
  * **Unit Testing**: method calls, return values, exception handling
  * **Integration**: component interactions, data persistence, external service calls

## Validation Depth (what each case should verify)

* **Input Validation**: parameter validation, type checking, constraint enforcement
* **Processing Logic**: algorithm correctness, business rule implementation
* **Output Validation**: return values, side effects, state changes
* **Error Handling**: exception scenarios, graceful degradation, recovery

## Environment & Tools

* Target **development/staging environment**
* Specify testing approach (unit tests, API tests, integration tests)
* Include test data requirements or mark `NEEDS_DATA:test_data`

## Output Format (per Test Case)

* **Title**: `[COMPONENT] brief technical behavior`
* **Preconditions**: system setup, test data, mock configurations
* **Test Steps (Given/When/Then)**: exact technical actions and verification
* **Expected Result**: specific technical outcome, status codes, data states

## Quality Gate (reject cases that violate)

* Any **guessed** technical implementation details
* Steps that lack **specific verification points**
* Expectations without **measurable technical outcomes**
* "Should" language without **binary pass/fail criteria**

**TEST STEPS FORMAT:**
- Use CLEAN Given/When/Then format WITHOUT numbering
- Separate with \\n: "Given [setup]\\nWhen [action]\\nThen [result]"
- NO "1.", "2.", "3." prefixes or bullet points

**IMPORTANT:** Return ONLY the JSON array, no explanations or markdown."""
    
    @staticmethod
    def get_enhanced_task_prompt_template() -> str:
        """Get enhanced template for task test case generation (optimized version)"""
        return """Generate test cases for task: {task_summary}

**DESCRIPTION:** {task_description}
**SCOPES:** {task_scopes}
**OUTCOMES:** {expected_outcomes}

**RESPONSE FORMAT:** Return ONLY a valid JSON array with this exact structure:

[
  {{
    "title": "Test case title",
    "type": "unit|integration|e2e",
    "priority": "P0|P1|P2", 
    "description": "Detailed test description with preconditions and context",
    "test_steps": "Given [setup]\\nWhen [action]\\nThen [result]",
    "expected_result": "Clear expected outcome"
  }}
]

**REQUIREMENTS:**
## Coverage

* **2–4 test cases per ticket if possible**, covering at least:

  1. **Happy Path**
  2. **Error Handling** (auth/permission + server/client errors)
  3. **Edge Cases** (timeouts, retries, double-clicks, stale cache)
  4. **Input/Response Validation** (schema, required fields, bounds)

Each case must map to at least one **Acceptance Criterion** or explicit ticket rule.

## Data Usage Policy (No Guessing)

* **Use only ticket-provided data** (endpoints, headers, IDs, status/error codes, payload fields).
* **Do NOT invent** endpoints, IDs, or codes.
* If data is missing, insert the marker: **`NEEDS_DATA:<what>`** and add an **Open Questions** list.

  * Example: `NEEDS_DATA:endpoint_path`, `NEEDS_DATA:error_codes`

## Executability Rules

* Steps must be runnable by any tester **without domain knowledge**.
* Use **Given/When/Then** with exact actions and checks.
* Specify **where to verify**:

  * **Browser DevTools → Network**: method, URL, headers, body, status, response JSON.
  * **UI**: visible state (redirect URL, toast text, disabled state).
* Include **concrete pass/fail checks** (no vague verbs like "works" or "should handle").

## Validation Depth (what each case should verify)

* **Request**: HTTP method, URL, headers (e.g., `Authorization`, `Content-Type`), body keys/types.
* **Response**: status code, required fields, types, key semantics (e.g., `redirectUrl` is absolute/relative).
* **UI Effects**: navigation/redirect, loading & disabled states, error surfaces (toast/inline), retry/backoff if specified.
* **Resilience**: offline/timeout/5xx, 401/403, 422 validation errors, idempotency on repeated clicks, cache invalidation rules if specified.

## Environment & Tools

* Target **staging** (or specify `NEEDS_DATA:environment`).
* If mocks are allowed, state **how** (e.g., MSW). Otherwise mark `NEEDS_DATA:mocking_policy`.

## Output Format (per Test Case)

* **Title**: `[AREA] brief behavior`
* **Traceability**: link to Story/AC ID
* **Preconditions**: env, auth state, seed data (or `NEEDS_DATA:*`)
* **Test Data**: only from ticket; else `NEEDS_DATA:*`
* **Steps (Given/When/Then)**: exact clicks/requests; where to inspect
* **Expected Result**: explicit HTTP/JSON/UI; schema snippet if relevant
* **Notes/Open Questions**: unresolved `NEEDS_DATA:*`

## Quality Gate (reject cases that violate)

* Any **guessed** endpoint, payload, or error code.
* Steps that lack **location of verification** (e.g., Network tab).
* Expectations without **status code + key fields**.
* "Should" language without **binary pass/fail**.

**IMPORTANT:** Return ONLY the JSON array, no explanations or markdown."""

