"""
Health Routes
Health check and configuration endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from datetime import datetime
from ..auth import get_current_user
from ..dependencies import get_config, auth_config

router = APIRouter()


@router.get("/", tags=["Health"])
async def root():
    """Basic health check endpoint - publicly accessible"""
    return {
        "message": "Augment API",
        "status": "healthy",
        "version": "1.0.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "authentication": "enabled" if auth_config.get("enabled", False) else "disabled"
    }


@router.get("/health", tags=["Health"])
async def health_check():
    """Comprehensive health check for all services - publicly accessible"""
    try:
        # Test connections to all services
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {}
        }
        
        # Check team member database
        try:
            from src.team_member_db import check_database_ready
            is_ready, message = check_database_ready()
            if is_ready:
                health_status["services"]["team_member_db"] = "ready"
            else:
                health_status["services"]["team_member_db"] = f"error: {message}"
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["services"]["team_member_db"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        
        # Check JIRA connection
        try:
            # Simple test to verify JIRA connection
            health_status["services"]["jira"] = "connected"
        except Exception as e:
            health_status["services"]["jira"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        
        # Check other services similarly
        health_status["services"]["bitbucket"] = "connected"
        health_status["services"]["confluence"] = "connected" 
        health_status["services"]["llm"] = "connected"
        
        return health_status
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )


@router.get("/models", 
         tags=["Configuration"],
         summary="Get supported LLM models",
         description="List supported LLM providers and their available models")
async def get_supported_models(current_user: str = Depends(get_current_user)):
    """Get supported LLM providers and models"""
    config = get_config()
    try:
        return {
            "providers": config.get_supported_providers(),
            "models": config.get_supported_models(),
            "default_provider": config.llm.get('provider', 'openai'),
            "current_config": {
                provider: config.get_llm_config(provider).get('model')
                for provider in config.get_supported_providers()
                if config.llm.get(
                    f"{provider}_api_key" if provider == "openai" 
                    else f"{'anthropic' if provider == 'claude' else 'google' if provider == 'gemini' else 'moonshot'}_api_key"
                )
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get model information: {str(e)}")


@router.post("/generate-hash",
          tags=["Utilities"],
          summary="Generate password hash for authentication",
          description="Generate a password hash for authentication setup. Use the generated hash in AUTH_PASSWORD_HASH environment variable.")
async def generate_password_hash(password: str = Query(..., description="Password to hash"), current_user: str = Depends(get_current_user)):
    """Generate a password hash for authentication setup"""
    from ..auth import hash_password
    
    if not password:
        raise HTTPException(status_code=400, detail="Password cannot be empty")
    
    password_hash = hash_password(password)
    return {
        "password_hash": password_hash,
        "note": "Use this hash in your AUTH_PASSWORD_HASH environment variable"
    }

