"""
Tests for Background Job Processing
Tests for ARQ background jobs, job queue, and job management endpoints
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient
import uuid

from api.models.generation import JobStatus, BatchResponse
from api.dependencies import jobs


@pytest.fixture
def mock_redis_pool():
    """Mock Redis connection pool"""
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=Mock(job_id="test-job-id"))
    pool.get_job = AsyncMock(return_value=Mock(
        cancelled=False,
        abort=AsyncMock()
    ))
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def sample_job_status():
    """Sample job status for testing"""
    return JobStatus(
        job_id="test-job-123",
        job_type="batch",
        status="started",
        progress={"message": "Test job"},
        started_at=datetime.now(),
        processed_tickets=0,
        successful_tickets=0,
        failed_tickets=0
    )


@pytest.fixture
def clear_jobs():
    """Clear jobs dict before and after test"""
    jobs.clear()
    yield
    jobs.clear()


class TestJobStatusModel:
    """Tests for JobStatus model"""
    
    def test_job_status_creation(self, clear_jobs):
        """Test creating a job status"""
        job = JobStatus(
            job_id="test-job-123",
            job_type="batch",
            status="started",
            progress={"message": "Test job"},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        
        assert job.job_id == "test-job-123"
        assert job.job_type == "batch"
        assert job.status == "started"
    
    def test_job_status_with_results(self, clear_jobs):
        """Test job status with results"""
        job = JobStatus(
            job_id="test-job-123",
            job_type="single",
            status="completed",
            progress={"message": "Completed"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            processed_tickets=1,
            successful_tickets=1,
            failed_tickets=0,
            results={"ticket_key": "PROJ-123", "success": True}
        )
        
        assert job.status == "completed"
        assert job.results is not None
        assert job.results["success"] is True


class TestJobStatusEndpoints:
    """Tests for job status API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client with mocked authentication"""
        from api.main import app
        from api.auth import get_current_user
        
        # Override auth dependency to bypass authentication in tests
        app.dependency_overrides[get_current_user] = lambda: "test_user"
        
        yield TestClient(app)
        
        # Clean up
        app.dependency_overrides.clear()
    
    def test_get_job_status_success(self, client, clear_jobs, sample_job_status):
        """Test getting job status successfully"""
        jobs["test-job-123"] = sample_job_status
        
        response = client.get("/jobs/test-job-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "started"
    
    def test_get_job_status_not_found(self, client, clear_jobs):
        """Test getting non-existent job status"""
        response = client.get("/jobs/non-existent-job")
        
        assert response.status_code == 404
    
    def test_list_jobs(self, client, clear_jobs):
        """Test listing all jobs"""
        jobs["job-1"] = JobStatus(
            job_id="job-1",
            job_type="batch",
            status="completed",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        jobs["job-2"] = JobStatus(
            job_id="job-2",
            job_type="single",
            status="processing",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        
        response = client.get("/jobs")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 2
    
    def test_list_jobs_filter_by_status(self, client, clear_jobs):
        """Test filtering jobs by status"""
        jobs["job-1"] = JobStatus(
            job_id="job-1",
            job_type="batch",
            status="completed",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        jobs["job-2"] = JobStatus(
            job_id="job-2",
            job_type="single",
            status="processing",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        
        response = client.get("/jobs?status=completed")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["status"] == "completed"
    
    def test_list_jobs_filter_by_job_type(self, client, clear_jobs):
        """Test filtering jobs by job type"""
        jobs["job-1"] = JobStatus(
            job_id="job-1",
            job_type="batch",
            status="completed",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        jobs["job-2"] = JobStatus(
            job_id="job-2",
            job_type="single",
            status="processing",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        
        response = client.get("/jobs?job_type=single")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["job_type"] == "single"
    
    def test_cancel_job_success(self, client, clear_jobs):
        """Test cancelling a job successfully"""
        jobs["test-job-123"] = JobStatus(
            job_id="test-job-123",
            job_type="batch",
            status="processing",
            progress={},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        
        mock_pool = AsyncMock()
        mock_arq_job = Mock()
        mock_arq_job.abort = AsyncMock()
        mock_pool.get_job = AsyncMock(return_value=mock_arq_job)
        
        async def mock_get_redis():
            return mock_pool
        
        with patch('api.routes.jobs.get_redis_pool', side_effect=mock_get_redis):
            response = client.delete("/jobs/test-job-123")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "cancelled"
            assert jobs["test-job-123"].status == "cancelled"
    
    def test_cancel_job_not_found(self, client, clear_jobs):
        """Test cancelling non-existent job"""
        response = client.delete("/jobs/non-existent-job")
        
        assert response.status_code == 404
    
    def test_cancel_job_wrong_status(self, client, clear_jobs):
        """Test cancelling job with wrong status"""
        jobs["test-job-123"] = JobStatus(
            job_id="test-job-123",
            job_type="batch",
            status="completed",
            progress={},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        
        response = client.delete("/jobs/test-job-123")
        
        assert response.status_code == 400


class TestAsyncModeEndpoints:
    """Tests for async mode in generation endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client with mocked authentication"""
        from api.main import app
        from api.auth import get_current_user
        
        # Override auth dependency to bypass authentication in tests
        app.dependency_overrides[get_current_user] = lambda: "test_user"
        
        yield TestClient(app)
        
        # Clean up
        app.dependency_overrides.clear()
    
    def test_single_ticket_async_mode(self, client, clear_jobs):
        """Test single ticket generation with async mode"""
        with patch('api.routes.generation.get_generator') as mock_get_gen:
            mock_generator = Mock()
            mock_get_gen.return_value = mock_generator
            
            mock_pool = AsyncMock()
            mock_job = Mock()
            mock_job.job_id = "test-job-id"
            mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
            
            # Patch get_redis_pool to return our mock (async function)
            async def mock_get_redis():
                return mock_pool
            
            with patch('api.routes.generation.get_redis_pool', side_effect=mock_get_redis):
                response = client.post(
                    "/generate/single",
                    json={
                        "ticket_key": "PROJ-123",
                        "async_mode": True,
                        "update_jira": False
                    }
                )
                
                assert response.status_code == 200
                data = response.json()
                assert "job_id" in data
                assert data["status"] == "started"
                assert "status_url" in data
                
                # Verify job was created
                assert data["job_id"] in jobs
    
    def test_single_ticket_sync_mode(self, client, clear_jobs):
        """Test single ticket generation with sync mode (default)"""
        with patch('api.routes.generation.get_generator') as mock_get_gen:
            with patch('api.routes.generation.get_jira_client') as mock_get_jira:
                mock_generator = Mock()
                mock_generator.process_ticket.return_value = Mock(
                    success=True,
                    description=Mock(
                        description="Test description",
                        system_prompt="System prompt",
                        user_prompt="User prompt"
                    ),
                    error=None,
                    skipped_reason=None,
                    llm_provider="openai",
                    llm_model="gpt-5-mini"
                )
                mock_get_gen.return_value = mock_generator
                
                mock_jira = Mock()
                mock_jira.get_ticket.return_value = {
                    'fields': {
                        'summary': 'Test Ticket',
                        'assignee': None,
                        'parent': None
                    }
                }
                mock_get_jira.return_value = mock_jira
                
                response = client.post(
                    "/generate/single",
                    json={
                        "ticket_key": "PROJ-123",
                        "async_mode": False,
                        "update_jira": False
                    }
                )
                
                assert response.status_code == 200
                data = response.json()
                assert "ticket_key" in data
                assert "generated_description" in data
                assert "job_id" not in data  # Should not return job_id in sync mode


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

