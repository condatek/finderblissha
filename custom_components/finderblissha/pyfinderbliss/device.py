from .client import BlissClientAsync

class DeviceAsync:
    def __init__(self, client: BlissClientAsync, device_info: dict):
        self.client = client
        self.id = device_info.get("serial_number")
        self.name = device_info.get("name")
        self.model = device_info.get("model")
        self._state = device_info

    @property
    def temperature(self):
        return self._state.get("temperature")

    @property
    def humidity(self):
        return self._state.get("humidity")

    async def async_update(self):
        devices = await self.client.get_devices()
        for d in devices:
            if d.get("serial_number") == self.id:
                self._state = d
                break

    async def async_set_temperature(self, temp: float):
        # TODO: implement set_temperature call to API
        pass
