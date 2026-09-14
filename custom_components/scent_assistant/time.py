"""Time entities for Scent Diffuser."""
from __future__ import annotations

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType
from .device import ScentDiffuserDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities."""
    device: ScentDiffuserDevice = hass.data[DOMAIN][entry.entry_id]
    if device.device_type == DeviceType.SCENTIMENT:
        return

    entities: list[TimeEntity] = [
        DiffuserStartTime(device, entry),
        DiffuserEndTime(device, entry),
    ]
    is_cloud = entry.data.get("connection_mode") == "cloud"
    if device.device_type == DeviceType.B501F and not is_cloud:
        for slot_no in range(1, 6):
            entities.append(B501FSlotStartTime(device, entry, slot_no))
            entities.append(B501FSlotEndTime(device, entry, slot_no))
    async_add_entities(entities)


class DiffuserStartTime(TimeEntity):
    """Start time for the daily spray schedule."""

    _attr_has_entity_name = True
    _attr_name = "Start Time"
    _attr_icon = "mdi:clock-start"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = f"{device.unique_id}_start_time"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.unique_id)},
        }
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def native_value(self) -> time | None:
        return time(self._device.state.start_hour, self._device.state.start_minute)

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_set_value(self, value: time) -> None:
        """Set the start time and write schedule to device."""
        self._device.state.start_hour = value.hour
        self._device.state.start_minute = value.minute
        await self._device.set_schedule(
            weekday_mask=0x7F,  # all days
            start_hour=value.hour,
            start_minute=value.minute,
            end_hour=self._device.state.end_hour,
            end_minute=self._device.state.end_minute,
            work_seconds=self._device.state.work_seconds or 10,
            pause_seconds=self._device.state.pause_seconds or 120,
        )


class DiffuserEndTime(TimeEntity):
    """End time for the daily spray schedule."""

    _attr_has_entity_name = True
    _attr_name = "End Time"
    _attr_icon = "mdi:clock-end"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = f"{device.unique_id}_end_time"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.unique_id)},
        }
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def native_value(self) -> time | None:
        return time(self._device.state.end_hour, self._device.state.end_minute)

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_set_value(self, value: time) -> None:
        """Set the end time and write schedule to device."""
        self._device.state.end_hour = value.hour
        self._device.state.end_minute = value.minute
        await self._device.set_schedule(
            weekday_mask=0x7F,  # all days
            start_hour=self._device.state.start_hour,
            start_minute=self._device.state.start_minute,
            end_hour=value.hour,
            end_minute=value.minute,
            work_seconds=self._device.state.work_seconds or 10,
            pause_seconds=self._device.state.pause_seconds or 120,
        )


# --- B501F per-slot time entities (start / end) ---------------------------

_B501F_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


def _b501f_slot(device: ScentDiffuserDevice, slot: int) -> dict | None:
    """Return the cached timer record for a B501F slot, or None."""
    timers = device.state.b501f_timers
    if timers and 1 <= slot <= len(timers):
        return timers[slot - 1]
    return None


class B501FSlotStartTime(TimeEntity):
    """Start time for one B501F timer slot's daily window.

    Writing it re-saves that slot's 16-byte record (CMD 0x14); the end
    time and burst durations of the same slot are preserved verbatim.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-start"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry, slot: int) -> None:
        self._device = device
        self._slot = slot
        self._attr_name = f"Slot {_B501F_ROMAN[slot]} Start Time"
        self._attr_unique_id = f"{device.unique_id}_slot_{slot}_start"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def native_value(self) -> time | None:
        rec = _b501f_slot(self._device, self._slot)
        if rec is None:
            return None
        mins = rec.get("start_minutes") or 0
        return time(mins // 60, mins % 60)

    @property
    def available(self) -> bool:
        return self._device.available and _b501f_slot(self._device, self._slot) is not None

    async def async_set_value(self, value: time) -> None:
        await self._device.set_slot_schedule(
            self._slot, start_minutes=value.hour * 60 + value.minute)


class B501FSlotEndTime(TimeEntity):
    """End time for one B501F timer slot's daily window."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-end"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry, slot: int) -> None:
        self._device = device
        self._slot = slot
        self._attr_name = f"Slot {_B501F_ROMAN[slot]} End Time"
        self._attr_unique_id = f"{device.unique_id}_slot_{slot}_end"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def native_value(self) -> time | None:
        rec = _b501f_slot(self._device, self._slot)
        if rec is None:
            return None
        mins = rec.get("stop_minutes") or 0
        return time(mins // 60, mins % 60)

    @property
    def available(self) -> bool:
        return self._device.available and _b501f_slot(self._device, self._slot) is not None

    async def async_set_value(self, value: time) -> None:
        await self._device.set_slot_schedule(
            self._slot, stop_minutes=value.hour * 60 + value.minute)
