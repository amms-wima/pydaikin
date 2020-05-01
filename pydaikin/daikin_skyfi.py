"""Pydaikin appliance, represent a Daikin device."""

import logging
from urllib.parse import unquote

from aiohttp.client_exceptions import ClientOSError, ClientResponseError

from .daikin_base import Appliance

_LOGGER = logging.getLogger(__name__)


class DaikinSkyFi(Appliance):
    """Daikin class for SkyFi units."""

    HTTP_RESOURCES = ['ac.cgi?pass={}', 'zones.cgi?pass={}']

    INFO_RESOURCES = HTTP_RESOURCES

    SKYFI_TO_DAIKIN = {
        'outsidetemp': 'otemp',
        'roomtemp': 'htemp',
        'settemp': 'stemp',
        'opmode': 'pow',
        'fanspeed': 'f_rate',
        'fanflags': 'f_dir',
        'acmode': 'mode',
    }

    DAIKIN_TO_SKYFI = {val: k for k, val in SKYFI_TO_DAIKIN.items()}

    TRANSLATIONS = {
        'mode': {
            '0': 'Off',
            '1': 'auto',
            '2': 'hot',
            '3': 'auto-3',
            '4': 'dry',
            '8': 'cool',
            '9': 'auto-9',
            '16': 'fan',
        },
        'f_rate': {'0': 'auto', '1': 'low', '2': 'medium', '3': 'high'},
        'f_mode': {'1': 'manual', '3': 'auto'},
    }

    def __init__(self, device_id, session=None, password=None):
        """Init the pydaikin appliance, representing one Daikin SkyFi device."""
        super().__init__(device_id, session)
        self._device_ip = f'{self._device_ip}:2000'
        self._password = password

    def __getitem__(self, name):
        """Return named value."""
        name = self.SKYFI_TO_DAIKIN.get(name, name)
        return super().__getitem__(name)

    async def init(self):
        """Init status."""
        await self.update_status(self.HTTP_RESOURCES)

    def set_holiday(self, mode):
        """Set holiday mode."""

    @property
    def support_away_mode(self):
        """Return True if the device support away_mode."""
        return False

    @property
    def support_fan_rate(self):
        """Return True if the device support setting fan_rate."""
        return True

    @property
    def support_swing_mode(self):
        """Return True if the device support setting swing_mode."""
        return False

    @staticmethod
    def parse_response(response_body):
        """Parse response from Daikin and map it to general Daikin format."""
        _LOGGER.debug("Parsing %s", response_body)
        response = dict([e.split('=') for e in response_body.split('&')])
        response.update(
            {
                DaikinSkyFi.SKYFI_TO_DAIKIN.get(key, key): val
                for key, val in response.items()
            }
        )
        return response

    async def _run_get_resource(self, resource):
        """Make the http request."""
        resource = resource.format(self._password)
        for i in range(4):
            try:
                return await super()._run_get_resource(resource)
            except (ClientOSError, ClientResponseError) as err:
                _LOGGER.debug("%s #%s", repr(err), i)
                if i >= 3:
                    raise

    def represent(self, key):
        """Return translated value from key."""
        k, val = super().represent(self.SKYFI_TO_DAIKIN.get(key, key))
        if key in [f'zone{i}' for i in range(1, 9)]:
            val = unquote(self[key])
        if key == 'zone':
            # zone is a binary representation of zone status
            val = list(str(bin(int(self[key]) + 256)))[3:]
        return (k, val)

    async def set(self, settings):
        """Set settings on Daikin device."""
        _LOGGER.debug("Updating settings: %s", settings)
        # start with current values
        current_val = await self._get_resource('ac.cgi?')
        _LOGGER.debug("Current settings: %s", current_val)

        # Merge current_val with mapped settings
        self.values.update(current_val)
        self.values.update(
            {
                self.DAIKIN_TO_SKYFI[k]: self.human_to_daikin(k, v)
                for k, v in settings.items()
            }
        )
        _LOGGER.debug("Updated values: %s", self.values)

        # we are using an extra mode "off" to power off the unit
        if settings.get('acmode', '') == 'off':
            self.values['opmode'] = '0'
            self.values['acmode'] = current_val['acmode']
        else:
            self.values['opmode'] = '1'

        query_c = 'set.cgi?pass={{}}p={opmode}&t={settemp}&f={fanspeed}&m={acmode}&'.format(
            **self.values
        )

        _LOGGER.debug("Sending query_c: %s", query_c)
        self.parse_response(await self._get_resource(query_c))
        _LOGGER.debug("Updated values: %s", self.values)

    @property
    def zones(self):
        """Return list of zones."""
        if 'nz' not in self.values:
            return False
        return [
            (self.represent(f'zone{i+1}')[1].strip(' +,'), onoff)
            for i, onoff in enumerate(self.represent('zone'))
        ]

    async def set_zone(self, zone_id, status):
        """Set zone status."""
        query = f'/setzone.cgi?z={zone_id}&s={status}&'
        _LOGGER.debug("Set zone: %s", query)
        current_state = await self._get_resource(query)
        self.values.update(current_state)
