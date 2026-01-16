"""
Draft PR Orchestrator JSON Schemas
JSON schemas for validating plan specifications
"""
import json
import hashlib
from typing import Dict, Any, Optional
from jsonschema import validate, ValidationError

from .draft_pr_models import PlanSpec


# JSON Schema for PlanSpec validation
PLAN_SPEC_SCHEMA = {
    "type": "object",
    "required": ["summary", "scope"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "High-level summary of the plan",
            "minLength": 10
        },
        "scope": {
            "type": "object",
            "required": ["files"],
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string"},
                            "change": {"type": "string", "description": "Type of change (create, modify, delete)"}
                        }
                    },
                    "minItems": 1
                }
            }
        },
        "happy_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Happy path scenarios"
        },
        "edge_cases": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Edge cases to handle"
        },
        "failure_modes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["trigger", "impact"],
                "properties": {
                    "trigger": {"type": "string"},
                    "impact": {"type": "string"},
                    "mitigation": {"type": "string"}
                }
            },
            "description": "Failure modes with trigger, impact, and mitigation"
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assumptions made in the plan"
        },
        "unknowns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Unknowns or uncertainties"
        },
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "target"],
                "properties": {
                    "type": {"type": "string", "enum": ["unit", "integration", "e2e"]},
                    "target": {"type": "string"}
                }
            },
            "description": "Tests to run"
        },
        "rollback": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Rollback procedures"
        },
        "cross_repo_impacts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["repo"],
                "properties": {
                    "repo": {"type": "string"},
                    "reason": {"type": "string"}
                }
            },
            "description": "Cross-repo impacts"
        }
    },
    "additionalProperties": False
}


def validate_plan_spec(plan_spec: Dict[str, Any]) -> None:
    """
    Validate a plan specification against the JSON schema.
    
    Args:
        plan_spec: Plan specification dictionary
        
    Raises:
        ValidationError: If plan doesn't match schema
        ValueError: If required sections are empty (per PRD requirement)
    """
    # Schema validation
    validate(instance=plan_spec, schema=PLAN_SPEC_SCHEMA)
    
    # PRD requirement: Empty sections are a failure signal
    # Check that critical sections are not empty
    required_sections = {
        "happy_paths": "At least one happy path must be specified",
        "edge_cases": "At least one edge case must be considered",
        "failure_modes": "At least one failure mode must be identified",
        "assumptions": "Assumptions must be explicitly stated",
        "tests": "At least one test must be specified"
    }
    
    for section, error_msg in required_sections.items():
        if not plan_spec.get(section) or len(plan_spec.get(section, [])) == 0:
            raise ValueError(f"{error_msg} (empty {section} section)")


def calculate_plan_hash(plan_spec: Dict[str, Any]) -> str:
    """
    Calculate SHA256 hash of canonical plan JSON.
    
    Args:
        plan_spec: Plan specification dictionary
        
    Returns:
        Hexadecimal hash string
    """
    # Convert to canonical JSON (sorted keys, no whitespace)
    canonical_json = json.dumps(plan_spec, sort_keys=True, separators=(',', ':'))
    
    # Calculate SHA256 hash
    hash_obj = hashlib.sha256(canonical_json.encode('utf-8'))
    return hash_obj.hexdigest()


def get_schema_for_prompt() -> str:
    """
    Get the JSON schema as a formatted string for inclusion in prompts.
    
    Returns:
        JSON schema as a formatted string
    """
    return json.dumps(PLAN_SPEC_SCHEMA, indent=2)
