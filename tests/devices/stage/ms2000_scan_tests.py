from voxel.devices.stage.ms2000 import MS2000 
import unittest

class TestMS2000(unittest.TestCase):

    def setUp(self):
        # Initialize with a real COM port and baud rate
        print('SETUP')
        self.ms2000 = MS2000(com_port='COM5', baud_rate=9600, report=False)
        
    def test_setup_scan(self):
        # Call setup_scan with specific axes and pattern
        print('HERE1')
        self.ms2000.setup_scan(fast_axis='X', slow_axis='Y')
        # If setup is successful, assert the relevant internal variables
        self.assertEqual(self.ms2000._scan_fast_axis, 'X')
        self.assertEqual(self.ms2000._scan_card_addr, '31')  # example expected card address
        # except Exception as e:
        #     self.fail(f"setup_scan raised an exception: {e}")

    # def test_get_axis_id(self):
    #     # Test getting the axis ID
    #     axis_id = self.ms2000.get_axis_id('X')
    #     # Assuming the axis ID should be 1 for X in your setup
    #     self.assertEqual(axis_id, 1)

    # def test_set_cmd_args_and_kwds(self):
    #     # Directly test command setting function
    #     response = self.ms2000._set_cmd_args_ansd_kwds("SCAN", 'X', 'Y', wait=True, card_address=31, F=1)
    #     # Check if the command was processed correctly
    #     self.assertIn('SCAN', response)

    # def test_get_axis_to_card_mapping(self):
    #     build_config = self.ms2000.get_build_config()
    #     mapping = self.ms2000._get_axis_to_card_mapping(build_config)
    #     # Assuming expected mapping based on your device's configuration
    #     expected_mapping = {'X': ('31', 0), 'Y': ('31', 1), 'Z': ('32', 0)}
    #     self.assertEqual(mapping, expected_mapping)
if __name__ == '__main__':
    unittest.main()
