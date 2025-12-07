"""
Authentication Module
Authentication middleware and password hashing utilities
"""
import secrets
import hashlib
import base64
from fastapi import HTTPException, Request, Depends
from .dependencies import auth_config

def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def get_current_user(request: Request) -> str:
    """Get current user with optional authentication"""
    if not auth_config.get("enabled", False):
        return "anonymous"
    
    # Authentication is enabled, check for Authorization header
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    try:
        scheme, credentials = authorization.split()
        if scheme.lower() != "basic":
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Basic"},
            )
        
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
        
        # Validate credentials
        username_correct = secrets.compare_digest(
            username.encode("utf8"), auth_config["username"].encode("utf8")
        )
        password_hash = hash_password(password)
        password_correct = secrets.compare_digest(
            password_hash.encode("utf8"), auth_config["password_hash"].encode("utf8")
        )
        
        if not (username_correct and password_correct):
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
        
        return username
        
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

