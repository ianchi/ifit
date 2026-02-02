# Contributing to iFit

Thank you for your interest in contributing to iFit! This document provides guidelines and instructions for contributing.

## Development Setup

1. **Prerequisites**
   - Python 3.11 or higher
   - Poetry for dependency management
   - Git for version control

2. **Initial Setup**

   ```bash
   # Clone the repository
   git clone https://github.com/ianchi/ifit.git
   cd ifit

   # Run the setup script
   ./scripts/setup.sh
   
   # Activate the virtual environment
   poetry shell
   ```

## Development Workflow

### Making Changes

1. **Create a feature branch**

   ```bash
   git checkout -b features/your-feature-name/description
   ```

2. **Make your changes**
   - Write code following the project's style guidelines
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests and linters**

   ```bash
   ./scripts/lint.sh      # Check code quality
   ./scripts/format.sh    # Format code
   ./scripts/test.sh      # Run tests
   ```

4. **Commit your changes**
   - Use conventional commit messages
   - Pre-commit hooks will run automatically

   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

### Commit Message Format

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - A new feature
- `fix:` - A bug fix
- `docs:` - Documentation only changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Example: `feat: add support for new iFit device model`

### Code Style

- **Line length**: 100 characters
- **Indentation**: 4 spaces for Python
- **Quotes**: Double quotes for strings
- **Type hints**: Required for all function signatures
- **Docstrings**: Google style for all public APIs

### Testing

- Write unit tests for all new functionality
- Use pytest markers:
  - `@pytest.mark.unit` - Fast unit tests
  - `@pytest.mark.integration` - Integration tests
  - `@pytest.mark.slow` - Slow running tests

```python
import pytest

@pytest.mark.unit
def test_example():
    assert True
```

### Pre-commit Hooks

Pre-commit hooks automatically run:

- Ruff linting and formatting
- Pyright type checking
- Various file checks
- Spell checking
- Conventional commit validation

To run manually:

```bash
pre-commit run --all-files
```

## Pull Request Process

1. Ensure all tests pass and code is properly formatted
2. Update the README.md or documentation if needed
3. Update CHANGELOG.md with your changes
4. Create a pull request with a clear description
5. Wait for review and address any feedback

## Questions or Issues?

- Open an issue for bugs or feature requests
- Use discussions for questions and general discussion

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
