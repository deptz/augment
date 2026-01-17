"""
Artifact Store
Persists all artifacts for draft PR orchestrator jobs (plans, diffs, logs, PR metadata)
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Base directory for artifact storage
ARTIFACT_BASE_DIR = Path("/tmp/augment/artifacts")


class ArtifactStoreError(Exception):
    """Exception raised for artifact store errors"""
    pass


class ArtifactStore:
    """
    Manages artifact persistence for draft PR orchestrator jobs.
    
    Artifacts are stored on filesystem with metadata tracked.
    Large artifacts (diffs, logs) stored as files.
    Small metadata stored in memory/Redis (handled by job system).
    """
    
    def __init__(self, base_dir: Optional[Path] = None, retention_days: int = 30):
        """
        Initialize artifact store.
        
        Args:
            base_dir: Base directory for artifacts (default: /tmp/augment/artifacts)
            retention_days: Number of days to retain artifacts (default: 30)
        """
        self.base_dir = base_dir or ARTIFACT_BASE_DIR
        self.retention_days = retention_days
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_job_dir(self, job_id: str) -> Path:
        """Get directory for a specific job's artifacts"""
        return self.base_dir / job_id
    
    def store_artifact(
        self,
        job_id: str,
        artifact_type: str,
        artifact_data: Any,
        metadata: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> str:
        """
        Store an artifact for a job with retry logic.
        
        Args:
            job_id: Job identifier
            artifact_type: Type of artifact (input_spec, plan_v1, plan_v2, git_diff, validation_logs, etc.)
            artifact_data: The artifact data (dict, string, bytes, etc.)
            metadata: Optional metadata about the artifact
            max_retries: Maximum number of retry attempts (default: 3)
            
        Returns:
            Path to stored artifact (relative to base_dir)
            
        Raises:
            ArtifactStoreError: If storage fails after all retries
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return self._store_artifact_internal(job_id, artifact_type, artifact_data, metadata)
            except (OSError, IOError, PermissionError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Failed to store artifact {artifact_type} for job {job_id} (attempt {attempt + 1}/{max_retries}): {e}. Retrying..."
                    )
                    import time
                    time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"Failed to store artifact {artifact_type} for job {job_id} after {max_retries} attempts: {e}")
                    raise ArtifactStoreError(
                        f"Failed to store artifact {artifact_type} for job {job_id} after {max_retries} attempts: {e}"
                    )
            except Exception as e:
                # Non-retryable errors (e.g., validation errors)
                logger.error(f"Non-retryable error storing artifact {artifact_type} for job {job_id}: {e}")
                raise ArtifactStoreError(f"Failed to store artifact {artifact_type} for job {job_id}: {e}")
        
        # Should never reach here, but just in case
        raise ArtifactStoreError(
            f"Failed to store artifact {artifact_type} for job {job_id} after {max_retries} attempts: {last_error}"
        )
    
    def _store_artifact_internal(
        self,
        job_id: str,
        artifact_type: str,
        artifact_data: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Internal method to store an artifact (without retry logic).
        
        Args:
            job_id: Job identifier
            artifact_type: Type of artifact
            artifact_data: The artifact data
            metadata: Optional metadata
            
        Returns:
            Path to stored artifact (relative to base_dir)
        """
        job_dir = self._get_job_dir(job_id)
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ArtifactStoreError(f"Failed to create artifact directory for job {job_id}: {e}")
        
        # Determine file extension and serialization
        if artifact_type.startswith("plan_"):
            # Plans stored as JSON
            file_path = job_dir / f"{artifact_type}.json"
            content = json.dumps(artifact_data, indent=2, default=str)
            file_path.write_text(content, encoding='utf-8')
        elif artifact_type in ["git_diff", "validation_logs", "stdout_stderr"]:
            # Logs/diffs stored as text
            file_path = job_dir / f"{artifact_type}.txt"
            if isinstance(artifact_data, (dict, list)):
                content = json.dumps(artifact_data, indent=2, default=str)
            else:
                content = str(artifact_data)
            
            # Check size limit (100MB per artifact)
            MAX_ARTIFACT_SIZE = 100 * 1024 * 1024  # 100MB
            content_bytes = content.encode('utf-8')
            if len(content_bytes) > MAX_ARTIFACT_SIZE:
                raise ArtifactStoreError(
                    f"Artifact {artifact_type} exceeds size limit of {MAX_ARTIFACT_SIZE / (1024*1024)}MB. "
                    f"Size: {len(content_bytes) / (1024*1024):.2f}MB"
                )
            
            try:
                file_path.write_text(content, encoding='utf-8')
            except OSError as e:
                raise ArtifactStoreError(f"Failed to write artifact {artifact_type} for job {job_id}: {e}")
        elif artifact_type == "pr_metadata":
            # PR metadata as JSON
            file_path = job_dir / f"{artifact_type}.json"
            content = json.dumps(artifact_data, indent=2, default=str)
            file_path.write_text(content, encoding='utf-8')
        elif artifact_type == "input_spec":
            # Input spec as JSON
            file_path = job_dir / f"{artifact_type}.json"
            content = json.dumps(artifact_data, indent=2, default=str)
            file_path.write_text(content, encoding='utf-8')
        elif artifact_type == "workspace_fingerprint":
            # Fingerprint as JSON
            file_path = job_dir / f"{artifact_type}.json"
            content = json.dumps(artifact_data, indent=2, default=str)
            file_path.write_text(content, encoding='utf-8')
        else:
            # Default: try JSON, fallback to text
            file_path = job_dir / f"{artifact_type}.json"
            try:
                content = json.dumps(artifact_data, indent=2, default=str)
            except (TypeError, ValueError):
                content = str(artifact_data)
            file_path.write_text(content, encoding='utf-8')
        
        # Store metadata if provided
        if metadata:
            metadata_path = job_dir / f"{artifact_type}.metadata.json"
            metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding='utf-8')
        
        # Validate that artifact was stored successfully
        if not file_path.exists():
            raise ArtifactStoreError(f"Artifact file was not created: {file_path}")
        
        # Verify file is readable
        try:
            file_path.read_text(encoding='utf-8')
        except Exception as e:
            raise ArtifactStoreError(f"Stored artifact is not readable: {e}")
        
        logger.info(f"Stored artifact {artifact_type} for job {job_id} at {file_path}")
        return str(file_path.relative_to(self.base_dir))
    
    def retrieve_artifact(
        self,
        job_id: str,
        artifact_type: str
    ) -> Optional[Any]:
        """
        Retrieve an artifact for a job.
        
        Args:
            job_id: Job identifier
            artifact_type: Type of artifact to retrieve
            
        Returns:
            Artifact data (dict, string, etc.) or None if not found
        """
        job_dir = self._get_job_dir(job_id)
        
        # Try JSON first
        json_path = job_dir / f"{artifact_type}.json"
        if json_path.exists():
            try:
                return json.loads(json_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON artifact {artifact_type} for job {job_id}")
                return None
        
        # Try text file
        txt_path = job_dir / f"{artifact_type}.txt"
        if txt_path.exists():
            return txt_path.read_text(encoding='utf-8')
        
        logger.debug(f"Artifact {artifact_type} not found for job {job_id}")
        return None
    
    def list_artifacts(self, job_id: str) -> List[str]:
        """
        List all artifact types for a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            List of artifact type names
        """
        job_dir = self._get_job_dir(job_id)
        if not job_dir.exists():
            return []
        
        artifacts = []
        for file_path in job_dir.iterdir():
            if file_path.is_file() and not file_path.name.endswith('.metadata.json'):
                # Extract artifact type from filename
                name = file_path.stem  # Remove extension
                artifacts.append(name)
        
        return sorted(artifacts)
    
    def get_artifact_metadata(self, job_id: str, artifact_type: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for an artifact.
        
        Args:
            job_id: Job identifier
            artifact_type: Type of artifact
            
        Returns:
            Metadata dict or None if not found
        """
        job_dir = self._get_job_dir(job_id)
        metadata_path = job_dir / f"{artifact_type}.metadata.json"
        
        if metadata_path.exists():
            try:
                return json.loads(metadata_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse metadata for {artifact_type} in job {job_id}")
                return None
        
        return None
    
    def delete_job_artifacts(self, job_id: str) -> bool:
        """
        Delete all artifacts for a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if deletion succeeded
        """
        job_dir = self._get_job_dir(job_id)
        if job_dir.exists():
            import shutil
            try:
                shutil.rmtree(job_dir)
                logger.info(f"Deleted artifacts for job {job_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete artifacts for job {job_id}: {e}")
                return False
        return True
    
    def cleanup_old_artifacts(self) -> int:
        """
        Clean up artifacts older than retention period.
        
        Returns:
            Number of job directories cleaned up
        """
        if not self.base_dir.exists():
            return 0
        
        cutoff_time = datetime.now() - timedelta(days=self.retention_days)
        cleaned_count = 0
        
        for job_dir in self.base_dir.iterdir():
            if not job_dir.is_dir():
                continue
            
            try:
                # Check modification time
                mtime = datetime.fromtimestamp(job_dir.stat().st_mtime)
                if mtime < cutoff_time:
                    import shutil
                    shutil.rmtree(job_dir)
                    cleaned_count += 1
                    logger.info(f"Cleaned up old artifacts for job {job_dir.name}")
            except Exception as e:
                logger.warning(f"Error checking job directory {job_dir}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old artifact directories")
        
        return cleaned_count


# Global artifact store instance
_artifact_store: Optional[ArtifactStore] = None


def get_artifact_store() -> ArtifactStore:
    """Get or create global artifact store instance"""
    global _artifact_store
    if _artifact_store is None:
        _artifact_store = ArtifactStore()
    return _artifact_store
