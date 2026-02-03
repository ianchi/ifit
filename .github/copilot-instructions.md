# GitHub Copilot Instructions for iFit Project

## Project Overview

This is a Python BLE (Bluetooth Low Energy) client and FTMS relay for iFit equipment. The project enables communication with iFit fitness equipment via Bluetooth and provides relay functionality for FTMS (Fitness Machine Service) protocol.

## Code Style & Formatting

### Python Standards

- **Python Version**: 3.11 (required, not 3.12+)
- **Line Length**: Maximum 100 characters
- **Type Hints**: Always include type annotations (enforced by ruff ANN rules)
- **Future Imports**: Use `from __future__ import annotations` at the top of files for forward references
- **Docstrings**: Required for all public modules, classes, and functions (Google-style)
- **Quote Style**: Double quotes for strings
- **Indentation**: 4 spaces (no tabs)

### Code Quality Tools

- **Formatter**: `ruff` (run with `./scripts/format.sh`)
- **Linter**: `ruff` with extensive rule set (run with `./scripts/lint.sh`)
- **Type Checker**: `pyright` for static type checking
- **Testing**: `pytest` with `pytest-asyncio` for async tests

### Naming Conventions

- **Classes**: PascalCase (e.g., `SportsEquipment`, `PulseSource`)
- **Functions/Methods**: snake_case with leading underscore for private (e.g., `_parse_args`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `RESPONSE_OK_CODE`, `MAX_BYTES_PER_MESSAGE`)
- **Enums**: Use IntEnum for protocol constants

## Project Structure

```
ifit/
├── cli/              # Command-line interface modules
│   ├── _main.py      # Main CLI entry point (argparse-based)
│   ├── _device.py    # Device operations (activate, info, get, set)
│   ├── _discovery.py # Device discovery and scanning
│   ├── _monitor.py   # Monitor mode functionality
│   └── _relay.py     # FTMS relay functionality
├── client/           # iFit protocol client
│   ├── _client.py    # BLE client implementation
│   ├── protocol.py   # Protocol definitions, enums, and data classes
│   └── codes.csv     # Device code mappings
├── ftms/             # FTMS server implementation
│   ├── _cli.py       # FTMS CLI commands
│   ├── _ftms.py      # FTMS protocol implementation
│   └── _server.py    # BLE server for FTMS
└── interceptor/      # Discovery and interception tools
    └── _discovery.py # Interactive activation code discovery
```

### Module Organization

- Use `_` prefix for internal/private modules (e.g., `_client.py`, `_main.py`)
- Public API exposed through `__init__.py` files
- Separate CLI logic from core functionality

## Coding Patterns

### Async/Await

- All BLE operations are asynchronous using `asyncio`
- Use `async def` for coroutines, `await` for async calls
- Use `bleak` library for BLE communication
- Follow proper async context manager patterns with `async with`

### Data Classes

- Use `@dataclass` decorator from standard library for data structures
- Use `field()` for default factories and metadata
- Example:

  ```python
  from dataclasses import dataclass, field

  @dataclass
  class Message:
      command: Command
      payload: bytes = field(default_factory=bytes)
  ```

### Enums

- Use `IntEnum` for protocol constants that map to integer values
- Keep enum definitions in `protocol.py`
- Use descriptive names that match protocol documentation

### Type Annotations

- Required for all function parameters and return types
- Use modern type hints: `list[str]` not `List[str]`
- Use `collections.abc` for abstract types (Callable, Iterable, Mapping)
- Use type aliases for complex types
- Example:

  ```python
  from collections.abc import Callable, Iterable

  def process_items(items: Iterable[str]) -> list[str]:
      ...
  ```

### Error Handling

- Catch specific exceptions, avoid bare `except:`
- Use `BLE001` exception when broad catching is intentional (scripts)
- Provide informative error messages
- Use logging instead of print statements (except in scripts)

### Logging

- Use standard library `logging` module
- Create module-level loggers: `LOGGER = logging.getLogger(__name__)`
- Use appropriate log levels: DEBUG, INFO, WARNING, ERROR

## CLI Patterns

### Argument Parsing

- Use `argparse` for command-line argument parsing
- Organize commands with subparsers when needed
- Provide clear help text and examples in epilog
- Use `argparse.RawDescriptionHelpFormatter` for formatted help

### CLI Workflow

1. Scan for devices
2. Activate a device to get activation code
3. Monitor/control/relay using device address and code

### Script Files

- Scripts in `scripts/` directory can use print statements
- More relaxed linting rules apply (see pyproject.toml per-file-ignores)
- Use shebang for bash scripts: `#!/usr/bin/env bash`

## Testing

### Test Structure

- Tests in `tests/` directory mirror main package structure
- Use `pytest` framework with `pytest-asyncio` for async tests
- Use fixtures in `conftest.py` for shared test setup
- Test file naming: `test_*.py`

### Test Conventions

- Relaxed linting rules for tests (assertions allowed, less strict annotations)
- Use descriptive test function names: `test_should_do_something_when_condition`
- Mock BLE operations for unit tests

## Dependencies

### Core Dependencies

- **bleak**: BLE communication library
- **pydantic**: Data validation and settings management

### Optional Dependencies

- **bless**: BLE server functionality (Linux only)
  - Installed with `poetry install --extras server`
  - Platform-specific marker: `sys_platform == 'linux'`

### Development Dependencies

- **ruff**: Linting and formatting
- **pyright**: Type checking
- **pytest**: Testing framework
- **commitizen**: Conventional commits

## Commit Convention

Use conventional commits format:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `style:` - Code style changes
- `refactor:` - Code refactoring
- `test:` - Test changes
- `chore:` - Build/tooling changes

## Common Pitfalls to Avoid

1. **Don't use Python 3.12+** - Project requires exactly 3.11
2. **Don't forget future annotations** - Add `from __future__ import annotations` to new files
3. **Don't use print in main code** - Use logging instead (print OK in scripts/)
4. **Don't use bare except** - Catch specific exceptions
5. **Don't forget type annotations** - Required by ruff rules
6. **Don't use old-style type hints** - Use `list[str]` not `List[str]`
7. **Don't ignore async** - BLE operations must be async
8. **Don't use single quotes** - Use double quotes for strings

## Protocol-Specific Notes

### iFit Protocol

- Message format: Header + Payload + Checksum
- Max 18 bytes per BLE message
- Response code 2 indicates success
- Protocol constants defined as IntEnum classes
- Equipment types: General (2), Treadmill (4)

### FTMS Protocol

- Standard Bluetooth Fitness Machine Service
- Server implementation in `ftms/` module
- Used for relaying iFit data to third-party apps

## Development Workflow

1. **Make changes** following style guidelines
2. **Format code**: `./scripts/format.sh`
3. **Check linting**: `./scripts/lint.sh`
4. **Run tests**: `./scripts/test.sh`
5. **Commit** using conventional commit messages

## When Generating New Code

- Start files with `from __future__ import annotations`
- Use `@dataclass` for data structures
- Use `IntEnum` for protocol constants
- Implement proper async patterns for BLE operations
- Add comprehensive type hints
- Include docstrings for public APIs
- Follow the established module structure (use `_` prefix for internal modules)
- Keep line length under 100 characters
- Use double quotes consistently
