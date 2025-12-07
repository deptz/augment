#!/usr/bin/env python3
"""
Generate static OpenAPI JSON documentation
"""

import json
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from api_server import app
    
    # Generate OpenAPI schema
    openapi_schema = app.openapi()
    
    # Save to file
    with open('openapi.json', 'w') as f:
        json.dump(openapi_schema, f, indent=2)
    
    print("✅ OpenAPI schema generated: openapi.json")
    print("📖 You can use this file with Swagger UI or other OpenAPI tools")
    
except Exception as e:
    print(f"❌ Error generating OpenAPI schema: {e}")
    print("Make sure all dependencies are installed: pip install -r requirements.txt")
