"""
Main FastAPI Application
FastAPI app creation, CORS configuration, middleware, and startup/shutdown events
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
import os
import logging

from .dependencies import initialize_services, auth_config
from .routes import api_router

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Augment",
    description="JIRA automation platform for generating ticket descriptions, creating tasks, and managing workflows.",
    version="1.0.0",
    contact={
        "name": "Augment Team",
        "url": "https://github.com/deptz/augment",
        "email": "puji@triwibowo.com"
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT"
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Configure CORS
# More permissive for development - allows all localhost origins
cors_origins = [
    "http://localhost:5173",  # Vite default dev server
    "http://localhost:3000",  # Common React/Next.js dev server
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "https://augment.triwibowo.com"
]

# Allow all localhost ports for development (add more if needed)
for port in [5173, 3000, 5174, 5175, 5176, 5177, 5178, 5179, 8080, 8081, 5000, 5001, 4000, 4001, 4002, 4003]:
    cors_origins.extend([
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}"
    ])

# CORS configuration - use permissive mode in development
is_development = os.getenv("ENVIRONMENT", "development").lower() == "development"

if is_development:
    # In development, allow all origins (less secure but easier to debug)
    logger.info("CORS: Running in development mode - allowing all origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins in development
        allow_credentials=False,  # Must be False when using allow_origins=["*"]
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
else:
    # Production: use explicit origin list
    logger.info(f"CORS: Running in production mode - allowing {len(cors_origins)} origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


# Add middleware to log CORS-related requests for debugging
@app.middleware("http")
async def cors_logging_middleware(request: Request, call_next):
    """Log CORS-related requests for debugging"""
    if request.method == "OPTIONS":
        origin = request.headers.get("origin", "unknown")
        logger.info(f"CORS OPTIONS request from origin: {origin}, path: {request.url.path}")
    response = await call_next(request)
    return response


# Include all routers
app.include_router(api_router)


# Enhanced OpenAPI schema for better documentation
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Augment API",
        version="1.0.0",
        description=app.description,
        routes=app.routes,
    )
    
    # Add custom info for better Swagger documentation
    openapi_schema["info"]["x-logo"] = {
        "url": "https://img.icons8.com/color/96/jira.png"
    }
    
    # Add security schemes for HTTP Basic Authentication
    openapi_schema["components"]["securitySchemes"] = {
        "HTTPBasic": {
            "type": "http",
            "scheme": "basic",
            "description": "HTTP Basic Authentication. Required when AUTH_ENABLED=true (except for health check endpoints)."
        }
    }
    
    # Add security requirements to all endpoints except health checks
    # Health endpoints are explicitly marked as public
    if auth_config.get("enabled", False):
        # Apply security to all paths
        for path, methods in openapi_schema.get("paths", {}).items():
            # Skip health check endpoints
            if path in ["/", "/health"]:
                continue
            
            # Add security requirement to all methods in this path
            for method in methods.values():
                if isinstance(method, dict) and "security" not in method:
                    method["security"] = [{"HTTPBasic": []}]
        
        # Also set global security as fallback
        openapi_schema["security"] = [{"HTTPBasic": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# Custom Swagger UI with enhanced documentation
@app.get("/swagger-ui.html", include_in_schema=False)
async def custom_swagger_ui_html():
    """Custom Swagger UI with enhanced styling"""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.15.5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.15.5/swagger-ui.css",
    )


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize all clients and services on startup"""
    # Ensure database is ready before initializing services
    try:
        from src.team_member_db import ensure_database_ready
        ensure_database_ready()
        logger.info("✅ Team member database verified and ready")
    except Exception as e:
        logger.error(f"❌ Failed to ensure database is ready: {e}")
        # Don't fail startup, but log the error - some endpoints may not work
        logger.warning("⚠️  Continuing startup, but team member features may not work")
    
    initialize_services()
    # Initialize Redis connection pool for ARQ
    try:
        from .job_queue import initialize_redis
        await initialize_redis()
    except Exception as e:
        logger.warning(f"Failed to initialize Redis (background jobs may not work): {e}")


# Shutdown event (if needed)
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Application shutting down")
    # Close Redis connection pool
    try:
        from .job_queue import close_redis
        await close_redis()
    except Exception as e:
        logger.warning(f"Error closing Redis connection: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

