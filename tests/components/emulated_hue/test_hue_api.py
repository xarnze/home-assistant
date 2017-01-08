"""The tests for the emulated Hue component."""
import json

from unittest.mock import patch
import requests

from homeassistant import bootstrap, const, core
import homeassistant.components as core_components
from homeassistant.components import (
    emulated_hue, http, light, script, media_player
)
from homeassistant.const import STATE_ON, STATE_OFF
from homeassistant.components.emulated_hue.hue_api import (
    HUE_API_STATE_ON, HUE_API_STATE_BRI)
from homeassistant.util.async import run_coroutine_threadsafe

from tests.common import get_test_instance_port, get_test_home_assistant

HTTP_SERVER_PORT = get_test_instance_port()
BRIDGE_SERVER_PORT = get_test_instance_port()

BRIDGE_URL_BASE = 'http://127.0.0.1:{}'.format(BRIDGE_SERVER_PORT) + '{}'
JSON_HEADERS = {const.HTTP_HEADER_CONTENT_TYPE: const.CONTENT_TYPE_JSON}

HASS = None


def setUpModule():
    """Setup the class."""
    global HASS
    HASS = hass = get_test_home_assistant()

    # We need to do this to get access to homeassistant/turn_(on,off)
    run_coroutine_threadsafe(
        core_components.async_setup(hass, {core.DOMAIN: {}}), hass.loop
    ).result()

    bootstrap.setup_component(
        hass, http.DOMAIN,
        {http.DOMAIN: {http.CONF_SERVER_PORT: HTTP_SERVER_PORT}})

    with patch('homeassistant.components'
               '.emulated_hue.UPNPResponderThread'):
        bootstrap.setup_component(hass, emulated_hue.DOMAIN, {
            emulated_hue.DOMAIN: {
                emulated_hue.CONF_LISTEN_PORT: BRIDGE_SERVER_PORT,
                emulated_hue.CONF_EXPOSE_BY_DEFAULT: True
            }
        })

    bootstrap.setup_component(hass, light.DOMAIN, {
        'light': [
            {
                'platform': 'demo',
            }
        ]
    })

    bootstrap.setup_component(hass, script.DOMAIN, {
        'script': {
            'set_kitchen_light': {
                'sequence': [
                    {
                        'service_template':
                            "light.turn_{{ requested_state }}",
                        'data_template': {
                            'entity_id': 'light.kitchen_lights',
                            'brightness': "{{ requested_level }}"
                            }
                    }
                ]
            }
        }
    })

    bootstrap.setup_component(hass, media_player.DOMAIN, {
        'media_player': [
            {
                'platform': 'demo',
            }
        ]
    })

    hass.start()

    # Kitchen light is explicitly excluded from being exposed
    kitchen_light_entity = hass.states.get('light.kitchen_lights')
    attrs = dict(kitchen_light_entity.attributes)
    attrs[emulated_hue.ATTR_EMULATED_HUE] = False
    hass.states.set(
        kitchen_light_entity.entity_id, kitchen_light_entity.state,
        attributes=attrs)

    # Expose the script
    script_entity = hass.states.get('script.set_kitchen_light')
    attrs = dict(script_entity.attributes)
    attrs[emulated_hue.ATTR_EMULATED_HUE] = True
    hass.states.set(
        script_entity.entity_id, script_entity.state, attributes=attrs
    )


def tearDownModule():
    """Stop module."""
    global HASS
    HASS.stop()
    HASS = None


def test_discover_lights():
    """Test the discovery of lights."""
    result = requests.get(
        BRIDGE_URL_BASE.format('/api/username/lights'), timeout=5)

    assert result.status_code == 200
    assert 'application/json' in result.headers['content-type']

    result_json = result.json()

    # Make sure the lights we added to the config are there
    assert 'light.ceiling_lights' in result_json
    assert 'light.bed_light' in result_json
    assert 'script.set_kitchen_light' in result_json
    assert 'light.kitchen_lights' not in result_json
    assert 'media_player.living_room' in result_json
    assert 'media_player.bedroom' in result_json
    assert 'media_player.walkman' in result_json
    assert 'media_player.lounge_room' in result_json


def test_get_light_state():
    """Test the getting of light state."""
    # Turn office light on and set to 127 brightness
    HASS.services.call(
        light.DOMAIN, const.SERVICE_TURN_ON,
        {
            const.ATTR_ENTITY_ID: 'light.ceiling_lights',
            light.ATTR_BRIGHTNESS: 127
        },
        blocking=True)

    office_json = perform_get_light_state('light.ceiling_lights', 200)

    assert office_json['state'][HUE_API_STATE_ON] is True
    assert office_json['state'][HUE_API_STATE_BRI] == 127

    # Check all lights view
    result = requests.get(
        BRIDGE_URL_BASE.format('/api/username/lights'), timeout=5)

    assert result.status_code == 200
    assert 'application/json' in result.headers['content-type']

    result_json = result.json()

    assert 'light.ceiling_lights' in result_json
    assert result_json['light.ceiling_lights']['state'][HUE_API_STATE_BRI] == \
        127

    # Turn bedroom light off
    HASS.services.call(
        light.DOMAIN, const.SERVICE_TURN_OFF,
        {
            const.ATTR_ENTITY_ID: 'light.bed_light'
        },
        blocking=True)

    bedroom_json = perform_get_light_state('light.bed_light', 200)

    assert bedroom_json['state'][HUE_API_STATE_ON] is False
    assert bedroom_json['state'][HUE_API_STATE_BRI] == 0

    # Make sure kitchen light isn't accessible
    kitchen_url = '/api/username/lights/{}'.format('light.kitchen_lights')
    kitchen_result = requests.get(
        BRIDGE_URL_BASE.format(kitchen_url), timeout=5)

    assert kitchen_result.status_code == 404


def test_put_light_state():
    """Test the seeting of light states."""
    perform_put_test_on_ceiling_lights()

    # Turn the bedroom light on first
    HASS.services.call(
        light.DOMAIN, const.SERVICE_TURN_ON,
        {const.ATTR_ENTITY_ID: 'light.bed_light',
         light.ATTR_BRIGHTNESS: 153},
        blocking=True)

    bed_light = HASS.states.get('light.bed_light')
    assert bed_light.state == STATE_ON
    assert bed_light.attributes[light.ATTR_BRIGHTNESS] == 153

    # Go through the API to turn it off
    bedroom_result = perform_put_light_state(
        'light.bed_light', False)

    bedroom_result_json = bedroom_result.json()

    assert bedroom_result.status_code == 200
    assert 'application/json' in bedroom_result.headers['content-type']

    assert len(bedroom_result_json) == 1

    # Check to make sure the state changed
    bed_light = HASS.states.get('light.bed_light')
    assert bed_light.state == STATE_OFF

    # Make sure we can't change the kitchen light state
    kitchen_result = perform_put_light_state(
        'light.kitchen_light', True)
    assert kitchen_result.status_code == 404


def test_put_light_state_script():
    """Test the setting of script variables."""
    # Turn the kitchen light off first
    HASS.services.call(
        light.DOMAIN, const.SERVICE_TURN_OFF,
        {const.ATTR_ENTITY_ID: 'light.kitchen_lights'},
        blocking=True)

    # Emulated hue converts 0-100% to 0-255.
    level = 23
    brightness = round(level * 255 / 100)

    script_result = perform_put_light_state(
        'script.set_kitchen_light', True, brightness)

    script_result_json = script_result.json()

    assert script_result.status_code == 200
    assert len(script_result_json) == 2

    kitchen_light = HASS.states.get('light.kitchen_lights')
    assert kitchen_light.state == 'on'
    assert kitchen_light.attributes[light.ATTR_BRIGHTNESS] == level


def test_put_light_state_media_player():
    """Test turning on media player and setting volume."""
    # Turn the music player off first
    HASS.services.call(
        media_player.DOMAIN, const.SERVICE_TURN_OFF,
        {const.ATTR_ENTITY_ID: 'media_player.walkman'},
        blocking=True)

    # Emulated hue converts 0.0-1.0 to 0-255.
    level = 0.25
    brightness = round(level * 255)

    mp_result = perform_put_light_state(
        'media_player.walkman', True, brightness)

    mp_result_json = mp_result.json()

    assert mp_result.status_code == 200
    assert len(mp_result_json) == 2

    walkman = HASS.states.get('media_player.walkman')
    assert walkman.state == 'playing'
    assert walkman.attributes[media_player.ATTR_MEDIA_VOLUME_LEVEL] == level


# pylint: disable=invalid-name
def test_put_with_form_urlencoded_content_type():
    """Test the form with urlencoded content."""
    # Needed for Alexa
    perform_put_test_on_ceiling_lights(
        'application/x-www-form-urlencoded')

    # Make sure we fail gracefully when we can't parse the data
    data = {'key1': 'value1', 'key2': 'value2'}
    result = requests.put(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}/state'.format(
                'light.ceiling_lights')), data=data)

    assert result.status_code == 400


def test_entity_not_found():
    """Test for entity which are not found."""
    result = requests.get(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}'.format("not.existant_entity")),
        timeout=5)

    assert result.status_code == 404

    result = requests.put(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}/state'.format("non.existant_entity")),
        timeout=5)

    assert result.status_code == 404


def test_allowed_methods():
    """Test the allowed methods."""
    result = requests.get(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}/state'.format(
                "light.ceiling_lights")))

    assert result.status_code == 405

    result = requests.put(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}'.format("light.ceiling_lights")),
        data={'key1': 'value1'})

    assert result.status_code == 405

    result = requests.put(
        BRIDGE_URL_BASE.format('/api/username/lights'),
        data={'key1': 'value1'})

    assert result.status_code == 405


def test_proper_put_state_request():
    """Test the request to set the state."""
    # Test proper on value parsing
    result = requests.put(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}/state'.format(
                'light.ceiling_lights')),
        data=json.dumps({HUE_API_STATE_ON: 1234}))

    assert result.status_code == 400

    # Test proper brightness value parsing
    result = requests.put(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}/state'.format(
                'light.ceiling_lights')), data=json.dumps({
                    HUE_API_STATE_ON: True,
                    HUE_API_STATE_BRI: 'Hello world!'
                }))

    assert result.status_code == 400


# pylint: disable=invalid-name
def perform_put_test_on_ceiling_lights(content_type='application/json'):
    """Test the setting of a light."""
    # Turn the office light off first
    HASS.services.call(
        light.DOMAIN, const.SERVICE_TURN_OFF,
        {const.ATTR_ENTITY_ID: 'light.ceiling_lights'},
        blocking=True)

    ceiling_lights = HASS.states.get('light.ceiling_lights')
    assert ceiling_lights.state == STATE_OFF

    # Go through the API to turn it on
    office_result = perform_put_light_state(
        'light.ceiling_lights', True, 56, content_type)

    office_result_json = office_result.json()

    assert office_result.status_code == 200
    assert 'application/json' in office_result.headers['content-type']

    assert len(office_result_json) == 2

    # Check to make sure the state changed
    ceiling_lights = HASS.states.get('light.ceiling_lights')
    assert ceiling_lights.state == STATE_ON
    assert ceiling_lights.attributes[light.ATTR_BRIGHTNESS] == 56


def perform_get_light_state(entity_id, expected_status):
    """Test the gettting of a light state."""
    result = requests.get(
        BRIDGE_URL_BASE.format(
            '/api/username/lights/{}'.format(entity_id)), timeout=5)

    assert result.status_code == expected_status

    if expected_status == 200:
        assert 'application/json' in result.headers['content-type']

        return result.json()

    return None


# pylint: disable=no-self-use
def perform_put_light_state(entity_id, is_on, brightness=None,
                            content_type='application/json'):
    """Test the setting of a light state."""
    url = BRIDGE_URL_BASE.format(
        '/api/username/lights/{}/state'.format(entity_id))

    req_headers = {'Content-Type': content_type}

    data = {HUE_API_STATE_ON: is_on}

    if brightness is not None:
        data[HUE_API_STATE_BRI] = brightness

    result = requests.put(
        url, data=json.dumps(data), timeout=5, headers=req_headers)

    # Wait until state change is complete before continuing
    HASS.block_till_done()

    return result
