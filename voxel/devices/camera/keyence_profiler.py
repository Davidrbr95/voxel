import ctypes
import time
import voxel.devices.camera.sdks.keyence.LJXAwrap as LJXAwrap
from voxel.devices.camera.base import BaseCamera

SAMPLING_RATE = {
    10: 0,
    20: 1,
    50: 2,
    100: 3,
    200: 4,
    500: 5,
    1000: 6,
    2000: 7,
    4000: 8,
    5000: 16
}

EXPOSURE_TIME = {
    0.015: 0,
    0.03: 1,
    0.06: 2,
    0.12: 3,
    0.24: 4,
    0.48: 5,
    0.96: 6,
    1.7: 7,
    4.8: 8,
    9.6: 9
}


class Profiler(BaseCamera):
    def __init__(self, device_id, ip1, ip2, ip3, ip4, portno, hsportno):
        self.device_id = device_id
        self.ip1 = ip1
        self.ip2 = ip2
        self.ip3 = ip3
        self.ip4 = ip4
        self.portno = portno
        self.hsportno = hsportno
        self.ethernetConfig = None
        self.close()
        self.prepare()

    def reset(self):
        """
        Reset the camera.
        """
        LJXAwrap.LJX8IF_ReturnToFactorySetting(self.device_id)
        print("Resetting controller to factory settings for device", self.device_id)
        LJXAwrap.LJX8IF_RebootController(self.device_id)
        print("Rebooting controller for device", self.device_id)
        time.sleep(20)
        self.prepare()
        return
    
    def prepare(self):
        """
        Prepare the camera for acquisition.
        """
        self.ethernetConfig = LJXAwrap.LJX8IF_ETHERNET_CONFIG()
        self.ethernetConfig.abyIpAddress[0] = self.ip1  # IP address
        self.ethernetConfig.abyIpAddress[1] = self.ip2
        self.ethernetConfig.abyIpAddress[2] = self.ip3
        self.ethernetConfig.abyIpAddress[3] = self.ip4
        self.ethernetConfig.wPortNo = self.portno       # Port No.

        res = LJXAwrap.LJX8IF_EthernetOpen(self.device_id, self.ethernetConfig)
        print("Ethernet connection open for device", self.device_id)
        if res != 0:
            print("Failed to connect controller.")
        print("----")
        return

    def start(self):
        """
        Start the camera acquisition.
        """
        LJXAwrap.LJX8IF_StartMeasure(self.device_id)
        print("Starting measure for device", self.device_id)
        return

    def stop(self):
        """
        Stop the camera acquisition.
        """
        LJXAwrap.LJX8IF_StopMeasure(self.device_id)
        print("Stopping measure for device", self.device_id)
        return

    def close(self):
        """
        Close the camera and release resources.
        """
        LJXAwrap.LJX8IF_CommunicationClose(self.device_id)
        print("----")
        print("Ethernet connection closed for device", self.device_id)
        return
    
    def laser_on(self):
        LJXAwrap.LJX8IF_ControlLaser(self.device_id, 1)
        print("Turning on laser for device", self.device_id)
        return
    
    def laser_off(self):
        LJXAwrap.LJX8IF_ControlLaser(self.device_id, 0)
        print("Turning off laser for device", self.device_id)
        return
    
    @property
    def sampling_rate_hz(self):
        rate_value = self._get_setting(category=0x00, item=0x02)
        rate_key = next(rate_key for rate_key, val in SAMPLING_RATE.items() if val == rate_value)
        return rate_key
    
    @sampling_rate_hz.setter
    def sampling_rate(self, rate):
        rate_value = SAMPLING_RATE[rate]
        self._set_setting(category=0x00, item=0x02, value=[rate_value, 0, 0, 0])
    
    @property
    def exposure_time_ms(self):
        time_value = self._get_setting(category=0x01, item=0x06)
        time_key = next(time_key for time_key, val in EXPOSURE_TIME.items() if val == time_value)
        return time_key
    
    @exposure_time_ms.setter
    def exposure_time_ms(self, time):
        time_value = EXPOSURE_TIME[time]
        self._set_setting(category=0x01, item=0x06, value=[time_value, 0, 0, 0])
    
    @property
    def dynamic_range(self):
        dr_value = self._get_setting(category=0x01, item=0x05)
        return dr_value
    
    @dynamic_range.setter
    def dynamic_range(self, dr):
        self._set_setting(category=0x01, item=0x05, value=[dr, 0, 0, 0])
    
    def _get_setting(self, category, item, depth=1, type=0x10):
        target_setting = LJXAwrap.LJX8IF_TARGET_SETTING()
        target_setting.byType = type         # Program No.
        target_setting.byCategory = category # Trigger category
        target_setting.byItem = item         # Item
        target_setting.byTarget1 = 0x00      # reserved
        target_setting.byTarget2 = 0x00      # reserved
        target_setting.byTarget3 = 0x00      # reserved
        target_setting.byTarget4 = 0x00      # reserved

        data_size = 4

        # Get setting to confirm
        setting_data_get = (ctypes.c_ubyte * data_size)()
        LJXAwrap.LJX8IF_GetSetting(self.device_id, depth,
                                         target_setting,
                                         setting_data_get, data_size)
        return setting_data_get
    
    def _set_setting(self, category, item, value, depth=1, type=0x10):
        target_setting = LJXAwrap.LJX8IF_TARGET_SETTING()
        target_setting.byType = type         # Program No.
        target_setting.byCategory = category # Trigger category
        target_setting.byItem = item         # Item
        target_setting.byTarget1 = 0x00      # reserved
        target_setting.byTarget2 = 0x00      # reserved
        target_setting.byTarget3 = 0x00      # reserved
        target_setting.byTarget4 = 0x00      # reserved

        data_size = 4

        # Set the value
        err = ctypes.c_uint()
        py_arr = value
        setting_data_set = (ctypes.c_ubyte * data_size)(*py_arr)

        LJXAwrap.LJX8IF_SetSetting(self.device_id, depth,
                                         target_setting,
                                         setting_data_set, data_size, err)
    
    def _change_batch_measurement(self, bm_value=1):
        self._set_setting(category=0x00, item=0x03, value=[bm_value, 0, 0, 0])
    
    def _change_batch_count(self, bc_value=[39, 16]):
        self._set_setting(category=0x00, item=0x0A, value=[bc_value[1], bc_value[0], 0, 0])