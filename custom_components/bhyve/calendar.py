""" Bhyve irrigation timer calendar."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from custom_components.bhyve.pybhyve.client import BHyveClient
from . import BHyveDeviceEntity, BHyveWebsocketEntity
from custom_components.bhyve.pybhyve.typings import (
    BHyveDevice,
    BHyveTimerProgram,
    BHyveZone,
)

from .util import filter_configured_devices, orbit_time_to_local_time

from .const import (
    CONF_CLIENT,
    DEVICE_SPRINKLER,
    DOMAIN,
    EVENT_CHANGE_MODE,
    EVENT_DEVICE_IDLE,
    EVENT_PROGRAM_CHANGED,
    EVENT_RAIN_DELAY,
    EVENT_SET_MANUAL_PRESET_TIME,
    EVENT_WATERING_COMPLETE,
    EVENT_WATERING_IN_PROGRESS,
    SIGNAL_UPDATE_PROGRAM,
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:

    bhyve = hass.data[DOMAIN][entry.entry_id][CONF_CLIENT]
    
    devices = filter_configured_devices(entry, await bhyve.devices)
    
    programs = await bhyve.timer_programs
    device_by_id = {}
    calendars = []
    
    for device in devices:
        device_id = device.get("id")
        device_by_id[device_id] = device
        for program in programs:
            program_device = device_by_id.get(program.get("device_id"))
            program_id = program.get("program")
            if program_device is not None and program_id is not None:        
                _LOGGER.debug("Creating calendar: Device:%s Program %s", device, program)
                calendars.append(BhyveCalendarEntity(hass, bhyve, device, program))                    
            
    async_add_entities(calendars, True)

class BhyveCalendarEntity(BHyveWebsocketEntity, CalendarEntity):
    """  Bhyve irrigation calendar entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        bhyve: BHyveClient,
        device: BHyveDevice,
        program: BHyveTimerProgram,       
    ) -> None:    
        """Initialize a  calendar entity."""
 
        device_name = device.get("name", "Unknown switch")
        program_name = program.get("name", "unknown")       
        _LOGGER.debug("Initialize a  calendar entity: Device:%s Program %s", device_name, program)
       
        name = f"{device_name} {program_name} calendar"
        
        super().__init__(hass, bhyve, device, name, "calendar")
        
        self._available = True       
        self._program = program
        self._device_id = program.get("device_id")
        self._program_id = program.get("id") 

        self._event: CalendarEvent | None = None
        
    @property
    def unique_id(self) -> str:
        """Return the unique id for the calendar program."""
        return f"bhyve:calendar:{self._program_id}"        

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        return None


    def _handle_upcoming_event(self) -> dict[str, Any] | None:
        """Handle current or next event."""
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
    
        event_list: list[CalendarEvent] = []

        if program_name := self._program.get("program"):
            full_program_name = self._program.get("name", "unknown")
            frequency = self._program.get("frequency")
            interval = frequency.get("interval")
            interval_start_time = frequency.get("interval_start_time")
                           
            start_date_time = orbit_time_to_local_time(interval_start_time)
            event_start = start_date_time.date()
            end_date_time = start_date_time + timedelta(days=1)
            event_end = end_date_time.date()
            
            
            _LOGGER.debug("Raw Event list. program_name:%s full_program_name:%s interval:%s interval_start_time:%s DATE: %s", 
              program_name,
              full_program_name, 
              interval,
              interval_start_time,
              event_start,
            )
            
            event = CalendarEvent(
                summary=full_program_name,
                start=event_start,
                end=event_end,
                description=full_program_name,
                location="Home",
                uid=f"{program_name}/{interval_start_time}",
            )
            
            _LOGGER.debug("First Event :%s", event)
            
#                event_list.append(event)  Event is not needed for start date if it is in the future. It will be added below. What if in the past ?
            
            # Now fill the calendar with all events for the next 60 days.
            threshold_date = dt_util.now() + timedelta(days=60)

            current_date_time = start_date_time
            while current_date_time <= threshold_date:
                event_start = current_date_time.date()
                event_end = (current_date_time + timedelta(days=1)).date()
                event = CalendarEvent(
                    summary=full_program_name,
                    start=event_start,
                    end=event_end,
                    description=full_program_name,
                    location="Home",
                    uid=f"{program_name}/{event_start}",
                )
                event_list.append(event)
                current_date_time += timedelta(days=interval)
            
            # Log if the loop was terminated due to exceeding threshold
            if current_date_time > threshold_date:
                _LOGGER.debug("Stopped at %s for program: %s", current_date_time, full_program_name)

        _LOGGER.debug("async_get_events Event List:%s", event_list)
        
        return event_list

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
    
        return None
        
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        _LOGGER.debug(
                "Calendar async_added_to_hass",
        )        

        @callback
        def update(_device_id: str, data: dict) -> None:
            """Update the state."""
            _LOGGER.debug(
                "Calendar Program update: %s - %s - %s", self.name, self._program_id, str(data)
            )
            event = data.get("event")
            if event == EVENT_PROGRAM_CHANGED:
                self._ws_unprocessed_events.append(data)
                self.async_schedule_update_ha_state(True)  # noqa: FBT003

        self._async_unsub_dispatcher_connect = async_dispatcher_connect(
            self.hass, SIGNAL_UPDATE_PROGRAM.format(self._program_id), update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect dispatcher listener when removed."""
        if self._async_unsub_dispatcher_connect:
            self._async_unsub_dispatcher_connect()

    def _on_ws_data(self, data: dict) -> None:
        #
        # {'event': 'program_changed' }  # noqa: ERA001
        #
        _LOGGER.debug("Calendar _on_ws_data Received program data update %s", data)

        event = data.get("event")
        if event is None:
            _LOGGER.warning("No event on ws data %s", data)
            return

        if event == EVENT_PROGRAM_CHANGED:
            program = data.get("program")
            if program is not None:
                self._program = program

    def _should_handle_event(self, event_name: str, _data: dict) -> bool:
        _LOGGER.debug("Calendar _should_handle_event")
        return event_name in [EVENT_PROGRAM_CHANGED]
        
