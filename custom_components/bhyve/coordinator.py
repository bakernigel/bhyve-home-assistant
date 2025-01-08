"""DataUpdateCoordinator for BHyve."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER
from .pybhyve.typings import BHyveApiData

DEFAULT_RECONNECT_TIME = 2  # Define a default reconnect time

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import BHyveConfigEntry
    from .pybhyve.client import BHyveClient


class BHyveUpdateCoordinator(DataUpdateCoordinator[BHyveApiData]):
    """Class to manage fetching data from the API."""

    config_entry: BHyveConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BHyveConfigEntry,
        api: BHyveClient,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=DOMAIN,
            always_update=False,
        )
        self.config_entry = entry
        self.api = api

        self.monitor_connected: bool = False

    async def _async_setup(self) -> None:
        self._shutdown_remove_listener = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_shutdown
        )

        return await super()._async_setup()

    async def _async_shutdown(self, _event: Any) -> None:
        """Call from Homeassistant shutdown event."""
        # unset remove listener otherwise calling it would raise an exception
        self._shutdown_remove_listener = None
        await self.async_unload()

    async def async_unload(self) -> None:
        """Stop the update monitor."""
        if self._shutdown_remove_listener:
            self._shutdown_remove_listener()

        await self.api.stop()
        self.monitor_connected = False

    async def _async_update_data(self) -> BHyveApiData:
        """Fetch data from the API."""
        try:
            LOGGER.debug("***** FETCHING BHYVE DATA *****")
            data = await self.api.get_data()
            LOGGER.debug(data)
        except Exception as err:
            LOGGER.debug("Failed to fetch data: %s", err)
            LOGGER.exception("Error fetching data from BHyve")
            raise UpdateFailed(err) from err

        if not self.monitor_connected:
            if await self.api.login() is False:
                msg = "Invalid credentials"
                raise ConfigEntryAuthFailed(msg)
            LOGGER.debug(
                "Connecting to BHyve websocket",
            )
            await self.api.listen(self.hass.loop)
            self.api.register_data_callback(self.callback)
            self.monitor_connected = True

        return data

    async def client_listen(
        self,
        hass: HomeAssistant,
        entry: BHyveConfigEntry,
        bhyve_client: BHyveClient,
    ) -> None:
        """Listen with the client."""
        try:
            await bhyve_client.listen()
            # Reset reconnect time after successful connection
            self.reconnect_time = DEFAULT_RECONNECT_TIME
            await bhyve_client.start()
        except HusqvarnaWSServerHandshakeError as err:
            _LOGGER.debug(
                "Failed to connect to websocket. Trying to reconnect: %s",
                err,
            )
        except TimeoutException as err:
            _LOGGER.debug(
                "Failed to listen to websocket. Trying to reconnect: %s",
                err,
            )
        if not hass.is_stopping:
            await asyncio.sleep(self.reconnect_time)
            self.reconnect_time = min(self.reconnect_time * 2, MAX_WS_RECONNECT_TIME)
            entry.async_create_background_task(
                hass,
                self.client_listen(hass, entry, bhyve_client=bhyve_client),
                "reconnect_task",
            )

    @callback
    def callback(self, data: BHyveApiData) -> None:
        """Process long-poll callbacks and write them to the DataUpdateCoordinator."""
        self.async_set_updated_data(data)
