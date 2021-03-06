"""
Support for Blink Alarm Control Panel.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/alarm_control_panel.blink/
"""
import logging

from homeassistant.components.alarm_control_panel import AlarmControlPanel
from homeassistant.components.blink import (
    BLINK_DATA, DEFAULT_ATTRIBUTION)
from homeassistant.const import (
    ATTR_ATTRIBUTION, STATE_ALARM_DISARMED, STATE_ALARM_ARMED_AWAY)

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['blink']

ICON = 'mdi:security'


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Arlo Alarm Control Panels."""
    if discovery_info is None:
        return
    data = hass.data[BLINK_DATA]

    # Current version of blinkpy API only supports one sync module.  When
    # support for additional models is added, the sync module name should
    # come from the API.
    sync_modules = []
    sync_modules.append(BlinkSyncModule(data, 'sync'))
    add_entities(sync_modules, True)


class BlinkSyncModule(AlarmControlPanel):
    """Representation of a Blink Alarm Control Panel."""

    def __init__(self, data, name):
        """Initialize the alarm control panel."""
        self.data = data
        self.sync = data.sync
        self._name = name
        self._state = None

    @property
    def icon(self):
        """Return icon."""
        return ICON

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def name(self):
        """Return the name of the panel."""
        return "{} {}".format(BLINK_DATA, self._name)

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            ATTR_ATTRIBUTION: DEFAULT_ATTRIBUTION,
        }

    def update(self):
        """Update the state of the device."""
        _LOGGER.debug("Updating Blink Alarm Control Panel %s", self._name)
        self.data.refresh()
        mode = self.sync.arm
        if mode:
            self._state = STATE_ALARM_ARMED_AWAY
        else:
            self._state = STATE_ALARM_DISARMED

    def alarm_disarm(self, code=None):
        """Send disarm command."""
        self.sync.arm = False
        self.sync.refresh()

    def alarm_arm_away(self, code=None):
        """Send arm command."""
        self.sync.arm = True
        self.sync.refresh()
