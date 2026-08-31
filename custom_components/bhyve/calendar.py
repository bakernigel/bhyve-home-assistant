"""BHyve irrigation timer calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
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
        device
        for device in devices
        if str(device.get("id")) in configured_devices
        and device.get("type") != DEVICE_BRIDGE
    ]

    device_by_id = {
        device.get("id"): device
        for device in valid_devices
    }

    calendars: list[BHyveCalendarEntity] = []

    for program in programs:
        device = device_by_id.get(program.get("device_id"))

        if device is None:
            continue

        if program.get("program") is None:
            continue

        calendars.append(
            BHyveCalendarEntity(
                coordinator,
                hass,
                bhyve,
                device,
                program,
            )
        )

    async_add_entities(calendars)


class BHyveCalendarEntity(CoordinatorEntity, CalendarEntity):
    """Representation of a BHyve irrigation program calendar."""

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

        self._device_id = device.get("id")
        self._program_id = program.get("id")

        device_name = device.get("name", "Unknown Device")
        program_name = program.get("name", "Unknown Program")

        self._attr_name = f"{device_name} {program_name} Calendar"
        self._attr_unique_id = f"bhyve_calendar_{self._program_id}"

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
        """Return the current or next upcoming event."""

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
        """Return calendar events in the requested range."""

        return self._build_events(start_date, end_date)

    def _build_events(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Build calendar event list."""

        events: list[CalendarEvent] = []

        if not self._program.get("enabled"):
            return events

        if not self._program.get("program"):
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

        #
        # Rain delay
        #
        # B-hyve reports "rain_delay" as the number of hours REMAINING,
        # not the original duration of the delay.
        #
        rain_delay_start = None
        rain_delay_end = None

        try:
            remaining_hours = int(self._delay_hours or 0)
        except (TypeError, ValueError):
            remaining_hours = 0

        if remaining_hours > 0:
            if self._delay_start:
                rain_delay_start = orbit_time_to_local_time(
                    self._delay_start
                )

            #
            # The delay value is remaining time, therefore:
            #
            #     END = NOW + remaining hours
            #
            # Do not calculate:
            #
            #     START + remaining hours
            #
            rain_delay_end = dt_util.now() + timedelta(
                hours=remaining_hours
            )

        current = interval_start_time

        while current <= end_date:
            if current >= start_date:
                skip_event = False

                #
                # Calendar entries are intentionally all-day events.
                #
                # A scheduled irrigation event should therefore disappear
                # from the calendar if that calendar date falls within the
                # active rain-delay date range.
                #
                if rain_delay_start and rain_delay_end:
                    current_local = dt_util.as_local(current)

                    if (
                        rain_delay_start.date()
                        <= current_local.date()
                        <= rain_delay_end.date()
                    ):
                        skip_event = True

                        _LOGGER.debug(
                            "Skipping calendar event %s for program %s "
                            "due to rain delay %s - %s",
                            current_local.date(),
                            self._program.get("name", "Unknown Program"),
                            rain_delay_start,
                            rain_delay_end,
                        )

                if not skip_event:
                    event_date = current.date()

                    events.append(
                        CalendarEvent(
                            summary=self._program.get(
                                "name",
                                "BHyve Program",
                            ),
                            start=event_date,
                            end=event_date + timedelta(days=1),
                            description=self._program.get(
                                "name",
                                "BHyve Program",
                            ),
                            location="Home",
                            uid=(
                                f"{self._program_id}/"
                                f"{event_date.isoformat()}"
                            ),
                        )
                    )

            current += timedelta(days=interval)

        return events

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Calendar events are read-only."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the BHyve coordinator."""

        #
        # coordinator.data["programs"] is a dictionary keyed by program ID.
        #
        programs: dict[str, Any] = self.coordinator.data.get(
            "programs",
            {},
        )

        updated_program = programs.get(self._program_id)

        if updated_program is not None:
            self._program = updated_program

        #
        # coordinator.data["devices"] is a dictionary keyed by device ID.
        #
        # Each entry contains:
        #
        # {
        #     "device": {...},
        #     ...
        # }
        #
        devices: dict[str, Any] = self.coordinator.data.get(
            "devices",
            {},
        )

        updated_device_data = devices.get(self._device_id)

        if updated_device_data is not None:
            updated_device = updated_device_data.get("device")

            if updated_device is not None:
                self._device = updated_device

                self._device_status = self._device.get(
                    "status",
                    {},
                )

                self._delay_start = self._device_status.get(
                    "rain_delay_started_at"
                )

                self._delay_hours = self._device_status.get(
                    "rain_delay",
                    0,
                )

        _LOGGER.debug(
            "Calendar coordinator update: program=%s "
            "rain_delay_started_at=%s rain_delay_remaining=%s",
            self._program_id,
            self._delay_start,
            self._delay_hours,
        )

        self.async_write_ha_state()