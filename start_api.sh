#!/bin/bash

# Augment API Server Startup Script

echo "🚀 Starting Augment API Server..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Please run 'python3 -m venv venv' first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "📦 Installing/updating dependencies..."
pip install -r requirements.txt

# Create exports directory if it doesn't exist
mkdir -p exports

# Check if config file exists
if [ ! -f "config.yaml" ]; then
    echo "❌ config.yaml not found. Please create configuration file first."
    exit 1
fi

# Start the API server
echo "🌐 Starting API server on http://localhost:8000"
echo "📖 API documentation will be available at http://localhost:8000/docs"
echo "🔧 Admin interface at http://localhost:8000/redoc"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
