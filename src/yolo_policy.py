"""
YOLO Policy Evaluator
Evaluates plans against YOLO policy for auto-approval
"""
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
import fnmatch

from .draft_pr_models import PlanSpec

logger = logging.getLogger(__name__)


class YOLOPolicyError(Exception):
    """Base exception for YOLO policy errors"""
    pass


class YOLOPolicyEvaluator:
    """
    Evaluates plans against YOLO policy to determine if auto-approval is safe.
    
    YOLO mode auto-approves plans that comply with policy constraints.
    Non-compliant plans fall back to normal approval workflow.
    """
    
    def __init__(self, policy: Dict[str, Any]):
        """
        Initialize policy evaluator.
        
        Args:
            policy: Policy configuration dict with:
                - max_files: Maximum number of files that can be changed
                - max_loc_delta: Maximum lines of code change
                - allow_paths: List of allowed path patterns
                - deny_paths: List of denied path patterns
                - require_tests: Whether tests are required
        """
        self.max_files = policy.get('max_files', 5)
        self.max_loc_delta = policy.get('max_loc_delta', 200)
        self.allow_paths = policy.get('allow_paths', [])
        self.deny_paths = policy.get('deny_paths', [])
        self.require_tests = policy.get('require_tests', False)
    
    def evaluate(self, plan_spec: PlanSpec) -> Dict[str, Any]:
        """
        Evaluate plan against YOLO policy.
        
        Args:
            plan_spec: Plan specification to evaluate
            
        Returns:
            Dict with:
                - compliant: bool - Whether plan complies with policy
                - violations: List[str] - List of policy violations
                - details: Dict - Detailed evaluation results
        """
        violations = []
        details = {}
        
        # Check file count
        files = plan_spec.scope.get('files', [])
        file_count = len(files)
        details['file_count'] = file_count
        if file_count > self.max_files:
            violations.append(f"Too many files: {file_count} > {self.max_files}")
        
        # Check LOC delta (estimate based on file count and change types)
        # This is a rough estimate - actual LOC would be calculated after APPLY
        loc_estimate = self._estimate_loc_delta(files)
        details['loc_estimate'] = loc_estimate
        if loc_estimate > self.max_loc_delta:
            violations.append(f"Estimated LOC delta too large: {loc_estimate} > {self.max_loc_delta}")
        
        # Check allowed paths
        if self.allow_paths:
            allowed_files = self._check_path_patterns(files, self.allow_paths, allow=True)
            if not allowed_files:
                violations.append("No files match allowed path patterns")
            details['allowed_files'] = allowed_files
        
        # Check denied paths
        if self.deny_paths:
            denied_files = self._check_path_patterns(files, self.deny_paths, allow=False)
            if denied_files:
                violations.append(f"Files match denied paths: {denied_files}")
            details['denied_files'] = denied_files
        
        # Check tests requirement
        if self.require_tests:
            tests = plan_spec.tests
            if not tests or len(tests) == 0:
                violations.append("Tests are required but none specified")
            details['has_tests'] = len(tests) > 0
        
        # Check for empty critical sections (safety check)
        if not plan_spec.edge_cases:
            violations.append("No edge cases specified (safety risk)")
        
        if not plan_spec.failure_modes:
            violations.append("No failure modes identified (safety risk)")
        
        compliant = len(violations) == 0
        
        return {
            "compliant": compliant,
            "violations": violations,
            "details": details
        }
    
    def _estimate_loc_delta(self, files: List[Dict[str, Any]]) -> int:
        """
        Estimate lines of code delta based on file changes.
        
        This is a rough estimate. Actual LOC is calculated after APPLY.
        
        Args:
            files: List of file change dicts
            
        Returns:
            Estimated LOC delta
        """
        # Rough estimates per change type
        estimates = {
            "create": 50,  # New files typically ~50 LOC
            "modify": 30,  # Modifications typically ~30 LOC
            "delete": -20  # Deletions reduce LOC
        }
        
        total = 0
        for file_change in files:
            change_type = file_change.get('change', 'modify').lower()
            estimate = estimates.get(change_type, 30)
            total += estimate
        
        return total
    
    def _check_path_patterns(
        self,
        files: List[Dict[str, Any]],
        patterns: List[str],
        allow: bool = True
    ) -> List[str]:
        """
        Check if files match path patterns.
        
        Args:
            files: List of file change dicts
            patterns: List of glob patterns
            allow: If True, return files that match (allowed). If False, return files that match (denied).
            
        Returns:
            List of file paths that match patterns
        """
        matched = []
        
        for file_change in files:
            file_path = file_change.get('path', '')
            
            for pattern in patterns:
                if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(file_path, f"**/{pattern}"):
                    matched.append(file_path)
                    break
        
        return matched
