"""
Verifier
Service for running tests, lint, and build commands to verify changes
"""
import logging
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """Base exception for verification errors"""
    pass


class Verifier:
    """
    Verifies changes by running tests, linters, and build commands.
    
    Captures stdout/stderr for artifact storage.
    """
    
    def __init__(
        self,
        test_command: Optional[str] = None,
        lint_command: Optional[str] = None,
        build_command: Optional[str] = None,
        timeout_seconds: int = 600
    ):
        """
        Initialize verifier.
        
        Args:
            test_command: Command to run tests (e.g., "pytest")
            lint_command: Command to run linter (e.g., "ruff check")
            build_command: Command to run build (e.g., "npm run build")
            timeout_seconds: Timeout for each command
        """
        self.test_command = test_command
        self.lint_command = lint_command
        self.build_command = build_command
        self.timeout_seconds = timeout_seconds
    
    async def verify(
        self,
        workspace_path: Path,
        plan_spec: Any,
        repos: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Run verification (tests, lint, build).
        
        Args:
            workspace_path: Path to workspace
            plan_spec: Plan specification (for test targets)
            repos: List of repos (for repo-specific commands)
            
        Returns:
            Dict with:
                - passed: bool - Whether all verifications passed
                - test_results: Dict with stdout, stderr, exit_code
                - lint_results: Dict with stdout, stderr, exit_code
                - build_results: Dict with stdout, stderr, exit_code
                - summary: str - Human-readable summary
        """
        results = {
            "passed": True,
            "test_results": None,
            "lint_results": None,
            "build_results": None,
            "summary": ""
        }
        
        # Run tests
        if self.test_command:
            test_results = await self._run_command(
                workspace_path,
                self.test_command,
                "tests"
            )
            results["test_results"] = test_results
            if test_results["exit_code"] != 0:
                results["passed"] = False
        
        # Run linter
        if self.lint_command:
            lint_results = await self._run_command(
                workspace_path,
                self.lint_command,
                "lint"
            )
            results["lint_results"] = lint_results
            if lint_results["exit_code"] != 0:
                results["passed"] = False
        
        # Run build
        if self.build_command:
            build_results = await self._run_command(
                workspace_path,
                self.build_command,
                "build"
            )
            results["build_results"] = build_results
            if build_results["exit_code"] != 0:
                results["passed"] = False
        
        # Generate summary
        results["summary"] = self._generate_summary(results)
        
        return results
    
    async def _run_command(
        self,
        workspace_path: Path,
        command: str,
        command_type: str
    ) -> Dict[str, Any]:
        """
        Run a command and capture output.
        
        Args:
            workspace_path: Path to workspace
            command: Command to run
            command_type: Type of command (for logging)
            
        Returns:
            Dict with stdout, stderr, exit_code
        """
        logger.info(f"Running {command_type} command: {command}")
        
        try:
            # Split command into parts
            cmd_parts = command.split()
            
            if not cmd_parts:
                return {
                    "stdout": "",
                    "stderr": "Empty command provided",
                    "exit_code": -1
                }
            
            # Check if command exists (basic check - first part should be executable)
            import shutil
            if not shutil.which(cmd_parts[0]):
                logger.warning(f"Command '{cmd_parts[0]}' not found in PATH")
                return {
                    "stdout": "",
                    "stderr": f"Command '{cmd_parts[0]}' not found in PATH",
                    "exit_code": -1
                }
            
            # Run in subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                cwd=str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {self.timeout_seconds}s",
                    "exit_code": -1
                }
            
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            
            return {
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": process.returncode
            }
            
        except Exception as e:
            logger.error(f"Failed to run {command_type} command: {e}")
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1
            }
    
    def _generate_summary(self, results: Dict[str, Any]) -> str:
        """Generate human-readable summary of verification results"""
        parts = []
        
        if results.get("test_results"):
            tr = results["test_results"]
            if tr["exit_code"] == 0:
                parts.append("Tests: PASSED")
            else:
                parts.append(f"Tests: FAILED (exit code {tr['exit_code']})")
        
        if results.get("lint_results"):
            lr = results["lint_results"]
            if lr["exit_code"] == 0:
                parts.append("Lint: PASSED")
            else:
                parts.append(f"Lint: FAILED (exit code {lr['exit_code']})")
        
        if results.get("build_results"):
            br = results["build_results"]
            if br["exit_code"] == 0:
                parts.append("Build: PASSED")
            else:
                parts.append(f"Build: FAILED (exit code {br['exit_code']})")
        
        if not parts:
            return "No verification commands configured"
        
        return " | ".join(parts)
