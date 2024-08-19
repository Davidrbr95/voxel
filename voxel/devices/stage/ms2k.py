from voxel.devices.stage.serialport import SerialPort
from enum import Enum
from typing import Union
from functools import cache, wraps
import logging

MM_SCALE = 4
DEFAULT_SPEED_PERCENT = 50

# Decorators
def axis_check(*args_to_skip: str):
    """Ensure that the axis (specified as an arg or kwd) exists.
    Additionally, sanitize all inputs to upper case.
    Parameters specified in the `args_to_skip` are omitted."""
    def wrap(func):
        # wraps needed for sphinx to make docs for methods with this decorator.
        @wraps(func)
        def inner(self, *args, **kwds):
            # Sanitize input to all-uppercase. Filter out specified parameters.
            args = [a.upper() for a in args if a not in args_to_skip]
            kwds = {k.upper(): v for k, v in kwds.items() if k not in args_to_skip}
            # Combine args and kwd names; skip double-adding params specified
            # as one or the other.
            iterable = [a for a in args if a not in kwds] + list(kwds.keys())
            for arg in iterable:
                assert arg.upper() in self.axes, \
                    f"Error. Axis '{arg.upper()}' does not exist"
            return func(self, *args, **kwds)
        return inner
    return wrap

def no_repeated_axis_check(func):
    """Ensure that an axis was specified either as an arg xor as a kwd."""

    @wraps(func)  # Required for sphinx doc generation.
    def inner(self, *args, **kwds):
        # Figure out if any axes was specified twice.
        intersection = {a.upper() for a in args} & \
                       {k.upper() for k, _ in kwds.items()}
        if len(intersection):
            raise SyntaxError("The following axes cannot be specified "
                              "both at the current position and at a specific "
                              f"position: {intersection}.")
        return func(self, *args, **kwds)
    return inner

class ScanState(Enum):
    """Scan states"""
    # http://asiimaging.com/docs/commands/scan
    START = 'S'
    STOP = 'P'
    # More read-only scan states exist, but are not captured here.
    
class ErrorCodes(Enum):
    # Error message responses from the Tiger Controller
    UNKNOWN_CMD = ':N-1'
    UNRECOGNIZED_AXIS_PARAMETER = ':N-2'
    MISSING_PARAMETERS = ':N-3'
    PARAMETER_OUT_OF_RANGE = ':N-4'
    OPERATION_FAILED = ':N-5'
    UNDEFINED_ERROR = ':N-6'
    INVALID_CARD_ADDRESS = ':N-7'
    RESERVED_8 = ':N-8'
    RESERVED_9 = ':N-9'
    RESERVED_10 = ':N-10'
    FILTERWHEEL_RESERVED_11 = ':N-11'
    FILTERWHEEL_RESERVED_12 = ':N-12'
    FILTERWHEEL_RESERVED_13 = ':N-13'
    FILTERWHEEL_RESERVED_14 = ':N-14'
    FILTERWHEEL_RESERVED_15 = ':N-15'
    FILTERWHEEL_RESERVED_16 = ':N-16'
    FILTERWHEEL_RESERVED_17 = ':N-17'
    FILTERWHEEL_RESERVED_18 = ':N-18'
    FILTERWHEEL_RESERVED_19 = ':N-19'
    FILTERWHEEL_RESERVED_20 = ':N-20'
    SERIAL_CMD_HALTED = ':N-21'

class ScanPattern(Enum):
    """parameter for specifying scan pattern."""
    RASTER = 0
    SERPENTINE = 1

class FirmwareModules(Enum):
    SCAN_MODULE = "SCAN MODULE"
    ARRAY_MODULE = "ARRAY MODULE"

class MS2000(SerialPort):
    """
    A utility class for operating the MS2000 from Applied Scientific Instrumentation.
 
    Move commands use ASI units: 1 unit = 1/10 of a micron.
    Example: to move a stage 1 mm on the x axis, use self.moverel(10000)
 
    Manual:
        http://asiimaging.com/docs/products/ms2000
 
    """

    # all valid baud rates for the MS2000
    # these rates are controlled by dip switches
    BAUD_RATES = [9600, 19200, 28800, 115200]

    @staticmethod
    def _reply_to_dict(reply):
        dict_reply = {}
        for line in reply.split('\r'):
            words = line.split(':')
            if len(words) == 2:
                val = words[1].split()
                dict_reply[words[0]] = val
        return dict_reply
    
    def __init__(self, com_port: str, baud_rate: int=115200, report: str=True):
        super().__init__(com_port, baud_rate, report)
        # validate baud_rate input
        if baud_rate in self.BAUD_RATES:
            self.baud_rate = baud_rate
        else:
            raise ValueError("The baud rate is not valid. Valid rates: 9600, 19200, 28800, or 115200.")
        print('IN MS2000 class')
        self.connect_to_serial()
        self.skipped_replies = 0
        self.log = logging.getLogger(__name__)
        self.build_config = self.get_build_config()
        self.ordered_axes = self.build_config['Motor Axes']
        self.axis_to_type = self._get_axis_to_type_mapping(self.build_config)
        self.ordered_axes = [ax for ax in self.ordered_axes if not ax.isnumeric()]
        self.axes = set(self.ordered_axes)

        # Internal State Tracking to issue moves correctly.
        self._scan_card_addr = None  # card address on which the scan axes exist.
        self._scan_fast_axis = None
        self._array_scan_card_addr = None  # card address on which the array scan axes exist.
        self._last_rel_move_axes = []  # axes specified in previous MOVEREL
        self._rb_axes = []  # axes specified as movable by ring buffer moves.
        # self.axis_to_card = self._get_axis_to_card_mapping(build_config)

    # ------------------------------ #
    #     MS2000 Serial Commands     #
    # ------------------------------ #
    def get_build_config(self):
        """return the configuration of the Tiger Controller.

        :return: a dict that looks like:

        .. code-block:: python

            {'Axis Addr': [],
             'Axis Props': ['74', '10', '2', etc.], # these are positions
             'Axis Types': ['x', 'x', 'z', etc],
             'Hex Addr': [],
             'Motor Axes': ['X', 'Y', 'Z', etc]}

        """
        # reply = self.send(f"BU X\r")
        #TODO: how to avoid hardcoding. The send command wasn't working for MS2000
        build_config = {'Motor Axes': ['X', 'Y', 'Z', 'F'],
         'Axis Types': ['x', 'x', 'z', 'z'],
         }
        # Reply is formatted in such a way that it can be put into dict form.
        return build_config


    @staticmethod
    def _get_axis_to_type_mapping(build_config: dict):
        """parse a build configuration dict to get axis-to-type relationship.

        :return: a dict that looks like
            ``{<axis>: <type>), etc.}``

        .. code-block:: python

            # return type looks like:
            {'X': 'X',
             'V': 'b'}

        """
        axis_to_type = {}
        curr_card_index = {c: 0 for c in set(build_config['Axis Types'])}
        for axis, axis_type in zip(build_config['Motor Axes'],
                                  build_config['Axis Types']):
            axis_to_type[axis] = axis_type
        return axis_to_type
    
    @staticmethod
    def check_reply_for_errors(reply: str):
        """Check if reply contains an error code; returns None or throws exception."""
        error_enum = None
        try:
            # throws a value error on failure
            error_enum = ErrorCodes(reply.rstrip('\r\n'))
            raise SyntaxError(f"Error. TigerController replied with error "
                              f"code: {str(error_enum)}.")
        except ValueError:
            pass

    def setup_scan(self, fast_axis: str, slow_axis: str, slow_axis_second: str,
                   pattern: ScanPattern = ScanPattern.RASTER,
                   wait: bool = True):

        self._scan_fast_axis = fast_axis
        kwds = {}
        for i in self.ordered_axes:
            if i == fast_axis:
                kwds[i] = 1
            if i == slow_axis:
                kwds[i] = 2
            if i == slow_axis_second:
                kwds[i] = 0
        
        if pattern is not None:
            kwds['F'] = pattern.value

        # Firmware check.
        # self._has_firmware(fast_axis, FirmwareModules.SCAN_MODULE)
        
        self._set_cmd_args_and_kwds("SCAN", **kwds, wait=wait,
                            card_address=self._scan_card_addr)
        
    def scanr(self, scan_start_mm: float, pulse_interval_um: float,
              scan_stop_mm: float = None, num_pixels: int = None, 
              retrace_speed_percent: int = DEFAULT_SPEED_PERCENT,
              wait: bool = True):
        """Setup the fast scanning axis start position and distance OR start
        position and number of pixels. To setup a scan, either scan_stop_mm
        or num_pixels must be specified, but not both.
        See ASI
        `SCANR Implementation <http://asiimaging.com/docs/commands/scanr>`_
        for more details.

        Note: :meth:`setup_scan` must be run first.

        :param scan_start_mm: absolute position to start the scan.
        :param pulse_interval_um: spacing (in [um]) between output pulses.
            i.e: a pulse will output every `pulse_interval_um`. Note that this
            value will be rounded to the nearest encoder tick. To set scan
            spacing to an exact encoder tick value, check
            :meth:`get_encoder_ticks_per_mm`. The logger will log a
            warning if the actual value in [um] was rounded.
        :param scan_stop_mm: absolute position to stop the scan. If
            unspecified, `num_pixels` is required.
        :param num_pixels:  number of pixels to output a pulse for. If
            unspecified, `scan_stop_mm` is required.
        :param retrace_speed_percent: percentage (0-100) of how fast to
            backtract to the scan start position after finishing a scan.
        :param wait: wait until the reply has been received.

        """

        # We can specify scan_stop_mm or num_pixels but not both (i.e: XOR).
        if not ((scan_stop_mm is None) ^ (num_pixels is None)):
            raise SyntaxError("Exclusively either scan_stop_mm or num_pixels "
                              "(i.e: one or the other, but not both) options "
                              "must be specified.")
        # Confirm that fast and slow axes have been defined.
        # if self._scan_card_addr is None:
        #     raise RuntimeError("Cannot infer the card address for which to "
        #                        "apply the sttings. setup_scan must be run "
        #                        "first.")

        ENC_TICKS_PER_MM = self.get_encoder_ticks_per_mm(self._scan_fast_axis)
        pulse_interval_enc_ticks_f = ENC_TICKS_PER_MM * pulse_interval_um * 1e-3
        pulse_interval_enc_ticks = round(pulse_interval_enc_ticks_f)
        if pulse_interval_enc_ticks != pulse_interval_enc_ticks_f:
            rounded_pulse_interval_um = \
                pulse_interval_enc_ticks/(ENC_TICKS_PER_MM * 1e-3)
            self.log.warning(f"Requested scan {self._scan_fast_axis}-stack "
                           f"spacing: {pulse_interval_um:1f}[um]. Actual "
                           f"spacing: {rounded_pulse_interval_um:.1f}[um].")
        # Parameter setup.
        kwds = {
            'X': round(scan_start_mm, MM_SCALE),
            'Z': pulse_interval_enc_ticks}
        if scan_stop_mm is not None:
            kwds['Y'] = round(scan_stop_mm, MM_SCALE)
        if num_pixels is not None:
            kwds['F'] = num_pixels
        self._set_cmd_args_and_kwds("SCANR", **kwds, wait=wait,
                                    card_address=self._scan_card_addr)

    def scanv(self, scan_start_mm: float, scan_stop_mm: float, line_count: int,
              overshoot_time_ms: int = None, overshoot_factor: float = None,
              wait: bool = True):
        """Setup the slow scanning axis.

        Behavior is equivalent to:
        ``numpy.linspace(scan_start_mm, scan_stop_mm, line_count, endpoint=False)``.
        See ASI
        `SCANV Implementation <http://asiimaging.com/docs/products/serial_commands#commandscanv_nv>`_
        for more details.

        Note: :meth:`setup_scan` must be run first.

        :param scan_start_mm: absolute position to start the scan in the slow
            axis dimension.
        :param scan_stop_mm: absolute position to stop the scan in the slow
            axis dimension.
        :param line_count: how many lines to scan on the slow axis.
        :param overshoot_time_ms: extra time (in ms) for the stage to settle
            (in addition to the current time set by the ``AC`` command.)
        :param overshoot_factor: scalar multiplier (default: 1.0) to add
            distance to the start and stop of a scan before initiating the
            starting of pulses.
        :param wait: wait until the reply has been received.
        """
        # Confirm that fast and slow axes have been defined.
        # if self._scan_card_addr is None:
        #     raise RuntimeError("Cannot infer the card address for which to "
        #                        "apply the sttings. setup_scan must be run "
        #                        "first.")
        kwds = {
            'X': round(scan_start_mm, MM_SCALE),
            'Y': round(scan_stop_mm, MM_SCALE),
            'Z': line_count}
        # if overshoot_time_ms is not None:
        #     kwds['F'] = round(overshoot_time_ms)
        if overshoot_factor is not None:
            kwds['F'] = round(overshoot_factor, MM_SCALE)
        self._set_cmd_args_and_kwds("SCANV", **kwds, wait=wait,
                                    card_address=self._scan_card_addr)
        
    def start_scan(self, wait: bool = True):
        """Start a scan that has been previously setup with
        :meth:`scanr` :meth:`scanv` and :meth:`setup_scan`."""
        # Clear the card address for which the scan settings have been applied.
        # Use the previously specified card address.
        # if self._scan_card_addr is None:
        #     raise RuntimeError("Cannot infer the card address for which to "
        #                        "apply the sttings. setup_scan must be "
        #                        "run first.")
        # card_address = self._scan_card_addr
        # Clear card address for which the scan settings were specified.
        self._scan_card_addr = None
        self._scan_fast_axis = None
        self._set_cmd_args_and_kwds("SCAN", ScanState.START.value,
                                    wait=wait, card_address=None)
    @axis_check()
    @cache
    def get_encoder_ticks_per_mm(self, axis: str):
        """Get <encoder ticks> / <mm of travel> for the specified axis.
        Implements `CNTS <http://asiimaging.com/docs/commands/CNTS>`_ command.
        """
        # TODO: can this function accept an arbitrary number of args?
        # FIXME: use _get_axis_value
        axis_str = f" {axis.upper()}?"
        cmd_str = "CNTS" + axis_str + '\r'
        self.send_command(cmd_str)
        response = self.read_response()
        return float(response.split('=')[-1].split()[0])
    
    def _set_cmd_args_and_kwds(self, cmd: str, *args: str, wait: bool = True,
                               card_address: int = None,
                               **kwds: Union[float, int]):
        """Flag a parameter or set a parameter with a specified value.

        .. code-block:: python

            box._set_cmd_args_and_kwds(Cmds.SETHOME, 'x', 'y', 'z')
            box._set_cmd_args_and_kwds(Cmds.SETHOME, 'x', y=10, z=20.5)
            box._set_cmd_args_and_kwds(Cmds.SETHOME, y=10, z=20.5)

        """
        card_addr_str = f"{card_address}" if card_address is not None else ""
        args_str = "".join([f" {a.upper()}" for a in args])
        kwds_str = "".join([f" {a.upper()}={v}" for a, v in kwds.items()])
        cmd_str = f"{card_addr_str}{cmd}{args_str}{kwds_str}\r"
        # print('CMD', cmd_str)
        # exit()
        self.send_command(cmd_str)
        response = self.read_response()
        return response
    
    @axis_check()
    def get_axis_id(self, axis: str):
        """Get the hardware's axis id for a given axis.

        Note: some methods require that the axis is specified by id.

        :param axis: the axis of interest.
        :return: the axis id of the specified axis.
        """
        cmd_str = "Z2B"+ f" {axis.upper()}?" + '\r'
        self.send_command(cmd_str)
        reply = self.read_response()
        return int(reply.split('=')[-1])
    
    def _has_firmware(self, card_address, *modules: FirmwareModules):
        """Raise RuntimeError if the specified card does not have the specified
        firmware.

        :param card_address: the card hex address.
        :param *modules: any number of modules specified as
            :obj:`~tigerasi.device_codes.FirmwareModules`.
        """
        missing_modules = []
        for module in modules:
            if module.value not in self._card_modules[card_address]:
                missing_modules.append(module.value)
        if len(missing_modules):
            raise RuntimeError(f"Error: card 0x{card_address} cannot execute "
                               f"the specified command because it is missing "
                               f"the following firmware modules: "
                               f"{missing_modules}")

    def moverel(self, x: int=0, y: int=0, z: int=0) -> None:
        """Move the stage with a relative move."""
        self.send_command(f"MOVREL X={x} Y={y} Z={z}\r")
        self.read_response()
 
    def moverel_axis(self, axis: str, distance: int) -> None:
        """Move the stage with a relative move."""
        self.send_command(f"MOVREL {axis}={distance}\r")
        self.read_response()
 
    def move(self, x: int=0, y: int=0, z: int=0) -> None:
        """Move the stage with an absolute move."""
        self.send_command(f"MOVE X={x} Y={y} Z={z}\r")
        self.read_response()
 
    def move_axis(self, axis: str, distance: int) -> None:
        """Move the stage with an absolute move."""
        self.send_command(f"MOVE {axis}={distance}\r")
        self.read_response()
 
    def set_max_speed(self, axis: str, speed:int) -> None:
        """Set the speed on a specific axis. Speed is in mm/s."""
        print('SENDINGGGGGGGGGGGGGGGGGGGGGGGGGGG', f"SPEED {axis}={speed}\r")
        self.send_command(f"SPEED {axis}={speed}\r")
        response = self.read_response()
        print('RESPONSE', response)
    
    def get_max_speed(self, axis: str):
        """Get the speed on a specific axis. Speed is in mm/s."""
        self.send_command(f"SPEED {axis}?\r")
        response = self.read_response()
        return float(response.split(" ")[1].split("=")[1])
        
    def get_position(self, axis: str) -> int:
        """Return the position of the stage in ASI units (tenths of microns)."""
        self.send_command(f"WHERE {axis}\r")
        response = self.read_response()
        return int(response.split(" ")[1])
 
    def get_position_um(self, axis: str) -> float:
        """Return the position of the stage in microns."""
        self.send_command(f"WHERE {axis}\r")
        response = self.read_response()
        return float(response.split(" ")[1])/10.0
    
    def get_backlash(self, axis: str):
        """Return the backslash of the stage in mm."""
        self.send_command(f"B {axis}?\r")
        response = self.read_response()
        return float(response.split(" ")[0].split('=')[1])
    
    def set_backlash(self, axis: str, backlash:float):
        """Return the backslash of the stage in mm."""
        self.send_command(f"B {axis}={backlash}\r")
        self.read_response()
        return {axis: backlash}
    
    def get_acceleration_ms(self, axis: str):
        """Return the backslash of the stage in ms."""
        self.send_command(f"ACCEL {axis}?\r")
        cmd =f"ACCEL {axis}?\r"
        response = self.read_response()
        self.log.info(f"COMMAND: {cmd} RESPONSE: {response}")
        return float(response.split(" ")[0].split('=')[1])
    
    def set_acceleration_ms(self, axis: str, acceleration: float):
        """Return the backslash of the stage in ms."""
        self.send_command(f"ACCEL {axis}={acceleration}\r")
        self.read_response()

    def get_lower_travel_limit(self, axis:str):
        self.send_command(f"SL {axis}?\r")
        response = self.read_response()
        return response.split(" ")[1].split("=")[1]

    def get_upper_travel_limit(self, axis:str):
        self.send_command(f"SU {axis}?\r")
        response = self.read_response()
        return response.split(" ")[1].split("=")[1]
 
    # ------------------------------ #
    #    MS2000 Utility Functions    #
    # ------------------------------ #
 
    def is_axis_busy(self, axis: str) -> bool:
        """Returns True if the axis is busy."""
        self.send_command(f"RS {axis}?\r")
        return "B" in self.read_response()
 
    def is_device_busy(self) -> bool:
        """Returns True if any axis is busy."""
        self.send_command("/")
        return "B" in self.read_response()
 
    def wait_for_device(self, report: bool = False) -> None:
        """Waits for the all motors to stop moving."""
        if not report:
            print("Waiting for device...")
        temp = self.report
        self.report = report
        busy = True
        while busy:
            busy = self.is_device_busy()
        self.report = temp

    @staticmethod
    def _get_axis_to_card_mapping(build_config: dict):
        """parse a build configuration dict to get axis-to-card relationship.

        :return: a dict that looks like
            ``{<axis>: (<hex_address>, <card_index>)), etc.}``

        .. code-block:: python

            # return type looks like:
            {'X': (31, 0),
             'Y': (31, 1)}

        """
        axis_to_card = {}
        curr_card_index = {c: 0 for c in set(build_config['Hex Addr'])}
        for axis, hex_addr in zip(build_config['Motor Axes'],
                                  build_config['Hex Addr']):
            card_index = curr_card_index[hex_addr]
            axis_to_card[axis] = (hex_addr, card_index)
            curr_card_index[hex_addr] = card_index + 1
        return axis_to_card
