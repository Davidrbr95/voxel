import unittest
from voxel.devices.filterwheel.fw102c import ThorlabsWheel 
import sys
import os

# Update sys.path to include the voxel directory if needed
voxel_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'voxel'))
sys.path.append(voxel_path)

class TestThorlabsWheel(unittest.TestCase):

    def setUp(self):
        self.filters = {
            "405": 1,
            "488": 2,
            "561": 3,
            "647": 4,
            "quad": 5,
            "ND": 6
        }
        self.baudrate = 115200
        self.port = 'COM6'
        self.speed = 'high'
        self.fWheel = ThorlabsWheel(self.port, self.baudrate, self.filters, self.port, self.speed)

    def tearDown(self):
        self.fWheel.close()

    def test_initialization(self):
        self.assertEqual(self.fWheel.id, self.port)
        self.assertEqual(self.fWheel.speed, 'speed=1')
        self.assertEqual(self.fWheel.filter, '405')

    def test_set_speed_high(self):
        self.fWheel.speed = 'high'
        self.assertEqual(self.fWheel.speed, 'speed=1')

    def test_set_speed_low(self):
        self.fWheel.speed = 'low'
        self.assertEqual(self.fWheel.speed, 'speed=0')

    def test_set_filter_valid(self):
        self.fWheel.filter = '561'
        self.assertEqual(self.fWheel.filter, '561')

    def test_set_filter_invalid(self):
        with self.assertRaises(ValueError):
            self.fWheel.filter = 'invalid_filter'

  
if __name__ == '__main__':
    unittest.main()
