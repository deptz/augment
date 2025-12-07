"""
API Server - Backward Compatibility Wrapper
This file maintains backward compatibility by importing from the new modular api structure.

For new code, import directly from api.main:
    from api.main import app

For backward compatibility, this file can still be used:
    from api_server import app
"""
from api.main import app

# Re-export for backward compatibility
__all__ = ["app"]

# Start server when run directly (backward compatibility)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
