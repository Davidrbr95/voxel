import unittest
import os
import sys
# Get the current script directory
# current_dir = os.path.dirname(os.path.abspath(__file__))

# Define the paths to Voxel and View
voxel_path = os.path.join(r"C:\Users\AIBS\Desktop\UHR-OTLS-control\voxel")
# view_path = os.path.join(current_dir, '../../../View')
# Add these paths to sys.path if they are not already present
if voxel_path not in sys.path:
    sys.path.append(voxel_path)
    print(f"Added {voxel_path} to sys.path")

from voxel.devices.tunable_lens.optotune_ele4i import TunableLens 
import time
import numpy as np


class TestTunableLens(unittest.TestCase):

    def setUp(self):
        # Initialize the TunableLens instance
        self.port = "COM4"  # Replace with the correct port for your setup
        self.tunable_lens = TunableLens(port=self.port)

    # def test_mode_setter_getter(self):
    #     # Test setting the mode to "external"
    #     self.tunable_lens.mode = "external"
    #     self.assertEqual(self.tunable_lens.mode, "external")

    #     # Test setting the mode back to "internal"
    #     self.tunable_lens.mode = "internal"
    #     self.assertEqual(self.tunable_lens.mode, "internal")

    def test_set_current(self):
        print('STARTING THE TEST')
        for i in np.linspace(-200, 200, 3):
            print(i)
            self.tunable_lens.current = i
        print(self.tunable_lens.signal_temperature_c)


    # def test_signal_temperature_c(self):
    #     # Get the temperature and check if it's a valid float number
    #     print('GOT TEM GET ATTR', getattr(self.tunable_lens, 'signal_temperature_c'))
    #     temperature = self.tunable_lens.signal_temperature_c
    #     print('Temperature', temperature)
    #     self.assertTrue(isinstance(temperature['Temperature [C]'], float))

    # def test_close(self):
    #     # Ensure the device can be closed without errors
    #     try:
    #         self.tunable_lens.close()
    #     except Exception as e:
    #         self.fail(f"Closing the device raised an exception: {e}")

    def tearDown(self):
        # Clean up by closing the device connection
        self.tunable_lens.close()

if __name__ == '__main__':
    unittest.main()
