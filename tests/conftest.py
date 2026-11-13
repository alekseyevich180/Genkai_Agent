"""Repository-wide pytest tier registration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    for marker in (
        "unit: isolated deterministic test",
        "contract: artifact or API contract test",
        "integration: offline multi-component test",
        "compatibility: legacy entrypoint compatibility test",
        "external: requires external runtime or network and is opt-in",
    ):
        config.addinivalue_line("markers", marker)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply one canonical tier marker from the test directory layout."""
    tier_by_directory = {
        "contracts": "contract",
        "architecture": "contract",
        "modeling": "unit",
        "literature": "unit",
        "mlip": "unit",
        "integrations": "integration",
        "workflow": "integration",
        "packaging": "integration",
        "compatibility": "compatibility",
        "external": "external",
    }
    for item in items:
        parts = item.path.parts
        for directory, marker in tier_by_directory.items():
            if directory in parts:
                item.add_marker(marker)
                break
