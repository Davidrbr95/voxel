"""
This script provides a `KDC101Controller` class to control the Thorlabs KDC101 DC motor controller.
It allows connecting to the device, homing, moving to specific positions, retrieving positions, and disconnecting.

Reference: https://github.com/Thorlabs/Motion_Control_Examples/tree/main/Python/KCube/KDC101
"""
import logging
import os
import sys
import time
import serial
from ctypes import *
from voxel.devices.tunable_lens.base import BaseTunableLens


class KDC101Controller(BaseTunableLens):
    """
    A controller class for the Thorlabs KDC101 DC motor controller.
    """

    def __init__(self, port: str, serial_num: str, lib_path: str): #, "27268443",  r"C:\Program Files\Thorlabs\Kinesis"
        """
        Initializes the KDC101Controller.

        :param serial_num: The serial number of the KDC101 device as a string.
        :param lib_path: The path to the Kinesis library. Defaults to Thorlabs' standard installation path.
        """
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.log.info('Starting the initialization of Tunable lens')
        self.port = port
        self._mode = 'default'
        self.serial_num_str = serial_num
        self.serial_num = c_char_p(serial_num.encode('utf-8'))
        self.lib_path = lib_path
        self.lib = None
        self.conversion_factor = 0.0289 / 1000  # mm per device unit

        # Load the Kinesis library
        self._load_library()
        self.connect()
        self.home()

    def _load_library(self):
        """
        Loads the Thorlabs Kinesis library using ctypes.
        """
        if sys.version_info < (3, 8):
            os.chdir(self.lib_path)
        else:
            os.add_dll_directory(self.lib_path)

        try:
            self.lib = cdll.LoadLibrary("Thorlabs.MotionControl.KCube.DCServo.dll")
            print("Successfully loaded Thorlabs.MotionControl.KCube.DCServo.dll")
        except OSError as e:
            raise RuntimeError(f"Failed to load the Kinesis library: {e}")

    @property 
    def mode(self):
        """Get the tunable lens control mode."""
        return self._mode
    
    @mode.setter
    def mode(self, mode: str):
        self._mode = mode
        self.log.info(f"Sent comamnd to mode: {self.mode}")
    
    def connect(self):
        """
        Connects to the KDC101 device and starts polling.

        :raises RuntimeError: If the device list cannot be built.
        """
        if self.lib.TLI_BuildDeviceList() == 0:
            self.lib.CC_Open(self.serial_num)
            self.lib.CC_StartPolling(self.serial_num, c_int(200))
            print(f"Connected to device {self.serial_num_str}")
        else:
            raise RuntimeError("Failed to build device list. Ensure the device is connected.")

    def home(self):
        """
        Homes the KDC101 device.
        """
        self.lib.CC_Home(self.serial_num)
        print("Homing the device...")
        time.sleep(10)  # Wait for homing to complete
        print("Homing completed.")

    @property
    def position(self) -> float:
        """
        Retrieves the current position of the device in real units.

        :return: Current position in real units (e.g., mm).
        """
        self.lib.CC_RequestPosition(self.serial_num)
        time.sleep(0.2)  # Wait for the position to be updated

        dev_pos = c_int(self.lib.CC_GetPosition(self.serial_num))
        real_pos = round(dev_pos.value * self.conversion_factor, 2)
        self.log.info(f"Current position: {real_pos} mm")
        return real_pos

    @position.setter
    def position(self, position):
        """
        Moves the device to the specified real position.

        :param position: Target position in real units (e.g., mm).
        """
        dev_pos = int(position / self.conversion_factor)

        new_pos_real = c_double(position)
        new_pos_dev = c_int(dev_pos)

        self.lib.CC_GetDeviceUnitFromRealValue(self.serial_num, new_pos_real, byref(new_pos_dev), 0)
        self.log.info(f"Moving to position {position} units (Device Units: {new_pos_dev.value})")

        self.lib.CC_SetMoveAbsolutePosition(self.serial_num, new_pos_dev)
        time.sleep(0.25)  # Brief pause before moving
        self.lib.CC_MoveAbsolute(self.serial_num)
        self.log.info(f"Move command issued.")

    def close(self):
        """
        Disconnects from the KDC101 device and stops polling.
        """
        self.lib.CC_Close(self.serial_num)
        print(f"Disconnected from device {self.serial_num_str}")