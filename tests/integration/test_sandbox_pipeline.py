"""
Integration tests for SandboxPipelineRunner (APPLY → VERIFY → PACKAGE → DRAFT_PR in one sandbox).

These tests require a running OpenSandbox server and are skipped by default.
Run with: pytest tests/integration/test_sandbox_pipeline.py -v
Set OPENSANDBOX_ENABLED=true and ensure OpenSandbox is reachable to run.
"""
import os
import pytest

# Skip entire module unless OpenSandbox is enabled and we have a server to talk to
pytestmark = pytest.mark.skipif(
    os.environ.get("OPENSANDBOX_ENABLED", "").lower() not in ("true", "1"),
    reason="OpenSandbox integration tests require OPENSANDBOX_ENABLED=true",
)


@pytest.mark.integration
def test_sandbox_pipeline_full_flow_placeholder():
    """
    Placeholder for full pipeline integration test:
    - Create sandbox, clone repo, apply plan, verify, package, push branch, create PR.
    - Asserts: sandbox created and released, artifacts stored, PR URL returned.
    Implement when running against a real OpenSandbox instance.
    """
    pytest.skip("Full sandbox pipeline integration test not implemented (requires OpenSandbox server)")
