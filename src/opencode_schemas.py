"""
OpenCode JSON Schemas
JSON schemas for validating OpenCode result.json outputs
"""
import json
from typing import Any, Dict
from jsonschema import validate, ValidationError


# Schema for ticket description generation result
TICKET_DESCRIPTION_SCHEMA = {
    "type": "object",
    "required": ["description"],
    "properties": {
        "description": {
            "type": "string",
            "description": "Generated ticket description in markdown format"
        },
        "impacted_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of file paths that may be impacted"
        },
        "components": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of components/modules identified"
        },
        "acceptance_criteria": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Generated acceptance criteria"
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "Confidence level in the analysis"
        }
    },
    "additionalProperties": True
}


# Schema for task breakdown result
TASK_BREAKDOWN_SCHEMA = {
    "type": "object",
    "required": ["tasks"],
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["summary", "description"],
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Task title/summary"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed task description"
                    },
                    "files_to_modify": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files that need modification"
                    },
                    "estimated_effort": {
                        "type": "string",
                        "enum": ["small", "medium", "large"],
                        "description": "Effort estimate"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dependencies on other tasks (by summary)"
                    },
                    "team": {
                        "type": "string",
                        "description": "Team responsible (backend, frontend, etc.)"
                    },
                    "test_cases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Test cases for this task (optional, only if generate_test_cases is true)"
                    }
                },
                "additionalProperties": True
            },
            "description": "List of generated tasks"
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Warnings or concerns identified during analysis"
        }
    },
    "additionalProperties": True
}


# Schema for coverage check result
COVERAGE_CHECK_SCHEMA = {
    "type": "object",
    "required": ["coverage_percentage"],
    "properties": {
        "coverage_percentage": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "description": "Overall coverage percentage"
        },
        "covered_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement"],
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "The requirement being covered"
                    },
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tasks that cover this requirement"
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files related to this requirement"
                    }
                },
                "additionalProperties": True
            },
            "description": "Requirements that are covered by tasks"
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement"],
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "The uncovered requirement"
                    },
                    "missing_tasks": {
                        "type": "string",
                        "description": "Description of what tasks are missing"
                    },
                    "affected_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files that would need changes"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "important", "minor"],
                        "description": "Severity of the gap"
                    },
                    "implementation_status": {
                        "type": "string",
                        "enum": ["missing", "partial", "mismatch"],
                        "description": "Implementation status: missing (code doesn't exist), partial (incomplete), mismatch (doesn't match description)"
                    }
                },
                "additionalProperties": True
            },
            "description": "Coverage gaps identified"
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Risky assumptions or concerns identified"
        },
        "overall_assessment": {
            "type": "string",
            "description": "Overall assessment summary"
        },
        "suggestions_for_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["task_key", "suggested_description"],
                "properties": {
                    "task_key": {
                        "type": "string",
                        "description": "JIRA key of task to update"
                    },
                    "current_description": {
                        "type": "string",
                        "description": "Current task description"
                    },
                    "suggested_description": {
                        "type": "string",
                        "description": "Suggested updated description"
                    },
                    "suggested_test_cases": {
                        "type": "string",
                        "description": "Suggested test cases"
                    },
                    "ready_to_submit": {
                        "type": "object",
                        "description": "Ready-to-submit JSON for API"
                    }
                },
                "additionalProperties": True
            },
            "description": "Suggestions for updating existing tasks"
        },
        "suggestions_for_new_tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["summary", "description"],
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Suggested task summary"
                    },
                    "description": {
                        "type": "string",
                        "description": "Suggested task description"
                    },
                    "test_cases": {
                        "type": "string",
                        "description": "Suggested test cases"
                    },
                    "gap_addressed": {
                        "type": "string",
                        "description": "Which coverage gap this addresses"
                    },
                    "ready_to_submit": {
                        "type": "object",
                        "description": "Ready-to-submit JSON for API"
                    }
                },
                "additionalProperties": True
            },
            "description": "Suggestions for new tasks to create"
        }
    },
    "additionalProperties": True
}


# Map job types to their schemas
JOB_TYPE_SCHEMAS = {
    "ticket_description": TICKET_DESCRIPTION_SCHEMA,
    "task_breakdown": TASK_BREAKDOWN_SCHEMA,
    "coverage_check": COVERAGE_CHECK_SCHEMA,
}


def validate_opencode_result(result: Dict[str, Any], job_type: str) -> None:
    """
    Validate an OpenCode result against its expected schema.
    
    Args:
        result: The parsed JSON result from OpenCode
        job_type: The type of job (ticket_description, task_breakdown, coverage_check)
        
    Raises:
        ValueError: If job_type is unknown
        ValidationError: If result doesn't match schema
    """
    if job_type not in JOB_TYPE_SCHEMAS:
        raise ValueError(f"Unknown job type: {job_type}. Valid types: {list(JOB_TYPE_SCHEMAS.keys())}")
    
    schema = JOB_TYPE_SCHEMAS[job_type]
    validate(instance=result, schema=schema)


def get_schema_for_prompt(job_type: str) -> str:
    """
    Get the JSON schema as a formatted string for inclusion in prompts.
    
    Args:
        job_type: The type of job
        
    Returns:
        JSON schema as a formatted string
    """
    if job_type not in JOB_TYPE_SCHEMAS:
        raise ValueError(f"Unknown job type: {job_type}")
    
    return json.dumps(JOB_TYPE_SCHEMAS[job_type], indent=2)


def validate_result_content(result: Dict[str, Any], job_type: str) -> bool:
    """
    Validate that the result has meaningful content, not just valid structure.
    
    Args:
        result: The parsed JSON result
        job_type: The type of job
        
    Returns:
        True if content is meaningful, False if empty/garbage
        
    Note:
        This is a semantic check beyond schema validation.
    """
    if job_type == "ticket_description":
        description = result.get("description", "")
        # Check for non-empty, non-trivial description
        if not description or len(description.strip()) < 50:
            return False
        return True
    
    elif job_type == "task_breakdown":
        tasks = result.get("tasks", [])
        # Check for at least one task with meaningful content
        if not tasks:
            return False
        for task in tasks:
            if not task.get("summary") or not task.get("description"):
                return False
            if len(task["description"].strip()) < 20:
                return False
        return True
    
    elif job_type == "coverage_check":
        # Check for valid coverage percentage
        coverage = result.get("coverage_percentage")
        if coverage is None or not isinstance(coverage, (int, float)):
            return False
        return True
    
    return True
