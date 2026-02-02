#!/usr/bin/env bash
set -e

echo "🔍 Running linters and type checkers..."

echo ""
echo "📝 Checking code with Ruff..."
poetry run ruff check .

echo ""
echo "🎨 Checking formatting with Ruff..."
poetry run ruff format --check .

echo ""
echo "🔎 Running type checker with Pyright..."
poetry run pyright

echo ""
echo "📖 Checking spelling with cspell..."
npx cspell "**/*.{py,md,yaml,yml,json,sh,toml}"

echo ""
echo "✅ All checks passed!"
