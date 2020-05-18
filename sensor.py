"""
Support for reading Ultimaker print progress

configuration.yaml

sensor:
  - platform: ultimaker
    host: IP_ADDRESS
    port: 10080
    scan_interval: 10
    resources:
      - 3dprinttotal
      - 3dprinttimeelapsed
      - 3dprintpercentage
      - 3dprintactive
"""
import logging
from datetime import timedelta
import aiohttp
import asyncio
import async_timeout
import voluptuous as vol
import time

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_RESOURCES
    )
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

BASE_URL = 'http://{0}/cluster-api/v1/print_jobs/printing'
_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=10)

SENSOR_PREFIX = '3D print '
SENSOR_TYPES = {
    '3dprinttotal': ['time total', 'HH:mm', 'mdi:thermometer'],
    '3dprinttimeelapsed': ['time elapsed', 'HH:mm', 'mdi:thermometer'],
    '3dprintpercentage': ['percentage', '%', 'mdi:thermometer'],
    '3dprintactive': ['active', '', ''],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_RESOURCES, default=list(SENSOR_TYPES)):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Setup the Ultimaker sensors."""

    host = config.get(CONF_HOST)

    ultimakerdata = UltimakerStatusData(hass, host)
    try:
        await ultimakerdata.async_update()
    except ValueError as err:
        _LOGGER.error("Error while fetching data from Ultimaker: %s", err)
        return

    entities = []
    for resource in config[CONF_RESOURCES]:
        sensor_type = resource.lower()
        name = SENSOR_PREFIX + SENSOR_TYPES[resource][0]
        unit = SENSOR_TYPES[resource][1]
        icon = SENSOR_TYPES[resource][2]

        _LOGGER.debug("Adding Ultimaker sensor: {}, {}, {}, {}".format(sensor_type, name, unit, icon))
        entities.append(UltimakerStatusSensor(ultimakerdata, sensor_type, name, unit, icon))

    async_add_entities(entities, True)


# pylint: disable=abstract-method
class UltimakerStatusData(object):
    """Handle Ultimaker object and limit updates."""

    def __init__(self, hass, host):
        """Initialize the data object."""
        self._hass = hass
        self._host = host

        self._url = BASE_URL.format(self._host)
        self._data = None

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Download and update data from Ultimaker."""

        try:
            websession = async_get_clientsession(self._hass)
            with async_timeout.timeout(5):
                response = await websession.get(self._url)
            _LOGGER.debug(
                "Response status from Ultimaker: %s", response.status
            )
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Cannot connect to Ultimaker: %s", err)
            self._data = None
            return
        except Exception as err:
            _LOGGER.error("Error downloading from Ultimaker: %s", err)
            self._data = None
            return

        try:
            self._data = await response.json(content_type='application/json')
            _LOGGER.debug("Data received from Ultimaker: %s", self._data)
        except Exception as err:
            _LOGGER.error("Cannot parse data from Ultimaker: %s", err)
            self._data = None
            return
    @property
    def latest_data(self):
        """Return the latest data object."""
        return self._data

class UltimakerStatusSensor(Entity):
    """Representation of a Ultimaker print job."""

    def __init__(self, ultimakerdata, sensor_type, name, unit, icon):
        """Initialize the sensor."""
        self._ultimakerdata = ultimakerdata
        self._name = name
        self._type = sensor_type
        self._unit = unit
        self._icon = icon

        self._state = None
        self._last_updated = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._icon

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit

    @property
    def device_state_attributes(self):
        """Return the state attributes of this device."""
        attr = {}
        if self._last_updated is not None:
            attr['Last Updated'] = self._last_updated
        return attr

    async def async_update(self):
        """Get the latest data and use it to update our sensor state."""

        await self._ultimakerdata.async_update()
        printstatus = self._ultimakerdata.latest_data
        isprinting = len(printstatus) > 0

        if self._type == '3dprintactive':
            self._state = isprinting

        if isprinting:
            if self._type == '3dprinttimeelapsed':
                if 'time_elapsed' in printstatus[0]:
                    if printstatus[0]["time_elapsed"] is not None:
                        self._state = time.strftime('%H:%M', time.gmtime(printstatus[0]["time_elapsed"]))
            elif self._type == '3dprinttotal':
                if 'time_total' in printstatus[0]:
                    if printstatus[0]["time_total"] is not None:
                        self._state = time.strftime('%H:%M', time.gmtime(printstatus[0]["time_total"]))
            elif self._type == '3dprintpercentage':
                if 'time_elapsed' in printstatus[0] and 'time_total' in printstatus[0]:
                    if printstatus[0]["time_elapsed"] is not None and printstatus[0]["time_total"] is not None:
                        self._state = min(int((printstatus[0]["time_elapsed"] / printstatus[0]["time_total"]) * 100), 100)

            _LOGGER.debug("Device: {} State: {}".format(self._type, self._state))

