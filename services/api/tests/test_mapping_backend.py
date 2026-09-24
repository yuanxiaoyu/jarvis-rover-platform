import pytest

from app.models.mapping import MappingState
from app.services.mapping_backend import InMemoryMappingBackend, UnavailableMappingBackend


@pytest.mark.anyio
async def test_unavailable_backend_is_fail_closed():
    backend = UnavailableMappingBackend()
    status = await backend.status()
    assert status.state is MappingState.ERROR_RECOVERABLE
    assert status.ready is False
    assert status.motion_allowed is False
    result = await backend.start("session-1")
    assert result.accepted is False
    assert result.state is MappingState.ERROR_RECOVERABLE


@pytest.mark.anyio
async def test_in_memory_backend_is_only_an_explicit_test_backend():
    backend = InMemoryMappingBackend()
    result = await backend.start("session-1")
    assert result.accepted is True
    assert (await backend.status()).state is MappingState.STARTING
