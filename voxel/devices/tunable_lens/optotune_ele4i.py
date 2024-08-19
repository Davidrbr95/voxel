import logging
import struct
import serial
from voxel.devices.tunable_lens.base import BaseTunableLens
import time
# constants for Optotune EL-E-4i controller
SWITCH_TIME  = 1

MODES = {
    "external": ['MwDA', '>xxx'],
    "internal": ['MwCA', '>xxxBhh'],
}

def crc_16(s):
    crc = 0x0000
    for c in s:
        crc = crc ^ c
        for i in range(0, 8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) > 0 else crc >> 1

    return crc

class TunableLens(BaseTunableLens):

    def __init__(self, port: str):

        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        # (!!) hardcode debug to false
        self.debug = False
        self.tunable_lens = serial.Serial(port=port, baudrate=115200, timeout=1)
        self.tunable_lens.flush()
        # set id to serial number of lens
        self.id = self.send_command('X', '>x8s')[0].decode('ascii')
        # self.current = 0.0 #assumes that tuneable lens starts at zero

    @property
    def mode(self):
        """Get the tunable lens control mode."""
        mode = self.send_command('MMA', '>xxxB')[0]
        print('Mode', mode)
        if mode == 1:
            return 'internal'
        if mode == 5:
            return 'external'

    @mode.setter
    def mode(self, mode: str):
        """Set the tunable lens control mode."""
        print('Set to mode: ', mode)
        valid = list(MODES.keys())
        if mode not in valid:
            raise ValueError("mode must be one of %r." % valid)
        mode_list = MODES[mode]
        self.send_command(mode_list[0], mode_list[1])
        print('Sent commands', mode_list)

    @property
    def current(self):
        """Get the current on lens."""
        print('Current: ', self.current)
    
    @current.setter
    def current(self, current: float):
        """Set the current on the lens."""
        max_current = 293 # mA hardcoded value would be nice if we could read this 
        current_code = round(current/max_current * 4096)
        if not (-4096 <= current_code <= 4096):
            raise ValueError("Current value must be between -4096 and 4096")
        hex_value = format(current_code & 0xFFFF, '04X')
        
        # Split the hexadecimal value into high and low bytes
        high_byte = hex_value[:2]
        low_byte = hex_value[2:]
        # Construct the full command string
        command = f"{self._str2hex('Aw')}{str(high_byte)}{str(low_byte)}{self._str2hex('LH')}"       
        command = bytes.fromhex(command)
        self.send_command(command)
        time.sleep(SWITCH_TIME)
        

    @property
    def signal_temperature_c(self):
        """Get the temperature in deg C."""
        state = {}
        state['Temperature [C]'] = self.send_command(b'TCA', '>xxxh')[0] * 0.0625
        return state

    def send_command(self, command, reply_fmt=None):
        print('start command', command)
        if type(command) is not bytes:
            print('Command is not byte')
            command = bytes(command, encoding='ascii')
            print('new command after ascii enconding', command)

        command = command + struct.pack('<H', crc_16(command))
        if self.debug:
            commandhex = ' '.join('{:02x}'.format(c) for c in command)
            print('{:<50} ¦ {}'.format(commandhex, command))
        print('FULL COMMAND', command)
        self.tunable_lens.write(command)

        if reply_fmt is not None:
            response_size = struct.calcsize(reply_fmt)
            response = self.tunable_lens.read(response_size+4)
            if self.debug:
                responsehex = ' '.join('{:02x}'.format(c) for c in response)
                print('{:>50} ¦ {}'.format(responsehex, response))

            if response is None:
                raise Exception('Expected response not received')
            data, crc, newline = struct.unpack('<{}sH2s'.format(response_size), response)
            if crc != crc_16(data) or newline != b'\r\n':
                raise Exception('Response CRC not correct')

            return struct.unpack(reply_fmt, data)

    def close(self):
        self.tunable_lens.close()
    
    def _str2hex(self, input_string):
        return ''.join(format(ord(c), '02x') for c in input_string)