""" Bhyve irrigation timer calendar."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.exceptions import (
    HomeAssistantError,
)

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
    SIGNAL_UPDATE_DEVICE,
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

class BhyveCalendarEntity(BHyveDeviceEntity, CalendarEntity):
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
        
        self._device_status = device.get("status", {})
        self._delay_start = self._device_status.get("rain_delay_started_at", "")
        self._delay_hours = self._device_status.get("rain_delay", 0)
        
        _LOGGER.debug("Init Calendar entity: Device:%s Program:%s Rain Delay:%s", self._device_id, program, self._device_status )
        
    @property
    def unique_id(self) -> str:
        """Return the unique id for the calendar program."""
        return f"bhyve:calendar:{self._program_id}"        

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        
        if not self._program.get("enabled"):
            _LOGGER.info(
                            "Skipping next event for disabled program %s",
                            self._program.get("name", "unknown"),
            )
            return
                    
        now = dt_util.now()
        earliest_event = None
        earliest_start_time = None

        program = self._program
        if not program.get("program"):
            return None

        program_name = program.get("name", "unknown")
        frequency = program.get("frequency")
        interval = frequency.get("interval")
        interval_start_time = orbit_time_to_local_time(frequency.get("interval_start_time"))

        # Find the next or current event for this program
        current_time = now
        while interval_start_time <= current_time + timedelta(days=60):
            event_start = interval_start_time
            event_end = interval_start_time + timedelta(days=1)

            # Check if the event is current or upcoming
            if event_start <= current_time < event_end:
                # Current event
                event = CalendarEvent(
                    summary=program_name,
                    start=event_start.date(),
                    end=event_end.date(),
                    description=program_name,
                    location="Home",
                    uid=f"{program.get('program')}/{event_start}",
                )
                return event  # Return the current event immediately
            elif event_start > current_time:
                # Upcoming event
                if earliest_start_time is None or event_start < earliest_start_time:
                    earliest_start_time = event_start
                    earliest_event = CalendarEvent(
                        summary=program_name,
                        start=event_start.date(),
                        end=event_end.date(),
                        description=program_name,
                        location="Home",
                        uid=f"{program.get('program')}/{event_start}",
                    )

            interval_start_time += timedelta(days=interval)

        return earliest_event  # Return the next upcoming event, or None if no events are found


    def _handle_upcoming_event(self) -> dict[str, Any] | None:
        """Handle current or next event."""
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:

        event_list: list[CalendarEvent] = []
        if not self._program.get("enabled"):
            _LOGGER.info(
                            "Skipping events for disabled program %s",
                            self._program.get("name", "unknown"),
            )
            return event_list
    
        if program_name := self._program.get("program"):
            full_program_name = self._program.get("name", "unknown")
            frequency = self._program.get("frequency")
            interval = frequency.get("interval")
            interval_start_time = frequency.get("interval_start_time")
                               
            start_date_time = orbit_time_to_local_time(interval_start_time)
            
            # Rain delay details
            
            rain_delay = self._device_status
            rain_delay_start = None
            rain_delay_end = None
            if rain_delay:
                rain_delay_start = orbit_time_to_local_time(self._delay_start)
                if rain_delay_start:
                    delay_hours = self._delay_hours
                    rain_delay_end = rain_delay_start + timedelta(hours=delay_hours)
    
            # Now fill the calendar with all events for the next 60 days
            threshold_date = dt_util.now() + timedelta(days=60)
            current_date_time = start_date_time
            while current_date_time <= threshold_date:
                event_start = current_date_time.date()
                event_end = (current_date_time + timedelta(days=1)).date()
    
                # Check if event falls within rain delay period
                skip_event = False
                if rain_delay_start and rain_delay_end:
                    event_datetime = dt_util.as_local(current_date_time)
                    if rain_delay_start.date() <= event_datetime.date() <= rain_delay_end.date():
                        skip_event = True
                        _LOGGER.warning(
                            "Skipping event on %s for program %s due to rain delay from %s to %s",
                            event_start, full_program_name, rain_delay_start, rain_delay_end
                        )
    
                if not skip_event:
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

    def _on_ws_data(self, data: dict) -> None:
        #
        # {'event': 'program_changed' }  # noqa: ERA001
        #

        event = data.get("event")
        if event is None:
            _LOGGER.warning("No event on ws data %s", data)
            return

        if event == EVENT_PROGRAM_CHANGED:
            _LOGGER.debug("Calendar EVENT_PROGRAM_CHANGED %s", data)
            program = data.get("program")
            if program is not None:
                if self._program_id == program.get("id"):               
                    self._program = program
                
        if event == EVENT_RAIN_DELAY:
            _LOGGER.debug("Calendar EVENT_RAIN_DELAY %s", data)
            self._delay_start = data.get("timestamp", "")
            self._delay_hours = data.get("delay", 0)                            

    def _should_handle_event(self, event_name: str, _data: dict) -> bool:
        return event_name in [EVENT_PROGRAM_CHANGED, EVENT_RAIN_DELAY,]

        
