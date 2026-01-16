"""
Plan Comparator
Service for comparing plan versions and generating diffs
"""
import json
import logging
from typing import Dict, Any, List

from .draft_pr_models import PlanVersion, PlanComparison

logger = logging.getLogger(__name__)


class PlanComparator:
    """Compares plan versions and generates structured diffs"""
    
    def compare_plans(
        self,
        from_version: PlanVersion,
        to_version: PlanVersion
    ) -> PlanComparison:
        """
        Compare two plan versions and generate a diff.
        
        Args:
            from_version: Source plan version
            to_version: Target plan version
            
        Returns:
            PlanComparison object with changes and summary
        """
        from_dict = from_version.plan_spec.dict()
        to_dict = to_version.plan_spec.dict()
        
        changes = {
            "added": {},
            "removed": {},
            "modified": {}
        }
        changed_sections = []
        
        # Compare each section
        all_keys = set(from_dict.keys()) | set(to_dict.keys())
        
        for key in all_keys:
            from_value = from_dict.get(key)
            to_value = to_dict.get(key)
            
            if key not in from_dict:
                # Added in new version
                changes["added"][key] = to_value
                changed_sections.append(key)
            elif key not in to_dict:
                # Removed in new version
                changes["removed"][key] = from_value
                changed_sections.append(key)
            elif from_value != to_value:
                # Modified
                changes["modified"][key] = {
                    "from": from_value,
                    "to": to_value
                }
                changed_sections.append(key)
        
        # Generate summary
        summary = self._generate_summary(changes, from_version.version, to_version.version)
        
        return PlanComparison(
            from_version=from_version.version,
            to_version=to_version.version,
            changes=changes,
            summary=summary,
            changed_sections=sorted(set(changed_sections))
        )
    
    def _generate_summary(
        self,
        changes: Dict[str, Any],
        from_version: int,
        to_version: int
    ) -> str:
        """
        Generate human-readable summary of changes.
        
        Args:
            changes: Changes dictionary
            from_version: Source version number
            to_version: Target version number
            
        Returns:
            Summary string
        """
        parts = [f"Plan updated from v{from_version} to v{to_version}."]
        
        added = changes.get("added", {})
        removed = changes.get("removed", {})
        modified = changes.get("modified", {})
        
        if added:
            parts.append(f"Added sections: {', '.join(added.keys())}.")
        
        if removed:
            parts.append(f"Removed sections: {', '.join(removed.keys())}.")
        
        if modified:
            parts.append(f"Modified sections: {', '.join(modified.keys())}.")
        
        # Provide more detail for key sections
        if "scope" in modified:
            from_files = len(modified["scope"]["from"].get("files", []))
            to_files = len(modified["scope"]["to"].get("files", []))
            if from_files != to_files:
                parts.append(f"File count changed: {from_files} → {to_files} files.")
        
        if "tests" in modified:
            from_tests = len(modified["tests"]["from"])
            to_tests = len(modified["tests"]["to"])
            if from_tests != to_tests:
                parts.append(f"Test count changed: {from_tests} → {to_tests} tests.")
        
        if "edge_cases" in modified:
            from_cases = len(modified["edge_cases"]["from"])
            to_cases = len(modified["edge_cases"]["to"])
            if from_cases != to_cases:
                parts.append(f"Edge cases changed: {from_cases} → {to_cases} cases.")
        
        if not added and not removed and not modified:
            return f"Plan v{from_version} and v{to_version} are identical."
        
        return " ".join(parts)
    
    def get_detailed_diff(
        self,
        from_version: PlanVersion,
        to_version: PlanVersion
    ) -> Dict[str, Any]:
        """
        Get detailed diff with line-by-line changes for text sections.
        
        Args:
            from_version: Source plan version
            to_version: Target plan version
            
        Returns:
            Detailed diff dictionary
        """
        comparison = self.compare_plans(from_version, to_version)
        
        detailed = {
            "summary": comparison.summary,
            "changed_sections": comparison.changed_sections,
            "section_diffs": {}
        }
        
        # Generate detailed diffs for text-based sections
        text_sections = ["summary", "happy_paths", "edge_cases", "assumptions", "unknowns", "rollback"]
        
        for section in text_sections:
            if section in comparison.changes.get("modified", {}):
                from_value = comparison.changes["modified"][section]["from"]
                to_value = comparison.changes["modified"][section]["to"]
                
                if isinstance(from_value, list) and isinstance(to_value, list):
                    # List comparison
                    added = [item for item in to_value if item not in from_value]
                    removed = [item for item in from_value if item not in to_value]
                    
                    detailed["section_diffs"][section] = {
                        "added": added,
                        "removed": removed,
                        "unchanged": [item for item in from_value if item in to_value]
                    }
                else:
                    # Simple text comparison
                    detailed["section_diffs"][section] = {
                        "from": from_value,
                        "to": to_value
                    }
        
        return detailed
