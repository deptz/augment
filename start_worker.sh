#!/bin/bash

# Augment Worker Startup Script

echo "🔧 Starting Augment Worker..."

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

# Check if config file exists
if [ ! -f "config.yaml" ]; then
    echo "❌ config.yaml not found. Please create configuration file first."
    exit 1
fi

# Start the worker
echo "⚙️  Starting ARQ worker process..."
echo "📋 Worker will process background jobs from the queue"
echo ""
echo "Press Ctrl+C to stop the worker"
echo ""

python run_worker.py

