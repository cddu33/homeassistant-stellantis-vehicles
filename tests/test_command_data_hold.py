"""Vehicle data received during a command is held, then dropped if the command fails."""
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles import base
from custom_components.stellantis_vehicles.base import StellantisVehicleCoordinator
from custom_components.stellantis_vehicles.const import DOMAIN

SENT_AT = datetime(2026, 11, 1, 17, 32, 53, tzinfo=UTC)


def _status(updated_at, plugged):
    return {
        "updatedAt": updated_at,
        "energies": [{
            "type": "Electric",
            "createdAt": updated_at,
            "extension": {"electric": {"charging": {"plugged": plugged, "status": "Disconnected"}}},
        }],
    }


def _plugged(data):
    return data["energies"][0]["extension"]["electric"]["charging"]["plugged"]


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self, date=None):
        return date if date is not None else self.now


@pytest.fixture
def clock():
    clock = Clock(SENT_AT)
    with patch.object(base, "get_datetime", clock):
        yield clock


@pytest.fixture
def coordinator(hass, clock):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    stellantis = MagicMock()
    stellantis.get_vehicle_maintenance = AsyncMock(return_value={})
    stellantis.send_mqtt_message = AsyncMock(return_value="action-1")
    coordinator = StellantisVehicleCoordinator(hass, {}, {"vin": "VIN1", "id": "1"}, stellantis, {}, entry)
    coordinator.after_async_update_data = AsyncMock()
    coordinator.data = _status("2026-11-01T17:00:00Z", False)
    return coordinator


async def _poll(coordinator, status):
    coordinator._stellantis.get_vehicle_status = AsyncMock(return_value=status)
    coordinator.data = await coordinator._async_update_data()


async def test_snapshot_from_failed_command_is_dropped(coordinator, clock):
    await coordinator.send_command("wakeup", "/VehCharge/state", {"action": "state"})

    # Partial wake-up snapshot arrives before the command's final status: held.
    clock.now = SENT_AT + timedelta(seconds=24)
    await _poll(coordinator, _status("2026-11-01T17:32:59Z", True))
    assert _plugged(coordinator.data) is False

    # 300 time out: the snapshot is dropped for good.
    clock.now = SENT_AT + timedelta(seconds=128)
    await coordinator.update_command_history("action-1", "300")
    clock.now = SENT_AT + timedelta(seconds=150)
    await _poll(coordinator, _status("2026-11-01T17:32:59Z", True))
    assert _plugged(coordinator.data) is False

    # A later snapshot, after the failed command, is applied again.
    await _poll(coordinator, _status("2026-11-01T17:40:00Z", True))
    assert _plugged(coordinator.data) is True


async def test_snapshot_from_successful_command_is_applied(coordinator, clock):
    await coordinator.send_command("wakeup", "/VehCharge/state", {"action": "state"})
    clock.now = SENT_AT + timedelta(seconds=24)
    await _poll(coordinator, _status("2026-11-01T17:32:59Z", True))
    assert _plugged(coordinator.data) is False

    await coordinator.update_command_history("action-1", "0")
    await _poll(coordinator, _status("2026-11-01T17:32:59Z", True))
    assert _plugged(coordinator.data) is True


async def test_snapshot_applied_once_hold_expires(coordinator, clock):
    await coordinator.send_command("wakeup", "/VehCharge/state", {"action": "state"})
    clock.now = SENT_AT + timedelta(seconds=181)
    await _poll(coordinator, _status("2026-11-01T17:32:59Z", True))
    assert _plugged(coordinator.data) is True


async def test_snapshot_older_than_command_is_applied(coordinator, clock):
    await coordinator.send_command("wakeup", "/VehCharge/state", {"action": "state"})
    await _poll(coordinator, _status("2026-11-01T17:20:00Z", True))
    assert _plugged(coordinator.data) is True


@pytest.mark.parametrize(("result", "applied"), [("0", True), ("300", False)])
async def test_mqtt_event_replayed_or_dropped(coordinator, clock, result, applied):
    await coordinator.send_command("wakeup", "/VehCharge/state", {"action": "state"})
    coordinator.apply_mqtt_event({"vin": "VIN1", "timestamp": "2026-11-01T17:32:55Z", "event_counter": 1})
    assert coordinator._mqtt_state == {}
    assert len(coordinator._held_mqtt_events) == 1

    clock.now = SENT_AT + timedelta(seconds=128)
    await coordinator.update_command_history("action-1", result)
    assert coordinator._held_mqtt_events == []
    assert (coordinator._mqtt_state != {}) is applied
