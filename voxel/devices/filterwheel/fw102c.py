import logging
import time
from voxel.devices.filterwheel.base import BaseFilterWheel
from voxel.devices.filterwheel.hardware.RS232 import RS232

SWITCH_TIME_S = 6 # estimated timing

class ThorlabsWheel(BaseFilterWheel, RS232):

    def __init__(self, id: str, baudrate: int, filters: dict, port: str, speed: str, **kwargs):
        # Initialize the logger
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.id = id
        self.filters = filters
        
        # Initialize the RS-232 communication
        RS232.__init__(self, port=port, baudrate=baudrate, **kwargs)
        
        # Initialize the filter wheel

        
        # Go to the home filter (assuming value 1 means home position)
        self.filter = next(key for key, value in self.filters.items() if value == 1)
        self.speed = speed

    @property
    def speed(self):
        return self._speed
    
    @speed.setter
    def speed(self, speed_name: str):
        if speed_name == 'high':
            self.sendCommand("speed=1")
            self._speed = "speed=1"
        elif speed_name == 'low':
            self.sendCommand("speed=0")
            self._speed = "speed=0"
        self.waitResponse()

    @property
    def filter(self):
        return self._current_filter

    @filter.setter
    def filter(self, filter_name: str):
        if filter_name not in self.filters:
            self.log.error(f"Filter '{filter_name}' not found in filter list")
            raise ValueError(f"Filter '{filter_name}' not found in filter list")
        
        command = "pos=" + str(self.filters[filter_name])
        print('POSITION', command)
        self.sendCommand(command)
        response = self.waitResponse()
        if response is not None:  
            self._current_filter = filter_name
            self.log.info(f"Filter set to '{filter_name}'")
        else:
            self.log.error(f"Failed to set filter to '{filter_name}'")
            raise RuntimeError(f"Failed to set filter to '{filter_name}'")
        time.sleep(SWITCH_TIME_S)

    def close(self):
        self.shutDown()
        self.log.info("ThorlabsWheel connection closed")

# if (__name__ == "__main__"):
#         filters = {
#             "405": 1,
#             "488": 2,
#             "561": 3,
#             "647": 4,
#             "quad": 5,
#             "ND": 6}
#         baudrate = 115200
#         fWheel = ThorlabsWheel('COM6', baudrate, filters, 'COM6', 'high')
#         print('Filter speed', fWheel.speed)
        
#         fWheel.close()

#
# The MIT License
#
# Copyright (c) 2020 Adam Glaser, University of Washington
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

