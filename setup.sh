#!/bin/bash

# Setup script for Augment

echo "🚀 Setting up Augment..."

# Check if Python 3.8+ is available
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
required_version="3.8"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
    echo "❌ Python 3.8+ is required. Current version: $python_version"
    exit 1
fi

echo "✅ Python version: $(python3 --version)"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
else
    echo "📦 Virtual environment already exists"
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Copy environment template
if [ ! -f ".env" ]; then
    echo "📋 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your configuration"
else
    echo "📋 .env file already exists"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo "1. Edit .env file with your API credentials"
echo "2. Update config.yaml if needed"
echo "3. Test the connection: python main.py test"
echo "4. Try a single ticket: python main.py single TICKET-123"
echo ""
echo "🔍 To use the tool:"
echo "  # Activate environment"
echo "  source venv/bin/activate"
echo ""
echo "  # Test connections"
echo "  python main.py test"
echo ""
echo "  # Process single ticket (dry run)"
echo "  python main.py single TICKET-123"
echo ""
echo "  # Process batch (dry run)"
echo "  python main.py batch \"project = 'PROJ' AND description is EMPTY\""
echo ""
echo "  # Process batch (actually update)"
echo "  python main.py batch \"project = 'PROJ' AND description is EMPTY\" --update"
