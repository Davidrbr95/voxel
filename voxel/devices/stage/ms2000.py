import logging
from voxel.devices.utils.singleton import Singleton
from voxel.devices.stage.base import BaseStage
from voxel.devices.stage.ms2k import MS2000
from time import sleep
from enum import Enum

# TODO: Figure out the appropriate constant for this
STEPS_PER_UM = 10

class ScanPattern(Enum):
    """parameter for specifying scan pattern."""
    RASTER = 0
    SERPENTINE = 1

SCAN_PATTERN = {
    "raster": ScanPattern.RASTER,
    "serpentine": ScanPattern.SERPENTINE,
}


class MS2000ControllerSingleton(MS2000, metaclass=Singleton):
    def __init__(self, com_port, baud_rate=9600):
        super(MS2000ControllerSingleton, self).__init__(com_port, baud_rate)


class Stage(BaseStage):

    def __init__(self, hardware_axis: str, instrument_axis: str, ms2000: MS2000 = None, port: str = None,
                 log_level="INFO"):
        """Connect to hardware.

        :param ms2000: MS2000 instance.
        :param hardware_axis: stage hardware axis.
        :param instrument_axis: instrument hardware axis.
        """
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.log.setLevel(log_level)

        if ms2000 is None and port is None:
            raise ValueError('MS2000 instance and port cannot both be none')

        self.ms2000 = MS2000ControllerSingleton(com_port=port) if ms2000 is None else ms2000
        # self.ms2000.connect_to_serial()
        self._hardware_axis = hardware_axis.upper()
        self._instrument_axis = instrument_axis.lower()
        self.id = self.instrument_axis # does this need to be the serial number
        axis_map = {self.instrument_axis: self.hardware_axis}
        self.log.debug("Remapping axes with the convention "
                       "{'instrument axis': 'hardware axis'} "
                       f"from the following dict: {axis_map}.")
        self.instrument_to_hardware_axis_map = self._sanitize_axis_map(axis_map)
        r_axis_map = dict(zip(axis_map.values(), axis_map.keys()))
        self.hardware_to_instrument_axis_map = self._sanitize_axis_map(r_axis_map)
        self.log.debug(f"New instrument to hardware axis mapping: "
                       f"{self.instrument_to_hardware_axis_map}")
        self.log.debug(f"New hardware to instrument axis mapping: "
                       f"{self.hardware_to_instrument_axis_map}")
        

        # TODO: Not sure how many of these are valid for MS2000 and what their values should be
        self.min_speed_mm_s = 0.001
        self.max_speed_mm_s = 1.000
        self.step_speed_mm_s = 0.01
        self.min_acceleration_ms = 50
        self.max_acceleration_ms = 2000
        self.step_acceleration_ms = 10
        self.min_backlash_mm = 0
        self.max_backlash_mm = 1
        self.step_backlash_mm = 0.01

    def _sanitize_axis_map(self, axis_map: dict):
        sanitized_axis_map = {}
        for axis, t_axis in axis_map.items():
            axis = axis.lower()
            t_axis = t_axis.lower()
            sign = "-" if axis.startswith("-") ^ t_axis.startswith("-") else ""
            sanitized_axis_map[axis.lstrip("-")] = f"{sign}{t_axis.lstrip('-')}"
        return sanitized_axis_map

    def _remap(self, axes: dict, mapping: dict):
        new_axes = {}
        for axis, value in axes.items():
            axis = axis.lower()
            new_axis = mapping.get(axis, axis)
            negative = 1 if new_axis.startswith('-') else 0
            new_axes[new_axis.lstrip('-')] = (-1) ** negative * value
        return new_axes

    def _instrument_to_hardware(self, axes: dict):
        return self._remap(axes, self.instrument_to_hardware_axis_map)

    def _instrument_to_hardware_axis_list(self, *axes):
        axes_dict = {x: 0 for x in axes}
        ms2000_axes_dict = self._instrument_to_hardware(axes_dict)
        return list(ms2000_axes_dict.keys())

    def _hardware_to_instrument(self, axes: dict):
        return self._remap(axes, self.hardware_to_instrument_axis_map)

    def move_relative_mm(self, position: float, wait: bool = True):
        w_text = "" if wait else "NOT "
        self.log.info(f"Relative move by: {self.hardware_axis}={position} mm and {w_text}waiting.")
        self.ms2000.moverel_axis(self.hardware_axis, round(position * 10000))  # Convert mm to 1/10 micron
        if wait:
            self.ms2000.wait_for_device()

    def move_absolute_mm(self, position: float, wait: bool = True):
        w_text = "" if wait else "NOT "
        self.log.info(f"Absolute move to: {self.hardware_axis}={position} mm and {w_text}waiting.")
        self.ms2000.move_axis(self.hardware_axis, round(position * 10000))  # Convert mm to 1/10 micron
        if wait:
            self.ms2000.wait_for_device()

    def setup_stage_scan(self, fast_axis_start_position: float,
                         slow_axis_start_position: float,
                         slow_axis_stop_position: float,
                         frame_count: int, frame_interval_um: float,
                         strip_count: int, pattern: str,
                         ):
        if self.mode == 'stage scan':
            valid_pattern = list(SCAN_PATTERN.keys())
            if pattern not in valid_pattern:
                raise ValueError("pattern must be one of %r." % valid_pattern)
            fast_axis = self.hardware_axis
            slow_axis = next(value for value in self.ms2000.build_config['Motor Axes'] if value != fast_axis)
            slow_axis_second = next(value for value in self.ms2000.build_config['Motor Axes'] if value != fast_axis and value != slow_axis)

            
            # axis_to_card = self.ms2000.axis_to_card
            # exit()

            ## HERE they are getting some code to represent the axis; this code doesnt exist in MS2000
            # fast_card = axis_to_card[fast_axis][0]
            # fast_position = axis_to_card[fast_axis][1]
            # slow_axis = next(
            #     key for key, value in axis_to_card.items() if value[0] == fast_card and value[1] != fast_position)
            # Stop any existing scan. Apply machine coordinate frame scan params.
            
            self.log.debug(f"fast axis start: {fast_axis_start_position},"
                           f"slow axis start: {slow_axis_start_position}")
            self.ms2000.setup_scan(fast_axis, slow_axis, slow_axis_second,
                                     pattern=SCAN_PATTERN[pattern], )
            self.ms2000.scanr(scan_start_mm=fast_axis_start_position,
                                pulse_interval_um=frame_interval_um,
                                num_pixels=frame_count, retrace_speed_percent=None)
            self.ms2000.scanv(scan_start_mm=slow_axis_start_position,
                                scan_stop_mm=slow_axis_stop_position,
                                line_count=strip_count)
    
    def setup_step_shoot_scan(self, *args, **kwargs):
        raise NotImplementedError("Step-shoot scan setup is not supported for MS2000.")

    def start(self):
        if self.mode == 'stage scan':
            self.ms2000.start_scan()

    def close(self):
        self.ms2000.disconnect_from_serial()

    @property
    def position_mm(self):
        ms2000_position_um = self.ms2000.get_position_um(self.hardware_axis)
        return self._hardware_to_instrument({self.hardware_axis: ms2000_position_um}).get(self.instrument_axis, None)

    @position_mm.setter
    def position_mm(self, value):
        self.move_absolute_mm(value, False)

    @property
    def limits_mm(self):
        # Get lower/upper limit in tigerbox frame.
        ms2000_limit_lower = self.ms2000.get_lower_travel_limit(self.hardware_axis)
        ms2000_limit_upper = self.ms2000.get_upper_travel_limit(self.hardware_axis)
        # Convert to sample frame before returning.
        sample_limit_lower = list(self._hardware_to_instrument({self.hardware_axis: ms2000_limit_lower}).values())[0]
        sample_limit_upper = list(self._hardware_to_instrument({self.hardware_axis: ms2000_limit_upper}).values())[0]
        limits = sorted([sample_limit_lower, sample_limit_upper])
        return limits
    
    @property
    def backlash_mm(self):
        ms2000_backlash = self.ms2000.get_backlash(self.hardware_axis)
        return self._hardware_to_instrument({self.hardware_axis: ms2000_backlash}).get(self.instrument_axis, None)
    
    @backlash_mm.setter
    def backlash_mm(self, backlash: float):
        """Set the axis backlash compensation to a set value (0 to disable)."""
        # print(**{self.hardware_axis: backlash})
        self.ms2000.set_backlash(self.hardware_axis, backlash)

    @property
    def speed_mm_s(self):
        ms2000_speed_mm_s = self.ms2000.get_max_speed(self.hardware_axis)
        return self._hardware_to_instrument({self.hardware_axis: ms2000_speed_mm_s}).get(self.instrument_axis, None)
    
    @speed_mm_s.setter
    def speed_mm_s(self, speed: float):
        """Should be set in um"""
        self.ms2000.set_max_speed(self.hardware_axis, speed)  # Convert mm/s to ASI units

    @property
    def acceleration_ms(self):
        ms2000_accl_mm_s = self.ms2000.get_acceleration_ms(self.hardware_axis)
        return self._hardware_to_instrument({self.hardware_axis: ms2000_accl_mm_s}).get(self.instrument_axis, None)
    
    @acceleration_ms.setter
    def acceleration_ms(self, acceleration: float):
        self.ms2000.set_acceleration_ms(self.hardware_axis, acceleration)

    ## MODE NO IDEA WHAT THIS IS
    @property
    def mode(self):
        mode = 'stage scan'
        return mode

    @mode.setter
    def mode(self, mode: str):
        if mode == 'stage scan':
            mode = mode
        else:
            raise NotImplementedError("Mode setter is not implemented for MS2000.")

    def halt(self):
        self.ms2000.send_command("HALT")
        self.ms2000.read_response()

    def is_axis_moving(self):
        return self.ms2000.is_axis_busy(self.hardware_axis)

    def zero_in_place(self):
        self.ms2000.send_command(f"ZERO {self.hardware_axis}")
        self.ms2000.read_response()

    def log_metadata(self):
        self.log.info('MS2000 hardware axis parameters')
        self.log.info("{'instrument axis': 'hardware axis'} "
                      f"{self.instrument_to_hardware_axis_map}.")

    @property
    def hardware_axis(self):
        return self._hardware_axis

    @property
    def instrument_axis(self, ):
        return self._instrument_axis
