#!/usr/bin/env bash
set -e

echo "🧪 Running tests..."

echo ""
echo "📊 Running pytest with coverage..."
poetry run pytest --cov=ifit --cov-report=term-missing

echo ""
echo "✅ Tests completed!"
