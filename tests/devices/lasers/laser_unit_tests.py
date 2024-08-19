import unittest
from voxel.devices.lasers.cobolt import SkyraLaser 
import unittest
import time

class TestSkyraLaser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # This setup runs once for the entire test case, assuming the laser is connected
        cls.coefficients = {
            0: 0,
            1: 1
        }
        cls.laser = SkyraLaser(
            id="28674",
            port="COM8",
            prefix="1",  # Using a valid prefix ['1', '2', '3', '4']
            max_power_mw=50.0,
            min_current_ma=0.0,
            max_current_ma=100.0,
            coefficients=cls.coefficients
        )

    @classmethod
    def tearDownClass(cls):
        # This will close the laser connection after all tests have run
        cls.laser.close()

    def test_enable(self):
        self.laser.modulation_mode = 'off'
        self.laser.enable()
        time.sleep(5)
        self.assertEqual('1', self.laser.check_status())
    
    def test_enable_disable(self):
        self.laser.enable()
        time.sleep(5)
        self.laser.disable()
        time.sleep(2)
        self.assertEqual('0', self.laser.check_status())
       
    def test_modulation_mode_setter_getter_constant_power(self):
        self.laser.modulation_mode = 'off'
        mode = self.laser.modulation_mode
        self.assertEqual(mode, 'off')

    def test_modulation_mode_setter_getter_analog(self):
        self.laser.modulation_mode = 'analog'
        mode = self.laser.modulation_mode
        self.assertEqual(mode, 'analog')

    def test_modulation_mode_setter_getter_digital(self):
        self.laser.modulation_mode = 'digital'
        mode = self.laser.modulation_mode
        self.assertEqual(mode, 'digital')
 
    def test_power_setpoint_mw_getter(self):
        # This test is for contant power
        self.laser.enable()
        time.sleep(5)
        self.assertTrue(0 <= self.laser.power_setpoint_mw <= 50)
        
    def test_power_setpoint_mw_setter_with_modulation_off(self):
        self.laser.enable()
        time.sleep(5)
        self.laser.modulation_mode = 'off'
        self.laser.power_setpoint_mw = 5
        time.sleep(5)
        self.assertEqual(self.laser.power_setpoint_mw, 5)

    def test_get_actual_power(self):
        self.laser.enable()
        time.sleep(5)
        self.laser.power_setpoint_mw = 5
        time.sleep(5)
        self.assertAlmostEqual(self.laser.power_mw, 5, 0.1)

    # def test_power_setpoint_mw_setter_with_modulation_on(self):
    #     self.assertIn(self.laser._prefix, ['1', '2', '3', '4'])  # Check that prefix is valid
    #     self.laser.modulation_mode = 'analog'
    #     self.laser.power_setpoint_mw = 50
    #     # Assuming some method to verify that the current setpoint was set correctly
    #     self.assertEqual(self.laser._current_setpoint, 50)

    # def test_modulation_mode_setter(self):
    #     self.assertIn(self.laser._prefix, ['1', '2', '3', '4'])  # Check that prefix is valid
    #     self.laser.modulation_mode = 'analog'
    #     self.assertEqual(self.laser.modulation_mode, 'analog')

    # def test_close(self):
    #     self.assertIn(self.laser._prefix, ['1', '2', '3', '4'])  # Check that prefix is valid
    #     self.laser.close()
    #     # Assuming some method to verify that the laser is disconnected
    #     self.assertFalse(self.laser._inst.is_connected())

    # def test_max_power_when_constant_current_on(self):
    #     self.assertIn(self.laser._prefix, ['1', '2', '3', '4'])  # Check that prefix is valid
    #     self.laser._inst.constant_current = 'ON'
    #     max_power = self.laser.max_power
    #     expected_power = int(round(100))  # for x=100 in coefficients_curve
    #     self.assertEqual(max_power, expected_power)

    # def test_max_power_when_constant_current_off(self):
    #     self.assertIn(self.laser._prefix, ['1', '2', '3', '4'])  # Check that prefix is valid
    #     self.laser._inst.constant_current = 'OFF'
    #     max_power = self.laser.max_power
    #     self.assertEqual(max_power, int(self.laser._max_power_mw))

if __name__ == '__main__':
    unittest.main()
