#!/usr/bin/env bash
set -e

echo "🚀 Setting up development environment..."

# Check if poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry is not installed. Please install it first:"
    echo "   curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install Node.js first."
    exit 1
fi

echo "📦 Installing Python dependencies with Poetry..."
poetry install --with dev --with test

echo "📦 Installing Node.js dependencies (cspell)..."
npm install

echo "🔧 Setting up pre-commit hooks..."
poetry run pre-commit install --install-hooks

echo "✅ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  - Run 'poetry shell' to activate the virtual environment"
echo "  - Run './scripts/lint.sh' to check code"
echo "  - Run './scripts/format.sh' to format code"
