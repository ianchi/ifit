#!/usr/bin/env bash
set -e

echo "🎨 Formatting code..."

echo ""
echo "🔧 Auto-fixing Ruff issues..."
poetry run ruff check --fix .

echo ""
echo "✨ Formatting with Ruff..."
poetry run ruff format .

echo ""
echo "✅ Code formatted successfully!"
