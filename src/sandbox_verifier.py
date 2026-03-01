"""
Run verification (test, lint, build) inside an existing OpenSandbox that has the repo.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SandboxVerifier:
    """
    Runs verification commands inside an existing sandbox that
    already has the cloned and modified repo from the APPLY stage.
    """

    def __init__(
        self,
        test_command: Optional[str] = None,
        lint_command: Optional[str] = None,
        build_command: Optional[str] = None,
        setup_commands: Optional[List[str]] = None,
        language: str = "python",
    ):
        self.test_command = test_command
        self.lint_command = lint_command
        self.build_command = build_command
        self.setup_commands = setup_commands or self._default_setup(language)

    def _default_setup(self, language: str) -> List[str]:
        return {
            "python": [
                "pip install -r requirements.txt 2>/dev/null || true",
                "pip install pytest ruff 2>/dev/null || true",
            ],
            "node": ["npm install 2>/dev/null || true"],
            "java": ["mvn dependency:resolve 2>/dev/null || true"],
            "go": ["go mod download 2>/dev/null || true"],
        }.get(language, [
            "pip install -r requirements.txt 2>/dev/null || true",
            "pip install pytest ruff 2>/dev/null || true",
        ])

    async def verify(
        self,
        sandbox: Any,
        repo_path: str = "/workspace/repo",
        plan_spec: Any = None,
        repos: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Run verification in the existing sandbox.
        Setup commands run sequentially; then test, lint, and build run in parallel.

        Args:
            sandbox: OpenSandbox instance with repo already cloned.
            repo_path: Path to repo inside sandbox.
            plan_spec: Reserved for future plan-aware verification.
            repos: Reserved for future use.

        Returns:
            Dict with "passed" (bool), "test_results", "lint_results", "build_results"
            (each None or {stdout, stderr, exit_code}), and "summary" (str).
            Does not raise; failures are reflected in passed=False and exit_code.
        """
        if not any([self.test_command, self.lint_command, self.build_command]):
            return {
                "passed": True,
                "test_results": None,
                "lint_results": None,
                "build_results": None,
                "summary": "No verification commands configured",
            }
        for cmd in self.setup_commands:
            await sandbox.commands.run(f"cd {repo_path} && {cmd}")
        tasks = {}
        for key, command, label in [
            ("test_results", self.test_command, "test"),
            ("lint_results", self.lint_command, "lint"),
            ("build_results", self.build_command, "build"),
        ]:
            if command:
                tasks[key] = self._run_command(sandbox, repo_path, command, label)
        results = {"test_results": None, "lint_results": None, "build_results": None}
        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), gathered):
                if isinstance(result, Exception):
                    results[key] = {"stdout": "", "stderr": str(result), "exit_code": -1}
                else:
                    results[key] = result
        results["passed"] = all(
            r is None or r.get("exit_code") == 0
            for r in [results["test_results"], results["lint_results"], results["build_results"]]
        )
        results["summary"] = self._generate_summary(results)
        return results

    async def _run_command(
        self,
        sandbox: Any,
        repo_path: str,
        command: str,
        label: str,
    ) -> Dict[str, Any]:
        try:
            result = await sandbox.commands.run(f"cd {repo_path} && {command}")
            stdout = "".join(msg.text for msg in result.logs.stdout) if result.logs.stdout else ""
            stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
            return {"stdout": stdout, "stderr": stderr, "exit_code": result.exit_code}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    def _generate_summary(self, results: Dict[str, Any]) -> str:
        parts = []
        for key, label in [
            ("test_results", "Tests"),
            ("lint_results", "Lint"),
            ("build_results", "Build"),
        ]:
            r = results.get(key)
            if r is None:
                continue
            status = "PASSED" if r.get("exit_code") == 0 else f"FAILED (exit code {r.get('exit_code')})"
            parts.append(f"{label}: {status}")
        return " | ".join(parts) if parts else "No verification commands configured"
