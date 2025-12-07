"""
Test Generation Routes
Endpoints for test case generation
"""
from fastapi import APIRouter, HTTPException, Depends
import logging

from ..models.test_generation import (
    TestGenerationRequest,
    TestCaseModel,
    TestGenerationResponse,
    ComprehensiveTestSuiteResponse
)
from ..dependencies import get_generator
from ..utils import create_custom_llm_client
from ..auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/plan/tests/comprehensive", 
          tags=["Test Generation"],
          response_model=ComprehensiveTestSuiteResponse,
          summary="Generate comprehensive test suite for an epic",
          description="Generate complete test suites for all stories and tasks in an epic. Coverage levels: minimal, basic, standard (default), comprehensive.")
async def generate_comprehensive_test_suite(
    request: TestGenerationRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate comprehensive test suite for an epic"""
    from ..job_queue import get_redis_pool
    from ..models.generation import BatchResponse, JobStatus
    from ..dependencies import jobs
    from datetime import datetime
    import uuid
    
    generator = get_generator()
    
    try:
        if not request.epic_key:
            raise HTTPException(status_code=400, detail="epic_key is required for comprehensive test generation")
        
        logger.info(f"User {current_user} generating comprehensive test suite for epic {request.epic_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # If async mode, enqueue job
        if request.async_mode:
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="test_generation",
                status="started",
                progress={"message": f"Queued for generating comprehensive test suite for epic {request.epic_key}"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0
            )
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_test_generation_worker',
                job_id=job_id,
                test_type="comprehensive",
                epic_key=request.epic_key,
                coverage_level=request.coverage_level,
                domain_context=request.domain_context,
                technical_context=request.technical_context,
                include_documents=request.include_documents,
                llm_model=request.llm_model,
                llm_provider=request.llm_provider,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued comprehensive test generation job {job_id} for epic {request.epic_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Comprehensive test generation for epic {request.epic_key} queued",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=0,
                update_jira=False,
                safety_note="Test generation does not modify JIRA"
            )
        
        # Synchronous mode (original behavior)
        # Import coverage level enum
        from src.enhanced_test_generator import TestCoverageLevel
        coverage_level = TestCoverageLevel(request.coverage_level)
        
        # Generate comprehensive test suite
        test_results = generator.planning_service.generate_comprehensive_test_suite(
            epic_key=request.epic_key,
            coverage_level=coverage_level
        )
        
        if not test_results["success"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to generate test suite: {'; '.join(test_results.get('errors', ['Unknown error']))}"
            )
        
        # Convert to API response format
        response = ComprehensiveTestSuiteResponse(
            success=test_results["success"],
            epic_key=test_results["epic_key"],
            coverage_level=test_results["coverage_level"],
            story_tests=test_results["story_tests"],
            task_tests=test_results["task_tests"],
            total_test_cases=test_results["total_test_cases"],
            test_statistics=test_results["test_statistics"],
            errors=test_results["errors"],
            execution_time_seconds=test_results["execution_time_seconds"]
        )
        
        logger.info(f"Generated {response.total_test_cases} test cases for epic {request.epic_key}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating comprehensive test suite for {request.epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate test suite: {str(e)}")


@router.post("/plan/tests/story", 
          tags=["Test Generation"],
          response_model=TestGenerationResponse,
          summary="Generate test cases for a story",
          description="Generate targeted test cases for a story including acceptance, integration, E2E, performance, and security tests. Coverage levels: minimal, basic, standard (default), comprehensive.")
async def generate_story_tests(
    request: TestGenerationRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate test cases for a specific story"""
    generator = get_generator()
    
    try:
        if not request.story_key:
            raise HTTPException(status_code=400, detail="story_key is required for story test generation")
        
        logger.info(f"User {current_user} generating tests for story {request.story_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Create custom LLM client if provider/model specified
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        # Import coverage level enum
        from src.enhanced_test_generator import TestCoverageLevel
        coverage_level = TestCoverageLevel(request.coverage_level)
        
        # Generate story tests
        test_results = generator.planning_service.generate_story_tests(
            story_key=request.story_key,
            coverage_level=coverage_level
        )
        
        if not test_results["success"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to generate story tests: {'; '.join(test_results.get('errors', ['Unknown error']))}"
            )
        
        # Convert test cases to API format
        test_cases = [
            TestCaseModel(
                title=tc["title"],
                type=tc["type"],
                description=tc["description"],
                expected_result=tc["expected_result"],
                priority=tc.get("priority"),
                traceability=tc.get("traceability"),
                precondition=tc.get("precondition"),
                test_steps=tc.get("test_steps"),
                source=tc.get("source")
            )
            for tc in test_results["test_cases"]
        ]
        
        # Convert to API response format
        response = TestGenerationResponse(
            success=test_results["success"],
            coverage_level=test_results["coverage_level"],
            story_key=test_results["story_key"],
            test_cases=test_cases,
            test_count=test_results["test_count"],
            domain_context=test_results.get("domain_context"),
            errors=test_results["errors"],
            execution_time_seconds=test_results["execution_time_seconds"]
        )
        
        logger.info(f"Generated {response.test_count} test cases for story {request.story_key}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating story tests for {request.story_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate story tests: {str(e)}")


@router.post("/plan/tests/task", 
          tags=["Test Generation"],
          response_model=TestGenerationResponse,
          summary="Generate test cases for a task",
          description="Generate test cases for a technical task including unit, integration, performance, and security tests. Coverage levels: minimal, basic, standard (default), comprehensive.")
async def generate_task_tests(
    request: TestGenerationRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate test cases for a specific task"""
    generator = get_generator()
    
    try:
        if not request.task_key:
            raise HTTPException(status_code=400, detail="task_key is required for task test generation")
        
        logger.info(f"User {current_user} generating tests for task {request.task_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Create custom LLM client if provider/model specified
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        # Import coverage level enum
        from src.enhanced_test_generator import TestCoverageLevel
        coverage_level = TestCoverageLevel(request.coverage_level)
        
        # Generate task tests
        test_results = generator.planning_service.generate_task_tests(
            task_key=request.task_key,
            coverage_level=coverage_level
        )
        
        if not test_results["success"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to generate task tests: {'; '.join(test_results.get('errors', ['Unknown error']))}"
            )
        
        # Convert test cases to API format
        test_cases = [
            TestCaseModel(
                title=tc["title"],
                type=tc["type"],
                description=tc["description"],
                expected_result=tc["expected_result"],
                priority=tc.get("priority"),
                traceability=tc.get("traceability"),
                precondition=tc.get("precondition"),
                test_steps=tc.get("test_steps"),
                source=tc.get("source")
            )
            for tc in test_results["test_cases"]
        ]
        
        # Convert to API response format
        response = TestGenerationResponse(
            success=test_results["success"],
            coverage_level=test_results["coverage_level"],
            task_key=test_results["task_key"],
            test_cases=test_cases,
            test_count=test_results["test_count"],
            technical_context=test_results.get("technical_context"),
            errors=test_results["errors"],
            execution_time_seconds=test_results["execution_time_seconds"]
        )
        
        logger.info(f"Generated {response.test_count} test cases for task {request.task_key}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating task tests for {request.task_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate task tests: {str(e)}")


@router.post("/plan/tests/task/context-aware", 
          tags=["Test Generation"],
          response_model=TestGenerationResponse,
          summary="Generate context-aware test cases for a task",
          description="Generate test cases for a task using context from parent story, PRD/RFC documents, and task details. Coverage levels: minimal, basic, standard (default), comprehensive.")
async def generate_context_aware_task_tests(
    request: TestGenerationRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate context-aware test cases for a task with story and document context"""
    generator = get_generator()
    
    try:
        if not request.task_key:
            raise HTTPException(status_code=400, detail="task_key is required for context-aware task test generation")
        
        logger.info(f"User {current_user} generating context-aware tests for task {request.task_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Create custom LLM client if provider/model specified
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        # Import coverage level enum
        from src.enhanced_test_generator import TestCoverageLevel
        coverage_level = TestCoverageLevel(request.coverage_level)
        
        # Generate context-aware task tests
        test_results = generator.planning_service.generate_context_aware_task_tests(
            task_key=request.task_key,
            coverage_level=coverage_level,
            technical_context=getattr(request, 'technical_context', None),
            include_documents=getattr(request, 'include_documents', True),
            custom_llm_client=custom_llm_client
        )
        
        if not test_results["success"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to generate context-aware task tests: {'; '.join(test_results.get('errors', ['Unknown error']))}"
            )
        
        # Convert test cases to API format
        test_cases = [
            TestCaseModel(
                title=tc["title"],
                type=tc["type"],
                description=tc["description"],
                expected_result=tc["expected_result"],
                priority=tc.get("priority", "P2"),
                traceability=tc.get("traceability", ""),
                precondition=tc.get("precondition", ""),
                test_steps=tc.get("test_steps", ""),
                source=tc.get("source")
            )
            for tc in test_results["test_cases"]
        ]
        
        # Enhanced response with context information
        response = TestGenerationResponse(
            success=test_results["success"],
            coverage_level=test_results["coverage_level"],
            task_key=test_results["task_key"],
            test_cases=test_cases,
            test_count=test_results["test_count"],
            technical_context=test_results.get("technical_context"),
            story_context=test_results.get("story_context"),
            document_context=test_results.get("document_context"),
            context_sources=test_results.get("context_sources", []),
            errors=test_results["errors"],
            execution_time_seconds=test_results["execution_time_seconds"]
        )
        
        logger.info(f"Generated {response.test_count} context-aware test cases for task {request.task_key}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating context-aware task tests for {request.task_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate context-aware task tests: {str(e)}")
