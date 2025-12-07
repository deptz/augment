# Contributing to Documentation Backfill

Thank you for your interest in contributing to this project! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a code of conduct that all contributors are expected to follow. Please be respectful and constructive in all interactions.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue with:
- A clear, descriptive title
- Steps to reproduce the issue
- Expected vs. actual behavior
- Environment details (Python version, OS, etc.)
- Any relevant error messages or logs

### Suggesting Features

Feature suggestions are welcome! Please open an issue with:
- A clear description of the proposed feature
- Use cases and examples
- Any potential implementation considerations

### Submitting Pull Requests

1. **Fork the repository** and clone your fork
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** following our coding standards
4. **Add or update tests** as needed
5. **Ensure all tests pass**:
   ```bash
   pytest
   ```
6. **Update documentation** if you've changed functionality
7. **Commit your changes** with clear, descriptive commit messages:
   ```bash
   git commit -m "Add feature: description of your feature"
   ```
8. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```
9. **Open a Pull Request** with a clear description of your changes

## Development Setup

### Prerequisites

- Python 3.10 or higher
- pip or poetry for dependency management
- Git

### Setup Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/deptz/augment.git
   cd augment
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Install development dependencies**:
   ```bash
   pip install pytest pytest-mock
   ```

5. **Copy environment template**:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your configuration (you can use dummy values for testing)

6. **Run tests**:
   ```bash
   pytest
   ```

## Coding Standards

### Python Style

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Use type hints where appropriate
- Keep functions focused and single-purpose
- Write docstrings for all public functions and classes

### Code Formatting

We recommend using:
- `black` for code formatting
- `flake8` or `pylint` for linting
- `mypy` for type checking (optional)

### Commit Messages

Write clear, descriptive commit messages:
- Use the imperative mood ("Add feature" not "Added feature")
- Keep the first line under 50 characters
- Add more detail in the body if needed
- Reference issue numbers when applicable

Example:
```
Add support for custom LLM providers

- Implemented provider abstraction layer
- Added configuration for new providers
- Updated documentation

Fixes #123
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_generator.py

# Run with verbose output
pytest -v
```

### Writing Tests

- Write tests for new features
- Ensure tests are isolated and don't depend on external services
- Use mocks for API calls
- Aim for good test coverage, especially for critical paths

## Documentation

### Code Documentation

- Add docstrings to all public functions and classes
- Use Google-style docstrings
- Document parameters, return values, and exceptions

### README Updates

- Update README.md if you've added features or changed setup
- Keep examples up to date
- Add new sections if needed

## Project Structure

```
augment/
├── src/              # Source code
├── api/              # API server code
├── tests/            # Test files
├── docs/             # Additional documentation
├── config.yaml       # Configuration template
├── requirements.txt  # Python dependencies
└── README.md         # Main documentation
```

## Review Process

1. All pull requests require at least one review
2. Maintainers will review for:
   - Code quality and style
   - Test coverage
   - Documentation updates
   - Backward compatibility
3. Address any feedback before merging
4. Once approved, a maintainer will merge your PR

## Questions?

If you have questions about contributing, please:
- Open an issue with the `question` label
- Check existing issues and discussions
- Reach out to maintainers

Thank you for contributing!

