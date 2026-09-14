"""Switch entities for Scent Diffuser."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType
from .device import ScentDiffuserDevice

_LOGGER = logging.getLogger(__name__)

SCENT_MARKETING_TYPES = {
    DeviceType.SCENT_MARKETING_AK,
    DeviceType.SCENT_MARKETING_GW,
    DeviceType.SCENT_MARKETING_GW_XOR,
    DeviceType.B501F,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    device: ScentDiffuserDevice = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = [DiffuserPowerSwitch(device, entry)]

    is_cloud = entry.data.get("connection_mode") == "cloud"
    if device.supports_fan and not is_cloud:
        entities.append(DiffuserFanSwitch(device, entry))

    # B501F: one independent switch per firmware timer slot (I-V).
    # Maps 1:1 to the app's 5 mode buttons — the firmware has no
    # "exclusive mode" concept, so slots can coexist (weekend vs weekday).
    # See `B501FSlotSwitch` below.
    if device.device_type == DeviceType.B501F and not is_cloud:
        for slot_no in range(1, 6):
            entities.append(B501FSlotSwitch(device, entry, slot_no))

    # Scent Marketing devices expose extra controls when running on BLE.
    if device.device_type in SCENT_MARKETING_TYPES and not is_cloud:
        entities.append(DiffuserLockSwitch(device, entry))
        if device.device_type == DeviceType.SCENT_MARKETING_AK:
            # The AK control bitmask carries a lamp bit we can drive
            # without any extra protocol work. (The fan switch is already
            # added above via `device.supports_fan`, which is True for AK —
            # appending it here too would register a second entity with the
            # same `_fan` unique_id and HA would reject the duplicate.)
            entities.append(DiffuserLampSwitch(device, entry))
            # V3 AK devices have a separate program-enabled toggle that
            # is distinct from Power. We register the entity for every
            # AK device but make it unavailable on V2 (where it would
            # just duplicate Power) — `available` checks `protocol.is_v3`
            # which only resolves after the first BLE login.
            entities.append(DiffuserScheduleSwitch(device, entry))

    async_add_entities(entities)


class DiffuserPowerSwitch(SwitchEntity):
    """Power on/off switch for the diffuser."""

    _attr_has_entity_name = True
    _attr_name = "Power"
    _attr_icon = "mdi:power"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = f"{device.unique_id}_power"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.power

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_turn_on(self, **kwargs) -> None:
        await self._device.set_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._device.set_power(False)


class DiffuserLockSwitch(SwitchEntity):
    """Child-lock switch (Scent Marketing devices)."""

    _attr_has_entity_name = True
    _attr_name = "Child lock"
    _attr_icon = "mdi:lock"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = f"{device.unique_id}_lock"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.lock

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_turn_on(self, **kwargs) -> None:
        await self._device.set_lock(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._device.set_lock(False)


class DiffuserScheduleSwitch(SwitchEntity):
    """Program / schedule enabled switch (Scent Marketing AK V3 only).

    On V3 devices the program-enabled flag is independent of Power and
    Fan — a diffuser can be powered on with the program disabled, in
    which case it won't spray. On V2 devices the equivalent state is
    already covered by the Power switch, so this entity stays
    unavailable on V2 hardware.
    """

    _attr_has_entity_name = True
    _attr_name = "Program"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = f"{device.unique_id}_schedule"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.schedule_enabled

    @property
    def available(self) -> bool:
        # V3-only: V2 devices have no separate program toggle.
        return self._device.available and self._device.protocol_is_v3

    async def async_turn_on(self, **kwargs) -> None:
        await self._device.set_schedule_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._device.set_schedule_enabled(False)


class DiffuserLampSwitch(SwitchEntity):
    """Auxiliary LED / lamp switch (Scent Marketing AK family)."""

    _attr_has_entity_name = True
    _attr_name = "Lamp"
    _attr_icon = "mdi:lightbulb"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = f"{device.unique_id}_lamp"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.light_on

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_turn_on(self, **kwargs) -> None:
        await self._device.set_lamp(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._device.set_lamp(False)


class DiffuserFanSwitch(SwitchEntity):
    """Fan on/off switch (Aroma-Link only, requires Bluetooth)."""

    _attr_has_entity_name = True
    _attr_name = "Fan"
    _attr_icon = "mdi:fan"

    def __init__(self, device: ScentDiffuserDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._is_cloud_only = entry.data.get("connection_mode") == "cloud"
        self._attr_unique_id = f"{device.unique_id}_fan"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.fan

    @property
    def available(self) -> bool:
        if self._is_cloud_only:
            return False
        return self._device.connection_mode == "ble"

    @property
    def extra_state_attributes(self) -> dict:
        if self._is_cloud_only:
            return {"note": "Fan control requires Bluetooth connection"}
        return {}

    async def async_turn_on(self, **kwargs) -> None:
        await self._device.set_fan(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._device.set_fan(False)


ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


class B501FSlotSwitch(SwitchEntity):
    """One independent timer-slot switch (I-V) for B501F / Scent Tech.

    Mirrors the Scent Tech app's five mode buttons: turning a slot ON
    enables it on the firmware (CMD 0x14, its other fields preserved)
    and turning it OFF disables just that slot. Slots coexist — e.g.
    slot I at 19:00-22:00 on weekdays and slot II at a different window
    on weekends — so each switch is independent. Which slot the
    Work/Pause/Start/End entities edit is still chosen by the
    "Active mode" select.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, device: ScentDiffuserDevice, entry: ConfigEntry, slot: int
    ) -> None:
        self._slot = slot
        self._device = device
        self._attr_name = f"Timer slot {ROMAN[slot]}"
        self._attr_unique_id = f"{device.unique_id}_slot_{slot}"
        self._attr_device_info = device.device_info
        device.register_state_callback(self._on_state_update)

    def _on_state_update(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        timers = self._device.state.b501f_timers
        if not timers or self._slot > len(timers):
            return None
        return bool(timers[self._slot - 1].get("enabled"))

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def extra_state_attributes(self) -> dict:
        timers = self._device.state.b501f_timers
        if not timers or self._slot > len(timers):
            return {}
        s = timers[self._slot - 1]
        attrs = {}
        if s.get("start_minutes") is not None:
            attrs["window"] = (
                f"{s['start_minutes'] // 60:02d}:"
                f"{s['start_minutes'] % 60:02d}-"
                f"{s.get('stop_minutes', 0) // 60:02d}:"
                f"{s.get('stop_minutes', 0) % 60:02d}"
            )
        if s.get("run_seconds") is not None:
            attrs["burst"] = f"{s['run_seconds']}s on / {s.get('pause_seconds', '?')}s off"
        return attrs

    async def async_turn_on(self, **kwargs) -> None:
        if not await self._device.set_slot_enabled(self._slot, True):
            raise ValueError(
                f"B501F slot {self._slot} enable failed on {self._device.name}"
            )

    async def async_turn_off(self, **kwargs) -> None:
        if not await self._device.set_slot_enabled(self._slot, False):
            raise ValueError(
                f"B501F slot {self._slot} disable failed on {self._device.name}"
            )
