"""
Tests for ticket-based job tracking and duplicate prevention
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient
from api.main import app
from api.models.generation import JobStatus
from api.dependencies import jobs, ticket_jobs, get_active_job_for_ticket, register_ticket_job, unregister_ticket_job, get_job_by_ticket_key


@pytest.fixture(autouse=True)
def cleanup_jobs():
    """Clean up jobs and ticket_jobs before and after each test"""
    jobs.clear()
    ticket_jobs.clear()
    yield
    jobs.clear()
    ticket_jobs.clear()


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


class TestTicketJobMapping:
    """Test ticket-to-job mapping functions"""
    
    def test_register_ticket_job(self):
        """Test registering a ticket key to job ID"""
        register_ticket_job("PROJ-123", "job-1")
        assert ticket_jobs["PROJ-123"] == "job-1"
    
    def test_unregister_ticket_job(self):
        """Test unregistering a ticket key"""
        register_ticket_job("PROJ-123", "job-1")
        unregister_ticket_job("PROJ-123")
        assert "PROJ-123" not in ticket_jobs
    
    def test_get_active_job_for_ticket_no_job(self):
        """Test getting active job when none exists"""
        result = get_active_job_for_ticket("PROJ-123")
        assert result is None
    
    def test_get_active_job_for_ticket_active_job(self):
        """Test getting active job when ticket is actively processing"""
        job_id = "job-1"
        ticket_key = "PROJ-123"
        
        # Create job with started status
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        result = get_active_job_for_ticket(ticket_key)
        assert result == job_id
    
    def test_get_active_job_for_ticket_completed_job(self):
        """Test that completed jobs are not considered active"""
        job_id = "job-1"
        ticket_key = "PROJ-123"
        
        # Create completed job
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="completed",
            progress={"message": "Done"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        result = get_active_job_for_ticket(ticket_key)
        # Should return None and clean up the mapping
        assert result is None
        assert ticket_key not in ticket_jobs
    
    def test_get_job_by_ticket_key_active(self):
        """Test getting job by ticket key when active"""
        job_id = "job-1"
        ticket_key = "PROJ-123"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        result = get_job_by_ticket_key(ticket_key)
        assert result is not None
        assert result["job_id"] == job_id
        assert result["status"] == "started"
    
    def test_get_job_by_ticket_key_latest_completed(self):
        """Test getting latest completed job by ticket key"""
        ticket_key = "PROJ-123"
        
        # Create older completed job
        jobs["job-1"] = JobStatus(
            job_id="job-1",
            job_type="single",
            status="completed",
            progress={"message": "Done"},
            started_at=datetime(2024, 1, 1),
            completed_at=datetime(2024, 1, 1, 1),
            ticket_key=ticket_key
        )
        
        # Create newer completed job
        jobs["job-2"] = JobStatus(
            job_id="job-2",
            job_type="single",
            status="completed",
            progress={"message": "Done"},
            started_at=datetime(2024, 1, 2),
            completed_at=datetime(2024, 1, 2, 1),
            ticket_key=ticket_key
        )
        
        result = get_job_by_ticket_key(ticket_key)
        assert result is not None
        assert result["job_id"] == "job-2"  # Should return latest
    
    def test_get_job_by_ticket_key_not_found(self):
        """Test getting job by ticket key when none exists"""
        result = get_job_by_ticket_key("PROJ-999")
        assert result is None


class TestDuplicatePreventionSingleTicket:
    """Test duplicate prevention for single ticket generation"""
    
    @patch('api.routes.generation.get_generator')
    @patch('api.routes.generation.get_redis_pool')
    @patch('api.routes.generation.get_current_user')
    @patch('api.routes.generation.get_active_job_for_ticket')
    def test_reject_duplicate_single_ticket(self, mock_get_active, mock_user, mock_redis, mock_generator):
        """Test that duplicate single ticket requests are rejected"""
        from api.models.generation import SingleTicketRequest
        
        # Setup mocks
        mock_user.return_value = "test_user"
        mock_redis_pool = AsyncMock()
        mock_redis.return_value = mock_redis_pool
        
        ticket_key = "PROJ-123"
        job_id = "existing-job"
        
        # Mock get_active_job_for_ticket to return existing job
        mock_get_active.return_value = job_id
        
        # Create existing active job
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        
        # Try to create duplicate job
        request = SingleTicketRequest(
            ticket_key=ticket_key,
            async_mode=True,
            update_jira=False
        )
        
        client = TestClient(app)
        response = client.post(
            "/generate/single",
            json=request.dict(),
            headers={"Authorization": "Bearer test"}
        )
        
        assert response.status_code == 409
        assert "already being processed" in response.json()["detail"]
        assert response.headers.get("X-Active-Job-Id") == job_id
    
    @patch('api.routes.generation.get_generator')
    @patch('api.routes.generation.get_redis_pool')
    @patch('api.routes.generation.get_current_user')
    def test_allow_reprocessing_after_completion(self, mock_user, mock_redis, mock_generator):
        """Test that tickets can be reprocessed after completion"""
        from api.models.generation import SingleTicketRequest
        
        # Setup mocks
        mock_user.return_value = "test_user"
        mock_redis_pool = AsyncMock()
        mock_redis.return_value = mock_redis_pool
        
        ticket_key = "PROJ-123"
        job_id = "completed-job"
        
        # Create completed job
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="completed",
            progress={"message": "Done"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            ticket_key=ticket_key
        )
        # Don't register it (completed jobs are unregistered)
        
        # Should be able to create new job
        request = SingleTicketRequest(
            ticket_key=ticket_key,
            async_mode=True,
            update_jira=False
        )
        
        client = TestClient(app)
        with patch('api.routes.generation.uuid.uuid4', return_value=Mock(hex="new-job-id")):
            response = client.post(
                "/generate/single",
                json=request.dict(),
                headers={"Authorization": "Bearer test"}
            )
        
        # Should succeed (status 200 or 201, depending on implementation)
        assert response.status_code in [200, 201]


class TestDuplicatePreventionBatch:
    """Test duplicate prevention for batch processing"""
    
    @patch('api.workers.get_jira_client')
    @patch('api.workers.get_generator')
    @patch('api.workers._initialize_services_if_needed')
    def test_batch_skips_duplicate_tickets(self, mock_init, mock_generator, mock_jira):
        """Test that batch worker skips tickets already being processed"""
        from api.workers import process_batch_tickets_worker
        
        # Setup mocks
        mock_ticket1 = Mock()
        mock_ticket1.key = "PROJ-1"
        mock_ticket1.fields.summary = "Ticket 1"
        mock_ticket1.fields.assignee = None
        mock_ticket1.fields.parent = None
        
        mock_ticket2 = Mock()
        mock_ticket2.key = "PROJ-2"
        mock_ticket2.fields.summary = "Ticket 2"
        mock_ticket2.fields.assignee = None
        mock_ticket2.fields.parent = None
        
        mock_jira_client = Mock()
        mock_jira_client.search_issues.return_value = [mock_ticket1, mock_ticket2]
        mock_jira.return_value = mock_jira_client
        
        # Create active job for PROJ-1
        active_job_id = "active-job"
        jobs[active_job_id] = JobStatus(
            job_id=active_job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key="PROJ-1"
        )
        register_ticket_job("PROJ-1", active_job_id)
        
        # Create batch job
        batch_job_id = "batch-job"
        jobs[batch_job_id] = JobStatus(
            job_id=batch_job_id,
            job_type="batch",
            status="started",
            progress={"message": "Starting..."},
            started_at=datetime.now()
        )
        
        # Mock generator
        mock_gen = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_result.description = None
        mock_result.llm_provider = None
        mock_result.llm_model = None
        mock_gen.process_ticket.return_value = mock_result
        mock_generator.return_value = mock_gen
        
        # Run worker
        ctx = Mock()
        ctx.job = Mock()
        ctx.job.cancelled = False
        
        import asyncio
        asyncio.run(process_batch_tickets_worker(
            ctx, batch_job_id, "project = PROJ", 10, False
        ))
        
        # Check that PROJ-1 was skipped
        batch_job = jobs[batch_job_id]
        assert batch_job.status == "completed"
        # PROJ-1 should be in results with error about duplicate
        results = batch_job.results
        assert len(results) == 2
        
        # Find PROJ-1 result
        proj1_result = next((r for r in results if r.ticket_key == "PROJ-1"), None)
        assert proj1_result is not None
        assert proj1_result.success is False
        assert "already being processed" in proj1_result.error.lower() or "duplicate" in proj1_result.error.lower()


class TestDuplicatePreventionPlanning:
    """Test duplicate prevention for planning endpoints"""
    
    @patch('api.routes.planning.get_generator')
    @patch('api.routes.planning.get_current_user')
    @patch('api.routes.planning.get_active_job_for_ticket')
    def test_reject_duplicate_story_generation(self, mock_get_active, mock_user, mock_generator):
        """Test that duplicate story generation requests are rejected"""
        from api.models.planning import StoryGenerationRequest
        
        # Setup mocks
        mock_user.return_value = "test_user"
        
        epic_key = "EPIC-1"
        job_id = "existing-job"
        
        # Mock get_active_job_for_ticket to return existing job
        mock_get_active.return_value = job_id
        
        # Create existing active job
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="story_generation",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=epic_key
        )
        
        # Try to create duplicate job
        request = StoryGenerationRequest(
            epic_key=epic_key,
            async_mode=True,
            dry_run=True
        )
        
        client = TestClient(app)
        with patch('api.routes.planning.get_redis_pool') as mock_redis:
            mock_redis_pool = AsyncMock()
            mock_redis.return_value = mock_redis_pool
            response = client.post(
                "/plan/stories/generate",
                json=request.dict(),
                headers={"Authorization": "Bearer test"}
            )
        
        assert response.status_code == 409
        assert "already being processed" in response.json()["detail"]
    
    @patch('api.routes.planning.get_generator')
    @patch('api.routes.planning.get_current_user')
    @patch('api.routes.planning.get_active_job_for_ticket')
    def test_reject_duplicate_task_generation(self, mock_get_active, mock_user, mock_generator):
        """Test that duplicate task generation requests are rejected"""
        from api.models.planning import TaskGenerationRequest
        
        # Setup mocks
        mock_user.return_value = "test_user"
        
        story_key = "STORY-1"
        job_id = "existing-job"
        
        # Mock get_active_job_for_ticket to return existing job for the story
        mock_get_active.return_value = job_id
        
        # Create existing active job
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="task_generation",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_keys=[story_key]
        )
        
        # Try to create duplicate job
        request = TaskGenerationRequest(
            story_keys=[story_key],
            epic_key="EPIC-1",
            async_mode=True,
            dry_run=True
        )
        
        client = TestClient(app)
        with patch('api.routes.planning.get_redis_pool') as mock_redis:
            mock_redis_pool = AsyncMock()
            mock_redis.return_value = mock_redis_pool
            response = client.post(
                "/plan/tasks/generate",
                json=request.dict(),
                headers={"Authorization": "Bearer test"}
            )
        
        assert response.status_code == 409
        assert "already being processed" in response.json()["detail"]


class TestTicketStatusEndpoint:
    """Test the GET /jobs/ticket/{ticket_key} endpoint"""
    
    @patch('api.routes.jobs.get_current_user')
    def test_get_status_by_ticket_key_active(self, mock_user):
        """Test getting status for active job by ticket key"""
        mock_user.return_value = "test_user"
        
        ticket_key = "PROJ-123"
        job_id = "job-1"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        client = TestClient(app)
        response = client.get(
            f"/jobs/ticket/{ticket_key}",
            headers={"Authorization": "Bearer test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["ticket_key"] == ticket_key
        assert data["status"] == "started"
    
    @patch('api.routes.jobs.get_current_user')
    def test_get_status_by_ticket_key_completed(self, mock_user):
        """Test getting status for completed job by ticket key"""
        mock_user.return_value = "test_user"
        
        ticket_key = "PROJ-123"
        job_id = "job-1"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="completed",
            progress={"message": "Done"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            ticket_key=ticket_key
        )
        # Don't register (completed jobs are unregistered)
        
        client = TestClient(app)
        response = client.get(
            f"/jobs/ticket/{ticket_key}",
            headers={"Authorization": "Bearer test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "completed"
    
    @patch('api.routes.jobs.get_current_user')
    def test_get_status_by_ticket_key_not_found(self, mock_user):
        """Test getting status for non-existent ticket key"""
        mock_user.return_value = "test_user"
        
        client = TestClient(app)
        response = client.get(
            "/jobs/ticket/PROJ-999",
            headers={"Authorization": "Bearer test"}
        )
        
        assert response.status_code == 404
        assert "no job found" in response.json()["detail"].lower()
    
    @patch('api.routes.jobs.get_current_user')
    def test_get_status_by_ticket_key_in_batch(self, mock_user):
        """Test getting status for ticket in batch job"""
        mock_user.return_value = "test_user"
        
        ticket_key = "PROJ-123"
        job_id = "batch-job"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="batch",
            status="completed",
            progress={"message": "Done"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            ticket_keys=[ticket_key, "PROJ-456"]
        )
        
        client = TestClient(app)
        response = client.get(
            f"/jobs/ticket/{ticket_key}",
            headers={"Authorization": "Bearer test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert ticket_key in data["ticket_keys"]


class TestTicketKeyCleanup:
    """Test that ticket keys are properly cleaned up"""
    
    def test_cleanup_on_job_completion(self):
        """Test that ticket keys are unregistered when job completes"""
        ticket_key = "PROJ-123"
        job_id = "job-1"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        # Simulate job completion
        job = jobs[job_id]
        job.status = "completed"
        job.completed_at = datetime.now()
        unregister_ticket_job(ticket_key)
        
        # Ticket should be unregistered
        assert ticket_key not in ticket_jobs
        assert get_active_job_for_ticket(ticket_key) is None
    
    def test_cleanup_on_job_failure(self):
        """Test that ticket keys are unregistered when job fails"""
        ticket_key = "PROJ-123"
        job_id = "job-1"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        # Simulate job failure
        job = jobs[job_id]
        job.status = "failed"
        job.completed_at = datetime.now()
        job.error = "Test error"
        unregister_ticket_job(ticket_key)
        
        # Ticket should be unregistered
        assert ticket_key not in ticket_jobs
    
    @patch('api.routes.jobs.get_redis_pool')
    @patch('api.routes.jobs.get_current_user')
    def test_cleanup_on_job_cancellation(self, mock_user, mock_redis):
        """Test that ticket keys are unregistered when job is cancelled"""
        mock_user.return_value = "test_user"
        mock_redis_pool = AsyncMock()
        mock_arq_job = AsyncMock()
        mock_redis_pool.get_job.return_value = mock_arq_job
        mock_redis.return_value = mock_redis_pool
        
        ticket_key = "PROJ-123"
        job_id = "job-1"
        
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="single",
            status="started",
            progress={"message": "Processing..."},
            started_at=datetime.now(),
            ticket_key=ticket_key
        )
        register_ticket_job(ticket_key, job_id)
        
        client = TestClient(app)
        response = client.delete(
            f"/jobs/{job_id}",
            headers={"Authorization": "Bearer test"}
        )
        
        assert response.status_code == 200
        # Ticket should be unregistered
        assert ticket_key not in ticket_jobs

