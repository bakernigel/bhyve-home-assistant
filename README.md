<!-- markdownlint-disable no-inline-html -->
# bhyve-home-assistant

Orbit B-hyve component for [Home Assistant](https://www.home-assistant.io/).

This integration is a copy of https://github.com/sebr/bhyve-home-assistant/ with the addition of a calendar entity to show programmed watering days.

If this integration has been useful to you, please consider chipping in and buying @sebr a coffee!

<a href="https://www.buymeacoffee.com/sebr" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee"></a>

For full instructions on using the integration see https://github.com/sebr/bhyve-home-assistant/

## Supported Entities

- `sensor` for measuring battery levels and watering history of `sprinkler_timer` devices as well as the device on/off state (not to be confused with zone on/off switches).
- `temperature sensor` for measuring the temperature at the device.
- `switch` for turning a zone on/off, enabling/disabling rain delays and toggling pre-configured programs.
- `binary_sensor` for `flood_sensor` devices which provide liquid detection and temperature alerts when out of threshold.
- `calendar` adds a calendar entity for each program showing upcoming waterings

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=integration&repository=byhve-home-assistant&owner=bakernigel)

## __Installation Using HACS__
- Download the custom Orbit Bhyve integration from the HACS custom repository using the button above
- Restart Home Assistant
- Install the Orbit Bhyve custom Integration using Settings -> Devices and Services -> Add Integration
- Configure the integration using your Orbit Bhyve login and password.

For full instructions on using the integration see https://github.com/sebr/bhyve-home-assistant/ 

