"""A vehicle clock that goes back (e.g. no GPS time, falling back to 2023) must not freeze the data."""
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.base import StellantisVehicleCoordinator
from custom_components.stellantis_vehicles.const import DOMAIN


def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return StellantisVehicleCoordinator(hass, {}, {"vin": "VIN1", "id": "1"}, MagicMock(), {}, entry)


async def test_rest_clock_reset_is_not_stale(hass):
    coordinator = _coordinator(hass)
    coordinator.data = {"updatedAt": "2026-11-12T10:00:00Z"}
    assert coordinator._is_stale({"updatedAt": "2026-11-12T10:00:00Z"})
    assert coordinator._is_stale({"updatedAt": "2026-11-12T09:59:00Z"})
    # Clock reset: accepted instead of skipped on every poll.
    assert not coordinator._is_stale({"updatedAt": "2023-01-01T00:05:00Z"})

    coordinator.data = {"updatedAt": "2023-01-01T00:05:00Z"}
    assert not coordinator._is_stale({"updatedAt": "2023-01-01T00:06:00Z"})
    # Clock set right again.
    assert not coordinator._is_stale({"updatedAt": "2026-11-12T10:10:00Z"})


async def test_mqtt_clock_reset_is_accepted(hass):
    coordinator = _coordinator(hass)

    def accept(timestamp, counter):
        return coordinator._accept_mqtt_event_order({"timestamp": timestamp, "event_counter": counter})

    assert accept("2026-11-12T10:00:00Z", 5)
    # Ordinary out-of-order event: still dropped.
    assert not accept("2026-11-12T09:59:59Z", 4)
    # Clock reset: the sequence restarts from it.
    assert accept("2023-01-01T00:00:10Z", 1)
    assert accept("2023-01-01T00:00:20Z", 2)
    assert not accept("2023-01-01T00:00:15Z", 3)
    assert accept("2026-11-12T10:05:00Z", 1)
