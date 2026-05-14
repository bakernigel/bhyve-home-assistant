"""BHyve irrigation timer calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIENT,
    CONF_DEVICES,
    DEVICE_BRIDGE,
    DOMAIN,
)
from .pybhyve.client import BHyveClient

from .pybhyve.typings import (
    BHyveDevice,
    BHyveTimerProgram,
)

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .util import orbit_time_to_local_time

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BHyve calendar entities."""

    bhyve: BHyveClient = hass.data[DOMAIN][entry.entry_id][CONF_CLIENT]
    
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    devices = await bhyve.devices
    programs = await bhyve.timer_programs

    configured_devices = entry.options.get(CONF_DEVICES, [])

    valid_devices = [
        d for d in devices
        if str(d.get("id")) in configured_devices
        and d.get("type") != DEVICE_BRIDGE
    ]

    device_by_id = {
        d.get("id"): d for d in valid_devices
    }

    calendars: list[BhyveCalendarEntity] = []

    for program in programs:
        device = device_by_id.get(program.get("device_id"))

        if device is None:
            continue

        if program.get("program") is None:
            continue

        calendars.append(
            BhyveCalendarEntity(
                coordinator,
                hass,
                bhyve,
                device,
                program,
            )
        )

    async_add_entities(calendars)

class BhyveCalendarEntity(CoordinatorEntity, CalendarEntity):
    """Representation of a BHyve calendar entity."""

    _attr_has_entity_name = True
    
    def __init__(
        self,
        coordinator,
        hass: HomeAssistant,
        bhyve: BHyveClient,
        device: BHyveDevice,
        program: BHyveTimerProgram,
    ) -> None:    
    
    
        """Initialize calendar entity."""
        
        super().__init__(coordinator)
    
        self.hass = hass
        self._bhyve = bhyve
        self._device = device
        self._program = program
    
        self._program_id = program.get("id")
    
        device_name = device.get("name", "Unknown Device")
        program_name = program.get("name", "Unknown Program")
    
        self._attr_name = f"{device_name} {program_name} Calendar"
    
        self._attr_unique_id = (
            f"bhyve_calendar_{self._program_id}"
        )
    
        self._attr_has_entity_name = True
    
        self._device_status = device.get("status", {})
    
        self._delay_start = self._device_status.get(
            "rain_delay_started_at"
        )
    
        self._delay_hours = self._device_status.get(
            "rain_delay",
            0,
        )
        
    @property
    def event(self) -> CalendarEvent | None:
        """Return next upcoming event."""

        events = self._build_events(
            dt_util.now(),
            dt_util.now() + timedelta(days=60),
        )

        return events[0] if events else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events."""
        return self._build_events(start_date, end_date)

    def _build_events(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Build event list."""

        events: list[CalendarEvent] = []

        if not self._program.get("enabled"):
            return events

        frequency = self._program.get("frequency")

        if not frequency:
            return events

        interval = frequency.get("interval")

        if not interval:
            return events

        interval_start_time = orbit_time_to_local_time(
            frequency.get("interval_start_time")
        )

        if interval_start_time is None:
            return events

        current = interval_start_time

        rain_delay_start = None
        rain_delay_end = None

        if self._delay_start:
            rain_delay_start = orbit_time_to_local_time(
                self._delay_start
            )

            if rain_delay_start:
                rain_delay_end = rain_delay_start + timedelta(
                    hours=self._delay_hours
                )

        while current <= end_date:
            if current >= start_date:

                skip_event = False

                if rain_delay_start and rain_delay_end:
                    if rain_delay_start <= current <= rain_delay_end:
                        skip_event = True

                if not skip_event:
                    event = CalendarEvent(
                        summary=self._program.get(
                            "name",
                            "BHyve Program",
                        ),
                        start=current.date(),
                        end=current.date() + timedelta(days=1),
#                        end=current + timedelta(hours=1),
                        uid=f"{self._program_id}_{current.isoformat()}",
                    )

                    events.append(event)

            current += timedelta(days=interval)

        return events

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete event."""
        return None
        
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
    
        programs = self.coordinator.data.get("programs", {})
    
        updated_program = programs.get(self._program_id)
    
        if updated_program:
            self._program = updated_program
    
        devices = self.coordinator.data.get("devices", {})
    
        updated_device = devices.get(self._device.get("id"))
    
        if updated_device:
            self._device = updated_device.get("device", self._device)
    
            self._device_status = self._device.get("status", {})
    
            self._delay_start = self._device_status.get(
                "rain_delay_started_at"
            )
    
            self._delay_hours = self._device_status.get(
                "rain_delay",
                0,
            )
    
        self.async_write_ha_state()        
            
