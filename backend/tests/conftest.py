import pytest

from app.core.policy_schema import load_policies
from app.core.settings import get_settings
from app.policies.service import PolicyManager
from app.storage.registry import create_storages


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def policy_manager():
    settings = get_settings()
    return PolicyManager(
        load_policies(settings.policies_path), create_storages(settings)
    )
