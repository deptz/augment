"""
Package Service
Generates git diff and PR metadata for draft PR creation
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

import git
from git import Repo

from .draft_pr_models import PlanSpec, PlanVersion

logger = logging.getLogger(__name__)


class PackageService:
    """
    Packages changes for PR creation.
    
    Generates git diff and PR metadata (title, description, labels, etc.)
    """
    
    def __init__(self, workspace_path: Path):
        """
        Initialize package service.
        
        Args:
            workspace_path: Path to workspace with git repos
        """
        self.workspace_path = workspace_path
    
    def package(
        self,
        plan_version: PlanVersion,
        verification_results: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Package changes for PR creation.
        
        Args:
            plan_version: Plan version that was applied
            verification_results: Results from verification stage
            
        Returns:
            Dict with:
                - git_diff: Full git diff
                - changed_files: List of changed files
                - pr_metadata: PR metadata (title, description, etc.)
        """
        plan_spec = plan_version.plan_spec
        
        # Find primary repo
        repos = list(self.workspace_path.iterdir())
        if not repos:
            raise ValueError("No repositories found in workspace")
        
        primary_repo_path = repos[0]
        if not (primary_repo_path / ".git").exists():
            raise ValueError(f"Not a git repository: {primary_repo_path}")
        
        repo = Repo(primary_repo_path)
        
        # Generate git diff
        git_diff = self._generate_git_diff(repo)
        
        # Get changed files
        changed_files = self._get_changed_files(repo)
        
        # Generate PR metadata
        pr_metadata = self._generate_pr_metadata(
            plan_version,
            verification_results,
            changed_files
        )
        
        return {
            "git_diff": git_diff,
            "changed_files": changed_files,
            "pr_metadata": pr_metadata
        }
    
    def _generate_git_diff(self, repo: Repo) -> str:
        """
        Generate full git diff.
        
        Args:
            repo: Git repository
            
        Returns:
            Git diff string
        """
        try:
            # Get diff from HEAD
            diff = repo.git.diff('HEAD')
            return diff
        except Exception as e:
            logger.error(f"Failed to generate git diff: {e}")
            return ""
    
    def _get_changed_files(self, repo: Repo) -> List[str]:
        """Get list of changed files"""
        changed = []
        diff = repo.head.commit.diff(None, create_patch=False)
        
        for item in diff:
            if item.a_path:
                changed.append(item.a_path)
            if item.b_path and item.b_path != item.a_path:
                changed.append(item.b_path)
        
        return sorted(set(changed))
    
    def _generate_pr_metadata(
        self,
        plan_version: PlanVersion,
        verification_results: Optional[Dict[str, Any]],
        changed_files: List[str]
    ) -> Dict[str, Any]:
        """
        Generate PR metadata.
        
        Args:
            plan_version: Plan version
            verification_results: Verification results
            changed_files: List of changed files
            
        Returns:
            PR metadata dict
        """
        plan_spec = plan_version.plan_spec
        
        # Generate title
        title = f"Implement: {plan_spec.summary}"
        
        # Generate description
        description_parts = [
            f"## Summary\n\n{plan_spec.summary}\n",
            "## Changes\n\n"
        ]
        
        # Add scope
        if plan_spec.scope.get('files'):
            description_parts.append("### Files Modified\n\n")
            for file_change in plan_spec.scope.get('files', []):
                description_parts.append(f"- `{file_change.get('path')}` ({file_change.get('change', 'modify')})\n")
            description_parts.append("\n")
        
        # Add test results if available
        if verification_results:
            description_parts.append("## Verification Results\n\n")
            description_parts.append(f"{verification_results.get('summary', 'N/A')}\n\n")
            
            if verification_results.get('test_results'):
                tr = verification_results['test_results']
                if tr['exit_code'] == 0:
                    description_parts.append("✅ Tests passed\n\n")
                else:
                    description_parts.append(f"❌ Tests failed (exit code {tr['exit_code']})\n\n")
        
        # Add implementation details
        if plan_spec.happy_paths:
            description_parts.append("## Happy Paths\n\n")
            for path in plan_spec.happy_paths:
                description_parts.append(f"- {path}\n")
            description_parts.append("\n")
        
        if plan_spec.edge_cases:
            description_parts.append("## Edge Cases Handled\n\n")
            for case in plan_spec.edge_cases:
                description_parts.append(f"- {case}\n")
            description_parts.append("\n")
        
        description = "".join(description_parts)
        
        return {
            "title": title,
            "description": description,
            "labels": ["draft", "automated"],
            "changed_files": changed_files,
            "plan_version": plan_version.version,
            "plan_hash": plan_version.plan_hash[:8]
        }
