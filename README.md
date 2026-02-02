# iFit BLE Client and FTMS Relay

A Python implementation of the iFit custom BLE protocol for communicating with iFit fitness equipment. This library provides a client for the proprietary iFit protocol and includes FTMS (Fitness Machine Service) relay functionality to bridge iFit equipment with standard fitness apps.

## Features

- BLE communication with iFit equipment
- FTMS (Fitness Machine Service) relay functionality
- Command-line interface for device interaction
- Monitor and discovery modes

## Installation

```bash
# Install with poetry
poetry install

# Install with server support
poetry install --extras server

# Install all extras
poetry install --extras all
```

## Usage

```bash
# Run the CLI
ifit --help
```

## Development

```bash
# First time setup
./scripts/setup.sh

# Activate virtual environment
poetry shell

# Run linters and type checks
./scripts/lint.sh

# Format code
./scripts/format.sh

# Run tests
./scripts/test.sh
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development guidelines.

## Documentation

See the [docs/](docs/) directory for detailed documentation:

- [User Guide](docs/USER_GUIDE.md) - Complete command reference and examples
- [iFit Protocol Structure](docs/IFIT_PROTOCOL.md) - Protocol documentation
- [FTMS Documentation](docs/FTMS.md) - FTMS relay implementation
- [Activation Discovery](docs/ACTIVATION_DISCOVERY.md) - Advanced activation code discovery

## Acknowledgments

This project builds upon the work of others in the fitness tech community:

- [zwifit](https://github.com/dawsontoth/zwifit) - For reverse engineering the iFit custom BLE protocol
- [qdomyos-zwift (QZ)](https://github.com/cagnulein/qdomyos-zwift) - For the comprehensive activation codes list

## License

MIT
