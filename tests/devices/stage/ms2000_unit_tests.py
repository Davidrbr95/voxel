
import sys
sys.path.append(r"C:\Users\ARPA\Desktop\ControlCodes\ARPA-OTLS-control\voxel")
import unittest
from voxel.devices.stage.ms2000 import Stage, MS2000ControllerSingleton  # Assuming the class is in a module named stage_module
import time

ABSOLUTE_POSITION = 0.0

class TestStage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Setup a real connection to the MS2000 device.
        cls.ms2000 = MS2000ControllerSingleton(com_port='COM7', baud_rate=9600)  # Adjust COM port as necessary
    
    @classmethod
    def tearDownClass(cls):
        # Close the connection to the MS2000 device.
        cls.ms2000.disconnect_from_serial()

    def setUp(self):
        # Initialize the Stage object with real MS2000 controller
        self.stage = Stage(hardware_axis='x', instrument_axis='x', ms2000=self.ms2000, port = 'COM7')
    
    # def test_setup_scan(self):
    #     print('RUN setup scan')
    #     self.stage.setup_stage_scan(fast_axis_start_position=0,
    #                      slow_axis_start_position=0,
    #                      slow_axis_stop_position=0,
    #                      frame_count=10, frame_interval_um=1,
    #                      strip_count=1, pattern='raster')
    #     pass

    # def test_start_scan(self):
    #     self.stage.start()
        
    # def test_stage_initialization(self):
    #     # Ensure the stage is initialized with the correct axis mapping
    #     # NOT SURE IF THIS IS THE CORRECT Expected output for 3rd statement
    #     self.assertEqual(self.stage.hardware_axis, 'X')
    #     self.assertEqual(self.stage.instrument_axis, 'x')
    #     self.assertEqual(self.stage.instrument_to_hardware_axis_map, {'x': 'x'})
    
    # def test_move_relative_mm(self):
    #     # Test relative movement
    #     initial_position = self.stage.position_mm
    #     self.stage.move_relative_mm(0.25, wait=True)
    #     new_position = self.stage.position_mm
    #     self.assertAlmostEqual(new_position, initial_position + 0.25*1000, places=1)

    # def test_move_absolute_mm(self):
    #     # Test absolute movement
    #     target_position = ABSOLUTE_POSITION
    #     self.stage.move_absolute_mm(target_position, wait=True)
    #     self.assertAlmostEqual(self.stage.position_mm, target_position*1000, places=1)
    
    def test_position_mm_getter(self):
        # Test position_mm property getter
        position = self.stage.position_mm
        print('Returned position', position)
        self.assertIsInstance(position, float)
    
    # def test_position_mm_setter(self):
    #     # Test position_mm property setter
    #     self.stage.position_mm = ABSOLUTE_POSITION
    #     while self.stage.is_axis_moving():
    #         continue
    #     self.assertAlmostEqual(self.stage.position_mm, ABSOLUTE_POSITION*1000, places=1)
    
    # def test_halt(self):
    #     # Test halt method (ensure it's safe to call)
    #     self.stage.move_relative_mm(1, wait=False)
    #     time.sleep(2)
    #     self.stage.halt()
    #     # The halt method should execute without throwing an error.
    #     time.sleep(2)
    #     is_moving = self.stage.is_axis_moving()
    #     self.assertFalse(is_moving)
    
    # def test_is_axis_moving(self):
    #     # Test is_axis_moving method
    #     self.stage.move_relative_mm(0.01, wait=False)
    #     is_moving = self.stage.is_axis_moving()
    #     self.assertTrue(is_moving, bool)
    
    # def test_zero_in_place(self):
    #     # Test zero_in_place method
    #     self.stage.zero_in_place()
    #     self.assertAlmostEqual(self.stage.position_mm, 0.0, places=1)
    
    # def test_set_get_backslash(self):
    #     self.stage.backlash_mm = 0
    #     print('STARTING backlash', self.stage.backlash_mm)
    #     self.stage.backlash_mm = 3
    #     print('NEW backlash', self.stage.backlash_mm)
    #     self.assertEqual(self.stage.backlash_mm, 3)
    #     self.stage.backlash_mm = 0
    
    # def test_speed_mm_s_setter_getter(self):
    #     self.stage.speed_mm_s = 1.5
    #     self.assertEqual(self.stage.speed_mm_s, 1.5)
    #     self.stage.speed_mm_s = 0.1
    #     self.assertEqual(self.stage.speed_mm_s, 0.1)

    # def test_accel_ms_setter_getter(self):
    #     self.stage.acceleration_ms = 50
    #     self.assertEqual(self.stage.acceleration_ms, 50)
    #     self.stage.acceleration_ms = 100
    #     self.assertEqual(self.stage.acceleration_ms, 100)

    # def test_travel_limits(self):
    #     print(self.stage.limits_mm)





    #### TESTS BElOW ARE NOT WORKING







    # def test_setup_stage_scan_raises_not_implemented(self):
    #     # Test that setup_stage_scan raises NotImplementedError
    #     with self.assertRaises(NotImplementedError):
    #         self.stage.setup_stage_scan()

    # def test_setup_step_shoot_scan_raises_not_implemented(self):
    #     # Test that setup_step_shoot_scan raises NotImplementedError
    #     with self.assertRaises(NotImplementedError):
    #         self.stage.setup_step_shoot_scan()
    
    # def test_start_raises_not_implemented(self):
    #     # Test that start raises NotImplementedError
    #     with self.assertRaises(NotImplementedError):
    #         self.stage.start()
    
    # def test_close(self):
    #     # Test close method
    #     self.stage.close()
    #     # The close method should execute without throwing an error.
    


    # def test_log_metadata(self):
    #     # Test log_metadata method (just ensure it runs without error)
    #     self.stage.log_metadata()
    #     # The method should execute without throwing an error.
    




if __name__ == '__main__':
    unittest.main()
