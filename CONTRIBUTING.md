# Contributing to Capivarex

Thank you for your interest in contributing to Capivarex! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Git
- A `.env` file (copy from `.env.example`)

### Getting Started

```bash
# Clone the repository
git clone https://github.com/cotah/bot_GOD.git
cd bot_GOD

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-asyncio pytest-cov ruff pip-audit

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Running the Application

```bash
# Development server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Production (Docker)
docker-compose -f docker-compose.prod.yml up --build
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Your Changes

- Follow the existing code style and architecture patterns
- Add docstrings to all public functions and classes
- Use type hints consistently

### 3. Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing

# Run specific test file
pytest tests/test_specific.py -v
```

### 4. Run the Linter

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .
```

### 5. Security Check

```bash
# Audit dependencies for known vulnerabilities
pip-audit -r requirements.txt
```

### 6. Submit a Pull Request

- Write a clear PR title and description
- Reference any related issues
- Ensure all CI checks pass
- Request review from maintainers

## Code Standards

### Architecture

The project follows a layered architecture:

```
api/           # FastAPI routes, middleware, dependencies
agents/        # AI agent implementations (orchestrator, weather, finance, etc.)
services/      # Business logic and external integrations
  core/        # Base service, registry, decorators
  business/    # Business logic services (chat, proactivity, etc.)
  infrastructure/  # Database, Redis, etc.
  integrations/    # External API wrappers (weather, finance, etc.)
models/        # Pydantic schemas and data models
utils/         # Utility functions
tests/         # Test suite
```

### Patterns

- **Service Registry**: All services are registered via `@register_service("name")` and retrieved via `get_service("name")`
- **Agent Registry**: All agents are registered via `@register_agent("name")` and retrieved via `get_agent("name")`
- **BaseService**: All services extend `BaseService` which provides retry, metrics, and health check capabilities
- **Strategy Pattern**: Used in ChatService for intent-to-agent dispatch

### Naming Conventions

- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Test files: `test_*.py`
- Test classes: `TestFeatureName`

### Docstrings

Use Google-style docstrings:

```python
def function_name(param1: str, param2: int) -> bool:
    """Short description of the function.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When param1 is empty.
    """
```

## Testing Guidelines

- Write tests for all new features and bug fixes
- Use `pytest` with `pytest-asyncio` for async tests
- Use `unittest.mock` for mocking external dependencies
- Maintain minimum 80% code coverage
- Place unit tests in `tests/` and integration tests in `tests/integration/`

## Questions?

If you have questions about contributing, please open a GitHub issue with the `question` label.
