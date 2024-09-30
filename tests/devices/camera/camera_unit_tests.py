import os
import sys
# Update sys.path to include the voxel directory if needed
voxel_path = r"C:\Users\AIBS\Desktop\UHR-OTLS-control\voxel"
sys.path.append(voxel_path)

import unittest
from voxel.devices.camera.sdks.dcam.dcam import Dcamapi, Dcam
from voxel.devices.camera.hamamatsu_dcam import Camera  



# Constants for the tests 
SERIAL_NUMBER = 306726
WIDTH_PX = 2048
HEIGHT_PX = 2048
EXPOSURE_TIME_MS = 20.0
DECIMAL_PLACE = 1

# Possible values for testing
BINNING = {'1x1': 1, '2x2': 2, '4x4': 4}
PIXEL_TYPES = {'mono8': 1, 'mono16': 2, 'mono12': 3}
# TRIGGERS = {
#     'mode': {'normal': 1, 'start': 6},
#     'source': {'internal': 1, 'external': 2, 'software': 3, 'master pulse': 4},
#     'polarity': {'negative': 1, 'positive': 2},
#     'active': {'edge': 1, 'level': 2, 'syncreadout': 3}
# }
TRIGGERS = {
    'mode': {'normal': 1, 'start': 6},
    'source': {'external': 2, 'software': 3, 'master pulse': 4},
    'polarity': {'negative': 1, 'positive': 2},
    'active': {'edge': 1, 'level': 2, 'syncreadout': 3}
}
SENSOR_MODES = {'area': 1, 'progressive': 12, 'split view': 14, 'dual light sheet': 16}
READOUT_DIRECTIONS = {'diverge': 5}


class TestCamera(unittest.TestCase):

    def setUp(self):
        """Set up the camera for testing."""
        self.camera = Camera(id=SERIAL_NUMBER)
        # self.camera.print_existing_options()
        print("Camera setup complete.")

    def test_camera_initialization(self):
        """Test if the camera initializes correctly."""
        self.assertIsNotNone(self.camera.dcam)
        print("Camera initialized successfully.")

    def test_camera_set_exposure_time(self):
        """Test setting the exposure time."""
        self.camera.exposure_time_ms = EXPOSURE_TIME_MS
        exposure_time_set = self.camera.exposure_time_ms
        self.assertAlmostEqual(exposure_time_set, EXPOSURE_TIME_MS, DECIMAL_PLACE)
        print(f"Exposure time set and verified: {exposure_time_set} ms")

    def test_camera_set_width_px(self):
        """Test setting the width in pixels."""
        self.camera.width_px = WIDTH_PX
        width_set = self.camera.width_px
        self.assertEqual(width_set, WIDTH_PX)
        print(f"Width set and verified: {width_set} px")

    def test_camera_set_pixel_type(self):
        """Test setting the pixel type for all options."""
        for pixel_type, value in PIXEL_TYPES.items():
            with self.subTest(pixel_type=pixel_type):
                self.camera.pixel_type = pixel_type
                pixel_type_set = self.camera.pixel_type
                self.assertEqual(pixel_type_set, pixel_type)
                print(f"Pixel type set and verified: {pixel_type_set}")

    def test_camera_set_binning(self):
        """Test setting the binning for all options."""
        for binning, value in BINNING.items():
            with self.subTest(binning=binning):
                print('VAlue', binning)
                self.camera.binning = binning
                binning_set = self.camera.binning
                self.assertEqual(binning_set, value)
                print(f"Binning set and verified: {binning_set}")

    def test_camera_set_sensor_mode(self):
        """Test setting the sensor mode for all options."""
        for sensor_mode, value in SENSOR_MODES.items():
            with self.subTest(sensor_mode=sensor_mode):
                self.camera.sensor_mode = sensor_mode
                sensor_mode_set = self.camera.sensor_mode
                self.assertEqual(sensor_mode_set, sensor_mode)
                print(f"Sensor mode set and verified: {sensor_mode_set}")

    def test_camera_set_width_px_offset(self):
        self.camera.width_offset_px = 20
        self.assertEqual(self.camera.width_offset_px, 20)

    def test_camera_set_height_px_offset(self):
        # self.camera.height_offset_px = 824
        self.camera.height_px = 400
        self.camera.prepare()
        self.camera.start()
        frame = self.camera.grab_frame()
        print(frame.shape)
        self.camera.stop()
        self.assertEqual(self.camera.height_offset_px, 824)

    def test_camera_set_trigger_mode(self):
        failed_combinations = []
        """Test setting the trigger mode, source, and polarity for all options."""
        for mode, mode_value in TRIGGERS['mode'].items():
            for source, source_value in TRIGGERS['source'].items():
                for polarity, polarity_value in TRIGGERS['polarity'].items():
                    for active, active_value in TRIGGERS['active'].items():
                        with self.subTest(mode=mode, source=source, polarity=polarity, active=active):
                            self.camera.trigger = {"mode": mode, "source": source, "polarity": polarity, "active": active}
                            trigger_mode_set = self.camera.trigger['mode']
                            trigger_source_set = self.camera.trigger['source']
                            trigger_polarity_set = self.camera.trigger['polarity']
                            trigger_active_set = self.camera.trigger['active']
                            try:
                                self.assertEqual(trigger_mode_set, mode)
                                self.assertEqual(trigger_source_set, source)
                                self.assertEqual(trigger_polarity_set, polarity)
                                self.assertEqual(trigger_active_set, active)
                                print(f"Trigger mode set and verified: {trigger_mode_set}, source: {trigger_source_set}, polarity: {trigger_polarity_set}, active: {trigger_active_set}")
                            except:
                                failed_combinations.append([mode, source, polarity, active])
        print(failed_combinations, len(failed_combinations))
           
            #         break
            #     break
            # break
            
    def test_camera_set_readout_direction(self):
        """Test setting the readout direction for all options."""
        for readout_direction, value in READOUT_DIRECTIONS.items():
            with self.subTest(readout_direction=readout_direction):
                self.camera.readout_direction = readout_direction
                readout_direction_set = self.camera.readout_direction
                self.assertEqual(readout_direction_set, readout_direction)
                print(f"Readout direction set and verified: {readout_direction_set}")

    def test_camera_start_and_stop(self):
        """Test starting and stopping the camera."""
        self.camera.prepare()
        self.camera.start()
        print("Camera started.")
        self.camera.stop()
        print("Camera stopped.")

    def test_camera_grab_frame(self):
        """Test grabbing a frame."""
        self.camera.prepare()
        self.camera.start()
        frame = self.camera.grab_frame()
        self.assertIsNotNone(frame)
        print("Frame grabbed successfully.")
        self.camera.stop()

    def tearDown(self):
        """Clean up after each test."""
        self.camera.close()
        print("Camera closed.")


if __name__ == '__main__':
    unittest.main()
