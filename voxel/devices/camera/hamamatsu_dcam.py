import logging
import time
from voxel.devices.utils.singleton import Singleton
from voxel.devices.camera.base import BaseCamera
from voxel.devices.camera.sdks.dcam.dcam import *
from voxel.descriptors.deliminated_property import DeliminatedProperty
import ctypes
import ctypes.util
import traceback

# DCAM4 API.
DCAMERR_ERROR = 0
DCAMERR_NOERROR = 1

DCAMPROP_ATTR_HASVALUETEXT = int("0x10000000", 0)
DCAMPROP_ATTR_READABLE = int("0x00010000", 0)
DCAMPROP_ATTR_WRITABLE = int("0x00020000", 0)

DCAMPROP_OPTION_NEAREST = int("0x80000000", 0)
DCAMPROP_OPTION_NEXT = int("0x01000000", 0)
DCAMPROP_OPTION_SUPPORT = int("0x00000000", 0)

DCAMPROP_TYPE_MODE = int("0x00000001", 0)
DCAMPROP_TYPE_LONG = int("0x00000002", 0)
DCAMPROP_TYPE_REAL = int("0x00000003", 0)
DCAMPROP_TYPE_MASK = int("0x0000000F", 0)

DCAMCAP_STATUS_ERROR = int("0x00000000", 0)
DCAMCAP_STATUS_BUSY = int("0x00000001", 0)
DCAMCAP_STATUS_READY = int("0x00000002", 0)
DCAMCAP_STATUS_STABLE = int("0x00000003", 0)
DCAMCAP_STATUS_UNSTABLE = int("0x00000004", 0)

DCAMWAIT_CAPEVENT_FRAMEREADY = int("0x0002", 0)
DCAMWAIT_CAPEVENT_STOPPED = int("0x0010", 0)

DCAMWAIT_RECEVENT_MISSED = int("0x00000200", 0)
DCAMWAIT_RECEVENT_STOPPED = int("0x00000400", 0)
DCAMWAIT_TIMEOUT_INFINITE = int("0x80000000", 0)

DCAM_DEFAULT_ARG = 0

DCAM_IDSTR_MODEL = int("0x04000104", 0)

DCAMCAP_TRANSFERKIND_FRAME = 0

DCAMCAP_START_SEQUENCE = -1
DCAMCAP_START_SNAP = 0

DCAMBUF_ATTACHKIND_FRAME = 0

BUFFER_SIZE_MB = 6000
# BUFFER_SIZE_MB = 50000

# ODO ring-buffer memory scales with scan length / nominal um-per-frame sampling.
# The current ODO sampling is configured in Control/odo_calibration.yaml.

# subarray parameter values
SUBARRAY_OFF = 1
SUBARRAY_ON = 2
GENTL_INFINITE = 18446744073709551615

# dcam properties dict for convenience in calls
PROPERTIES = {
    "exposure_time": 2031888,  # 0x001F0110, R/W, sec, "EXPOSURE TIME"
    "sensor_mode": 4194832,  # 0x00400210, R/W, mode,  "SENSOR MODE"
    "binning": 4198672,  # 0x00401110, R/W, mode, "BINNING"
    "readout_direction": 4194608,  # 0x00400130, R/W, mode,   "READOUT DIRECTION"
    "trigger_active": 1048864,  # 0x00100120, R/W, mode,   "TRIGGER ACTIVE"
    "trigger_mode": 1049104,  # 0x00100210, R/W, mode,    "TRIGGER MODE"
    "trigger_polarity": 1049120,  # 0x00100220, R/W, mode, "TRIGGER POLARITY"
    "trigger_source": 1048848,  # 0x00100110, R/W, mode,   "TRIGGER SOURCE"
    "line_interval": 4208720,  # 0x00403850, R/W, sec,  # "INTERNAL LINE INTERVAL"
    "image_width": 4325904,  # 0x00420210, R/O, long, "IMAGE WIDTH"
    "image_height": 4325920,  # 0x00420220, R/O, long,    "IMAGE HEIGHT"
    "subarray_hpos": 4202768,  # 0x00402110, R/W, long,    "SUBARRAY HPOS"
    "subarray_hsize": 4202784,  # 0x00402120, R/W, long,   "SUBARRAY HSIZE"
    "subarray_vpos": 4202800,  # 0x00402130, R/W, long,    "SUBARRAY VPOS"
    "subarray_vsize": 4202816,  # 0x00402140, R/W, long,   "SUBARRAY VSIZE"
    "subarray_mode": 4202832,  # 0x00402150, R/W, mode,    "SUBARRAY MODE"
    "pixel_type": 4326000,  # 0x00420270, R/W, DCAM_PIXELTYPE,   # "IMAGE PIXEL TYPE"
    "sensor_temperature": 2097936,  # 0x00200310, R/O, celsius,"SENSOR TEMPERATURE",
    "defectcorrect_mode": 4653072, # 0x00470010, R/W, mode,  "DEFECT CORRECT MODE"
    "readoutspeed": 4194576,  # 0x00400110, R/W, long,    "READOUT SPEED"
    "internaltrigger_handling": 1049200,
}

# generate valid pixel types by querying dcam
# should be of the form
# {"mono8": DCAM_PIXELTYPE.MONO8,
#  "mono12": DCAM_PIXELTYPE.MONO12,
#  "mono16": DCAM_PIXELTYPE.MONO16 ...
# }
PIXEL_TYPES = dict()

# generate valid binning by querying dcam
# should be of the form
# {"1x1": 1,
#  "2x2": 2,
#  "4x4": 4 ...
# }
BINNING = dict()

# full dcam trigger modes mapping
# NORMAL = 1
# PIV = 3
# START = 6
# full dcam trigger sources mapping
# INTERNAL = 1
# EXTERNAL = 2
# SOFTWARE = 3
# MASTERPULSE = 4
# full dcam trigger polarity mapping
# NEGATIVE = 1
# POSITIVE = 2
# full dcam trigger active mapping
# EDGE = 1
# LEVEL = 2
# SYNCREADOUT = 3
# POINT = 4

# generate valid triggers by querying dcam
# full dcam trigger modes mapping
# NORMAL = 1
# PIV = 3
# START = 6
# full dcam trigger sources mapping
# INTERNAL = 1
# EXTERNAL = 2
# SOFTWARE = 3
# MASTERPULSE = 4
# full dcam trigger polarity mapping
# NEGATIVE = 1
# POSITIVE = 2
# full dcam trigger active mapping
# EDGE = 1
# LEVEL = 2
# SYNCREADOUT = 3
# POINT = 4
TRIGGERS = {
    "mode": dict(),
    "source": dict(),
    "polarity": dict(), 
    "active": dict()
}

# generate valid sensor modes by querying dcam
# full dcam sensor modes mapping
# AREA = 1
# LINE = 3
# TDI = 4
# TDI_EXTENDED = 10
# PROGRESSIVE = 12
# SPLITVIEW = 14
# DUALLIGHTSHEET = 16
# PHOTONNUMBERRESOLVING = 18
# WHOLELINES = 19
SENSOR_MODES = dict()

# generate valid readout directions by querying dcam
# full dcam readout directions  mapping
# FORWARD = 1
# BACKWARD = 2
# BYTRIGGER = 3
# DIVERGE = 5
# FORWARDBIDIRECTION = 6
# REVERSEBIDIRECTION = 7
READOUT_DIRECTIONS = dict()

# singleton wrapper around Dcamapi
class DcamapiSingleton(Dcamapi, metaclass=Singleton):
    def __init__(self):
        super(DcamapiSingleton, self).__init__()

class Camera(BaseCamera):

    def __init__(self, id: str):
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.id = str(id) # convert to string incase serial # is entered as int
        # Producer can use this to keep driver buffers allocated across tiles.
        self.persistent_prepare_enabled = True
        self._latest_frame = None
        self.last_frame_number = 0 
        self.number_image_buffers = 0
        self.buffer_size_frames = 0
        self.max_backlog = 0
        self.buffer_index = 0
        self._buffers_allocated = False
        DcamapiSingleton.init()
        print('Starting camera initialization')
        if True:#DcamapiSingleton.init() is not False:
            num_cams = DcamapiSingleton.get_devicecount()
            for cam in range(0, num_cams):
                dcam = Dcam(cam)
                cam_id = dcam.dev_getstring(DCAM_IDSTR.CAMERAID)
                if cam_id.replace("S/N: ","") == self.id:
                    self.log.info(f"camera found for S/N: {self.id}")
                    self.dcam = dcam
                    self.cam_num = cam
                    # open camera
                    self.dcam.dev_open()
                    break

            if 'dcam' in locals():
                del dcam
        else:
            self.log.error('DcamapiSingleton.init() fails with error {}'.format(DCAMERR(DcamapiSingleton.lasterr()).name))
        # initialize parameter values
        # self._update_parameters()


    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def exposure_time_ms(self):
        # us to ms conversion
        return self.dcam.prop_getvalue(PROPERTIES["exposure_time"])*1000

    @exposure_time_ms.setter
    def exposure_time_ms(self, exposure_time_ms: float):
        self.dcam.prop_setvalue(PROPERTIES["exposure_time"], exposure_time_ms / 1000)
        self.log.info(f"exposure time set to: {exposure_time_ms} ms")
        # refresh parameter values
        self._update_parameters()

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def width_px(self):
        return int(self.dcam.prop_getvalue(PROPERTIES["subarray_hsize"]))

    @width_px.setter
    def width_px(self, value: int):

        # reset offset to (0,0)
        self.dcam.prop_setvalue(PROPERTIES["subarray_hpos"], 0)

        self.dcam.prop_setvalue(PROPERTIES["subarray_hsize"], value)

        centered_offset_px = round((self.max_width_px / 2 - value / 2) / self.step_width_px) * self.step_width_px
        self.dcam.prop_setvalue(PROPERTIES["subarray_hpos"], centered_offset_px)
        self.log.info(f"width set to: {value} px")
        # refresh parameter values
        self._update_parameters()

    @property
    def width_offset_px(self):
        return int(self.dcam.prop_getvalue(PROPERTIES["subarray_hpos"]))
    
    @width_offset_px.setter
    def width_offset_px(self, value: int):
        # print('Setting', value)
        self.dcam.prop_setvalue(PROPERTIES["subarray_hpos"], value)   

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def height_px(self):
        # print('Geetting height_px', int(self.dcam.prop_getvalue(PROPERTIES["subarray_vsize"])))
        return int(self.dcam.prop_getvalue(PROPERTIES["subarray_vsize"]))

    @height_px.setter
    def height_px(self, value: int):

        # reset offset to (0,0)
        self.dcam.prop_setvalue(PROPERTIES["subarray_vpos"], 0)

        self.dcam.prop_setvalue(PROPERTIES["subarray_vsize"], value)

        centered_offset_px = round((self.max_height_px / 2 - value / 2) / self.step_height_px) * self.step_height_px
        # print('Centerd offset heigh: ', centered_offset_px)
        self.dcam.prop_setvalue(PROPERTIES["subarray_vpos"], centered_offset_px)
        self.log.info(f"height set to: {value} px")
        # refresh parameter values
        self._update_parameters()

    @property
    def height_offset_px(self):
        # print('Check heigh offset', int(self.dcam.prop_getvalue(PROPERTIES["subarray_vpos"])))
        return int(self.dcam.prop_getvalue(PROPERTIES["subarray_vpos"]))

    @height_offset_px.setter
    def height_offset_px(self, value: int):
        # print('Setting', value)
        self.dcam.prop_setvalue(PROPERTIES["subarray_vpos"], value)   
        time.sleep(0.1)
    
    @property
    def internaltrigger_handling(self):
        return int(self.dcam.prop_getvalue(PROPERTIES["internaltrigger_handling"]))

    @internaltrigger_handling.setter
    def internaltrigger_handling(self, value: int):
        self.dcam.prop_setvalue(PROPERTIES["internaltrigger_handling"], value)   
        time.sleep(0.1)

    @property
    def pixel_type(self):
        pixel_type = self.dcam.prop_getvalue(PROPERTIES["pixel_type"])
        # invert the dictionary and find the abstracted key to output
        print(f"Looking up pixel_type, current raw value: {pixel_type}")
        if not PIXEL_TYPES:
            try:
                self._query_pixel_types()
            except Exception:
                pass
        for key, value in PIXEL_TYPES.items():
            try:
                if int(value) == int(pixel_type):
                    return key
            except Exception:
                if value == pixel_type:
                    return key
        fallback = f"unknown_{pixel_type}"
        self.log.warning(f"unmapped pixel_type raw value: {pixel_type}; returning {fallback}")
        return fallback

    @pixel_type.setter
    def pixel_type(self, pixel_type_bits: str):

        valid = list(PIXEL_TYPES.keys())
        if pixel_type_bits not in valid:
            raise ValueError("pixel_type_bits must be one of %r." % valid)

        self.dcam.prop_setvalue(PROPERTIES["pixel_type"], PIXEL_TYPES[pixel_type_bits])
        self.log.info(f"pixel type set to: {pixel_type_bits}")
        # refresh parameter values
        self._update_parameters()

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def line_interval_us(self):
        line_interval_s = self.dcam.prop_getvalue(PROPERTIES["line_interval"])
        # convert from s to ms
        return line_interval_s*1e6

    @line_interval_us.setter
    def line_interval_us(self, line_interval_us: float):

        # convert from us to s
        self.dcam.prop_setvalue(PROPERTIES["line_interval"], line_interval_us/1e6)
        self.log.info(f"line interval set to: {line_interval_us} us")
        # refresh parameter values
        self._update_parameters()

    @property
    def frame_time_ms(self):
        if 'light sheet' in self.sensor_mode:
            return (self.line_interval_us * self.height_px)/1000 + self.exposure_time_ms
        else:
            return (self.line_interval_us * self.height_px/2)/1000 + self.exposure_time_ms

    @property
    def trigger(self):

        source = self.dcam.prop_getvalue(PROPERTIES["trigger_source"])
        mode = self.dcam.prop_getvalue(PROPERTIES["trigger_mode"])
        polarity = self.dcam.prop_getvalue(PROPERTIES["trigger_polarity"])
        active = self.dcam.prop_getvalue(PROPERTIES["trigger_active"])

        def _decode(raw_value, table: dict, field_name: str):
            reverse = {v: k for k, v in table.items()}
            if raw_value in reverse:
                return reverse[raw_value]
            # Some SDK states may report bool-like or float-like values; coerce defensively.
            try:
                if isinstance(raw_value, bool):
                    coerced = int(raw_value)
                    if coerced in reverse:
                        return reverse[coerced]
                if isinstance(raw_value, (int, float)):
                    as_int = int(raw_value)
                    if as_int in reverse:
                        return reverse[as_int]
            except Exception:
                pass
            self.log.warning(
                f"unknown trigger {field_name} value from SDK: {raw_value!r}; returning raw value"
            )
            return raw_value

        return {
            "mode": _decode(mode, TRIGGERS["mode"], "mode"),
            "source": _decode(source, TRIGGERS["source"], "source"),
            "polarity": _decode(polarity, TRIGGERS["polarity"], "polarity"),
            "active": _decode(active, TRIGGERS["active"], "active"),
        }

    @trigger.setter
    def trigger(self, trigger: dict):

        mode = trigger['mode']
        source = trigger['source']
        polarity = trigger['polarity']
        active = trigger['active']

        valid_mode = list(TRIGGERS['mode'].keys())
        if mode not in valid_mode:
            raise ValueError("mode must be one of %r." % valid_mode)
        valid_source = list(TRIGGERS['source'].keys())
        if source not in valid_source:
            raise ValueError("source must be one of %r." % valid_source)
        valid_polarity = list(TRIGGERS['polarity'].keys())
        if polarity not in valid_polarity:
            raise ValueError("polarity must be one of %r." % valid_polarity)
        valid_active = list(TRIGGERS['active'].keys())
        if active not in valid_active:
            raise ValueError("active must be one of %r." % valid_active)

        # TODO figure out TRIGGERACTIVE bool
        self.dcam.prop_setvalue(PROPERTIES["trigger_mode"], TRIGGERS['mode'][mode])
        print("In dcam, current trigger mode...........", mode)
        self.dcam.prop_setvalue(PROPERTIES["trigger_source"], TRIGGERS['source'][source])
        self.dcam.prop_setvalue(PROPERTIES["trigger_polarity"], TRIGGERS['polarity'][polarity])
        self.dcam.prop_setvalue(PROPERTIES["trigger_active"], TRIGGERS['active'][active])

        self.log.info(f"trigger set to, mode: {mode}, source: {source}, polarity: {polarity}, active: {active}")
        # refresh parameter values
        self._update_parameters()

    @property
    def binning(self):
        binning = self.dcam.prop_getvalue(PROPERTIES["binning"])
        return binning

    @binning.setter
    def binning(self, binning):
        if binning not in BINNING and binning not in [1, 2, 4]:
            raise ValueError("binning must be one of %r." % BINNING)
        else:
            if isinstance(binning, str):
                self.dcam.prop_setvalue(PROPERTIES["binning"], BINNING[binning])
                self.log.info(f"binning set to: {BINNING[binning]}")
                # refresh parameter values
            elif isinstance(binning, int):
                self.dcam.prop_setvalue(PROPERTIES["binning"], binning)
                self.log.info(f"binning set to: {binning}")
            self._update_parameters()

    @property
    def sensor_width_px(self):
        return 2048

    @property
    def sensor_height_px(self):
        return 2048

    @property
    def signal_sensor_temperature_c(self):
        """get the sensor temperature in degrees C."""
        state = {}
        state['Sensor Temperature [C]'] = self.dcam.prop_getvalue(PROPERTIES["sensor_temperature"])
        return state

    @property
    def sensor_mode(self):
        sensor_mode = self.dcam.prop_getvalue(PROPERTIES['sensor_mode'])
        return next(key for key, value in SENSOR_MODES.items() if value == sensor_mode)

    @sensor_mode.setter
    def sensor_mode(self, sensor_mode: str):
        valid_mode = list(SENSOR_MODES.keys())
        if sensor_mode not in valid_mode:
            raise ValueError("sensor_mode must be one of %r." % valid_mode)
        else:
            self.dcam.prop_setvalue(PROPERTIES['sensor_mode'], SENSOR_MODES[sensor_mode])
        self.log.info(f"sensor mode set to: {sensor_mode}")
        # refresh parameter values
        self._update_parameters()

    @property
    def readout_direction(self):
        readout_direction = self.dcam.prop_getvalue(PROPERTIES['readout_direction'])
        return next(key for key, value in READOUT_DIRECTIONS.items() if value == readout_direction)

    @readout_direction.setter
    def readout_direction(self, readout_direction: str):
        valid_direction = list(READOUT_DIRECTIONS.keys())
        if readout_direction not in valid_direction:
            raise ValueError("readout_direction must be one of %r." % valid_direction)
        else:
            self.dcam.prop_setvalue(PROPERTIES['readout_direction'], READOUT_DIRECTIONS[readout_direction])
        self.log.info(f"readout direction set to: {readout_direction}")
        # refresh parameter values
        self._update_parameters()

    def prepare(self):
        # print("In dcam, start preparing camera...")
        # determine bits to bytes
        if self.pixel_type == 'mono8':
            bit_to_byte = 1
        else:
            bit_to_byte = 2
        self.defectcorrect()
        self.setSubArrayMode()
        self.readoutspeed()
        frame_size_mb = self.width_px*self.height_px/self.binning**2*bit_to_byte/1e6
        self.buffer_size_frames = round(BUFFER_SIZE_MB / frame_size_mb)
        # Reuse existing driver buffers when possible. Reallocate only if needed.
        needs_realloc = (
            (not self._buffers_allocated)
            or int(self.number_image_buffers) != int(self.buffer_size_frames)
        )
        if needs_realloc:
            if self._buffers_allocated:
                try:
                    self.dcam.buf_release()
                except Exception:
                    pass
            self.dcam.buf_alloc(self.buffer_size_frames)
            self.number_image_buffers = self.buffer_size_frames
            self._buffers_allocated = True
        # self.log.info(f"buffer set to: {self.buffer_size_frames} frames")

    def prepare_snapshot(self, buffer_frames=2):
        """
        Prepare the camera for a one-shot capture with a very small driver buffer.
        This avoids allocating the large streaming buffer budget for a single frame.
        """
        desired_buffers = max(1, int(buffer_frames))
        self.defectcorrect()
        self.setSubArrayMode()
        self.readoutspeed()
        needs_realloc = (
            (not self._buffers_allocated)
            or int(self.number_image_buffers) != desired_buffers
        )
        if needs_realloc:
            if self._buffers_allocated:
                try:
                    self.dcam.buf_release()
                except Exception:
                    pass
            self.dcam.buf_alloc(desired_buffers)
            self.number_image_buffers = desired_buffers
            self._buffers_allocated = True
        self.buffer_size_frames = desired_buffers

    def defectcorrect(self, defect = False):
        if defect:
            self.dcam.prop_setvalue(PROPERTIES["defectcorrect_mode"], SUBARRAY_OFF)
        else:
            self.dcam.prop_setvalue(PROPERTIES["defectcorrect_mode"], SUBARRAY_ON)

    def readoutspeed(self, mode = 0x7FFFFFFF):
        if mode == 1:
            self.dcam.prop_setvalue(PROPERTIES["readoutspeed"], 1)
        else:
            self.dcam.prop_setvalue(PROPERTIES["readoutspeed"], 0x7FFFFFFF)

    def start(self, frames = GENTL_INFINITE):
        # initialize variables for acquisition run
        self.clear_runtime_state()
        self.buffer_index = -1
        self.dcam.cap_start()
    
    def ready_signal(self):
        self.camera_ready_event.set()

    def setSubArrayMode(self):
        """
        This sets the sub-array mode as appropriate based on the current ROI.
        """
        roi_w = int(self.dcam.prop_getvalue(PROPERTIES["subarray_hsize"]))
        roi_h = int(self.dcam.prop_getvalue(PROPERTIES["subarray_vsize"]))
        if ((roi_w == self.sensor_width_px) and (roi_h == self.sensor_height_px)):
            self.dcam.prop_setvalue(PROPERTIES["subarray_mode"], SUBARRAY_OFF)
        else:
            self.dcam.prop_setvalue(PROPERTIES["subarray_mode"], SUBARRAY_ON)

    def abort(self):
        self.stop()

    def clear_runtime_state(self):
        self.dropped_frames = 0
        self.pre_frame_time = 0
        self.pre_frame_count_px = 0
        self.max_backlog = 0
        self._latest_frame = None
        self.buffer_index = 0
        self.last_frame_number = 0

    def stop_capture_only(self):
        try:
            self.dcam.cap_stop()
        except Exception:
            pass
        self.clear_runtime_state()

        # Keep legacy trigger reset behavior.
        # self.dcam.prop_setvalue(PROPERTIES["trigger_mode"], TRIGGERS['mode']['normal'])
        self.dcam.prop_setvalue(PROPERTIES["trigger_mode"], TRIGGERS['mode']['start'])

    def release_buffers(self):
        if self._buffers_allocated:
            try:
                self.dcam.buf_release()
            except Exception:
                pass
            self._buffers_allocated = False
            self.number_image_buffers = 0

    def stop(self):
        # Backward-compatible full stop: stop capture and release buffers.
        self.stop_capture_only()
        self.release_buffers()

        # self.dcam.prop_setvalue(PROPERTIES["trigger_mode"], TRIGGERS['mode']['start'])

    def close(self):
        if self.dcam.is_opened():
            self.stop_capture_only()
            self.release_buffers()
            if self.dcam is not None:
                self.dcam.dev_close()
            DcamapiSingleton.uninit()

    def reset(self):
        if self.dcam.is_opened():
            self._latest_frame = None
            self.last_frame_number = 0 
            self.max_backlog = 0
            self.buffer_index = 0
            self.dcam.dev_close()
            DcamapiSingleton.uninit()
            del self.dcam
            if DcamapiSingleton.init() is not False:
                self.dcam = Dcam(self.cam_num)
                self.dcam.dev_open()
    
    def getFrame(self):
        """
        Returns exactly one new frame from the camera buffer (as a NumPy array),
        or None if there are no more frames available (camera stopped).
        
        This will block until at least one new frame is ready if the camera
        is still running. 
        """
        # Grab the next unread index (or None if none is available).
        idx = self.nextFrameIndex()
        if idx is None:
            # No more frames or camera is done.
            return None

        # Retrieve the frame data from that buffer index.
        # t0 = time.perf_counter()
        frame_data = self.dcam.buf_getframedata(idx)  
        # t1 = time.perf_counter()
        
        self._latest_frame = frame_data
        # self.log.info("HCAM buf_getframedata() took: %.6f seconds", (t1 - t0))
        return frame_data, 1
    
    def getFrame_alloc(self):
        idx = self.nextFrameIndex()
        if idx is None:
            # No more frames or camera is done.
            return None
        

        paramlock = DCAMBUF_FRAME()
        
        paramlock.size = 0
        paramlock.iKind = 0
        paramlock.option = 0
        paramlock.iFrame = idx
        paramlock.buf = None
        paramlock.rowbytes = 0
        paramlock.type = 0
        paramlock.width = 0
        paramlock.height = 0
        paramlock.left = 0
        paramlock.top = 0
        paramlock.timestamp = DCAM_TIMESTAMP()
        paramlock.framestamp = 0
        paramlock.camerastamp = 0
        paramlock.size = ctypes.sizeof(paramlock)	

        # Lock the frame in the camera buffer & get address.
        self.checkStatus(self.dcam.dcambuf_lockframe(self.dcam.hdcam,
                                            ctypes.byref(paramlock)),
                            "dcambuf_lockframe")

        # Create storage for the frame & copy into this storage.
        hc_data = HCamData(self.dcam.prop_getvalue(4325952))
        hc_data.copyData(paramlock.buf)

        return hc_data, 1

    def nextFrameIndex(self):
        """
        Return the index (integer) of the *oldest unread* frame currently in the
        camera buffer. If no frames are available and the camera is still running,
        this will block until at least one frame is acquired. If the camera has
        stopped and no more frames are available, returns None.

        The idea:
        - Each call returns exactly *one* new frame index, in ascending order.
        - For example, if frames 0,1,2,3 have arrived, the first call returns 0,
            the next call returns 1, etc., until we've read them all.
        """
        # Check capture status.
        captureStatus = ctypes.c_int32(0)
        self.checkStatus(self.dcam.cap_status())

        # If camera is still acquiring, wait for at least one new frame.
        # This blocks until there's a frame (or the camera stops).
        if captureStatus.value == DCAMCAP_STATUS_BUSY:
            paramstart = DCAMWAIT_START(
                0, 
                0, 
                DCAMWAIT_CAPEVENT_FRAMEREADY | DCAMWAIT_CAPEVENT_STOPPED,
                100
            )
            paramstart.size = ctypes.sizeof(paramstart)
            self.checkStatus(
                self.dcam.dcamwait_start(
                    self.wait_handle, ctypes.byref(paramstart)
                ),
                "dcamwait_start"
            )

        # Check how many frames have been acquired so far.
        paramtransfer = self.dcam.cap_transferinfo()
        self.checkStatus(paramtransfer, "dcamcap_transferinfo")
        # cur_buffer_index = paramtransfer.nNewestFrameIndex
        cur_frame_number = paramtransfer.nFrameCount

        # How many *total* frames have arrived since last time?
        backlog = cur_frame_number - self.last_frame_number
        self.log.info('Size of backlog buffer: %s', backlog)
        # if backlog>2:
        #     print('Size of backlog buffer: %s', backlog)

        # Check for buffer overruns (we're acquiring more frames than we can store).
        if backlog > self.number_image_buffers:
            print(">> Warning! Hamamatsu camera frame buffer overrun detected!")
        if backlog > self.max_backlog:
            self.max_backlog = backlog

        # If there are new frames, read exactly ONE new index.
        if backlog > 0:
            # Move forward by ONE index from the "last read" buffer_index.
            next_index = (self.buffer_index + 1) % self.number_image_buffers

            # Update the trackers:
            self.buffer_index = next_index
            self.last_frame_number += 1

            # Return the single new index
            return next_index
        else:
            # No new frames; if the camera is stopped, we won't get more. Return None.
            return None

    def getFrames(self):
        """
        Gets all of the available frames.

        This will block waiting for new frames even if there new frames 
        available when it is called.

        FIXME: It does not always seem to block? The length of frames can
               be zero. Are frames getting dropped? Some sort of race condition?
        """
        frames = []
        time_v = []
        new_frames = self.newFrames()
        for n in new_frames:
            start = time.perf_counter()
            image = self.dcam.buf_getframedata(n) # this is the likely rate limiting step
            end = time.perf_counter()
            time_v.append(end-start)
            frames.append(image)
            if n == new_frames[-1]:
                self._latest_frame  = image
        self.log.info('HCAM buf_Get frames average: %0.6f', np.mean(time_v))
        return frames

    # def newFrames(self):
    #     """
    #     Return a list of the ids of all the new frames since the last check.
    #     Returns an empty list if the camera has already stopped and no frames
    #     are available.

    #     This will block waiting for at least one new frame.
    #     """
    #     # start = time.perf_counter()

    #     captureStatus = self.dcam.cap_status()

    #     # Wait for a new frame if the camera is acquiring.
    #     if captureStatus == DCAMCAP_STATUS_BUSY:
    #         ret = self.dcam.wait_capevent_frameready(3)
    #         while not ret:
    #             ret = self.dcam.wait_capevent_frameready(3)
    #     # end = time.perf_counter()
    #     # self.log.info('HCAM wait status busy: %0.6f', end-start)

    #     # Check how many new frames there are.
    #     # paramtransfer = DCAMCAP_TRANSFERINFO(
    #     #     0, DCAMCAP_TRANSFERKIND_FRAME, 0, 0)
    #     # paramtransfer.size = ctypes.sizeof(paramtransfer)
    #     # self.checkStatus(self.dcam.dcamcap_transferinfo(self.cam_num,
    #     #                                            ctypes.byref(paramtransfer)),
    #     #                  "dcamcap_transferinfo")
    #     # start = time.perf_counter()
    #     paramtransfer = self.dcam.cap_transferinfo()
    #     cur_buffer_index = paramtransfer.nNewestFrameIndex
    #     cur_frame_number = paramtransfer.nFrameCount
    #     # end = time.perf_counter()
    #     # self.log.info('HCAM cap tranfer info: %0.6f', end-start)

    #     # Check that we have not acquired more frames than we can store in our buffer.
    #     # Keep track of the maximum backlog.
    #     backlog = cur_frame_number - self.last_frame_number
    #     if (backlog > self.buffer_size_frames):
    #         print(">> Warning! hamamatsu camera frame buffer overrun detected!", backlog, self.buffer_size_frames)
    #     if (backlog > self.max_backlog):
    #         self.max_backlog = backlog
    #     self.last_frame_number = cur_frame_number

    #     # start = time.perf_counter()
    #     # Create a list of the new frames.
    #     new_frames = []
    #     if (cur_buffer_index < self.buffer_index):
    #         for i in range(self.buffer_index + 1, self.buffer_size_frames):
    #             new_frames.append(i)
    #         for i in range(cur_buffer_index + 1):
    #             new_frames.append(i)
    #     else:
    #         for i in range(self.buffer_index, cur_buffer_index):
    #             new_frames.append(i+1)
    #     self.buffer_index = cur_buffer_index
    #     if backlog>1:
    #         print('Backlog at camera', backlog)
    #     # end = time.perf_counter()
    #     # self.log.info('HCAM ceate list of new frames: %0.6f', end-start)

    #     return new_frames


    def newFrames(self):
        """
        Return a list of the ids of all the new frames since the last check.
        Returns an empty list if the camera has already stopped and no frames
        are available.
    
        This will block waiting for at least one new frame.
        """

        captureStatus = ctypes.c_int32(0)
        self.checkStatus(self.dcam.cap_status())

        # Wait for a new frame if the camera is acquiring.
        if captureStatus.value == DCAMCAP_STATUS_BUSY:
            paramstart = DCAMWAIT_START(
                    0, 
                    0, 
                    DCAMWAIT_CAPEVENT_FRAMEREADY | DCAMWAIT_CAPEVENT_STOPPED, 
                    100)
            paramstart.size = ctypes.sizeof(paramstart)
            self.checkStatus(self.dcam.dcamwait_start(self.wait_handle,
                                            ctypes.byref(paramstart)),
                             "dcamwait_start")

        # Check how many new frames there are.
        paramtransfer = self.dcam.cap_transferinfo()
        self.checkStatus(paramtransfer,
                         "dcamcap_transferinfo")
        cur_buffer_index = paramtransfer.nNewestFrameIndex
        cur_frame_number = paramtransfer.nFrameCount

        # Check that we have not acquired more frames than we can store in our buffer.
        # Keep track of the maximum backlog.
        backlog = cur_frame_number - self.last_frame_number
        self.log.info('Size of backlog buffer %0.6f', backlog)
        if (backlog > self.number_image_buffers):
            print(">> Warning! hamamatsu camera frame buffer overrun detected!")
        if (backlog > self.max_backlog):
            self.max_backlog = backlog
        self.last_frame_number = cur_frame_number


        # Create a list of the new frames.
        new_frames = []
        if (cur_buffer_index < self.buffer_index):
            for i in range(self.buffer_index + 1, self.number_image_buffers):
                new_frames.append(i)
            for i in range(cur_buffer_index + 1):
                new_frames.append(i)
        else:
            for i in range(self.buffer_index, cur_buffer_index):
                new_frames.append(i+1)
        self.buffer_index = cur_buffer_index

        # if self.debug:
        #     print(new_frames)

        return new_frames

    def checkStatus(self, fn_return, fn_name="unknown"):
        """
        Check return value of the dcam function call.
        Throw an error if not as expected?
        """
        # if (fn_return != DCAMERR_NOERROR) and (fn_return != DCAMERR_ERROR):
        #    raise DCAMException("dcam error: " + fn_name + " returned " + str(fn_return))
        if (fn_return == DCAMERR_ERROR):
            c_buf_len = 80
            c_buf = ctypes.create_string_buffer(c_buf_len)
            c_error = self.dcam.dcam_getlasterror(self.camera_handle,
                                             c_buf,
                                             ctypes.c_int32(c_buf_len))
            raise DCAMException(
                "dcam error " + str(fn_name) + " " + str(c_buf.value))
            # print "dcam error", fn_name, c_buf.value
        return fn_return

    def grab_frame(self):
        """Retrieve a frame as a 2D numpy array with shape (rows, cols)."""
        # Note: creating the buffer and then "pushing" it at the end has the
        #   effect of moving the internal camera frame buffer from the output
        #   pool back to the input pool, so it can be reused.
        timeout_ms = 1000
        if self.dcam.wait_capevent_frameready(timeout_ms) is not False:
            image = self.dcam.buf_getlastframedata()
            self._latest_frame  = image
            return image

    def capture_snapshot_frame(self, timeout_ms=10000):
        """
        Capture and return a single frame using DCAM snapshot mode.
        """
        timeout_ms = max(1, int(timeout_ms))
        self.clear_runtime_state()
        self.buffer_index = -1
        if self.dcam.cap_snapshot() is False:
            raise RuntimeError("Hamamatsu DCAM cap_snapshot() failed.")
        if self.dcam.wait_capevent_frameready(timeout_ms) is False:
            try:
                self.stop_capture_only()
            except Exception:
                pass
            raise TimeoutError(f"Hamamatsu DCAM snapshot timed out after {timeout_ms} ms.")
        image = self.dcam.buf_getlastframedata()
        self._latest_frame = image
        try:
            self.stop_capture_only()
        except Exception:
            pass
        return image

    @property
    def latest_frame(self):
        return self._latest_frame

    def signal_acquisition_state(self):
        """return a dict with the state of the acquisition buffers"""
        cap_info = DCAMCAP_TRANSFERINFO()
        # __hdcam inside class Dcam referenced as _Dcam__hdcam
        dcamcap_transferinfo(self.dcam._Dcam__hdcam, byref(cap_info))
        self.post_frame_time = time.time()
        frame_index = cap_info.nFrameCount
        out_buffer_size = frame_index - self.pre_frame_count_px
        in_buffer_size = self.buffer_size_frames - out_buffer_size
        if out_buffer_size > self.buffer_size_frames:
            new_dropped_frames = out_buffer_size - self.buffer_size_frames
            self.dropped_frames += new_dropped_frames
        time_diff = (self.post_frame_time - self.pre_frame_time)
        if time_diff > 0:
            frame_rate = out_buffer_size / time_diff
        else:
            frame_rate = 1/(self.exposure_time_ms/1000)
        # determine bits to bytes
        if self.pixel_type == 'mono8':
            bit_to_byte = 1
        else:
            bit_to_byte = 2
        data_rate = frame_rate*self.width_px*self.height_px/self.binning**2*bit_to_byte/1e6
        state = {}
        state['Frame Index'] = frame_index
        state['Input Buffer Size'] = in_buffer_size
        state['Output Buffer Size'] = out_buffer_size
        # number of underrun, i.e. dropped frames
        state['Dropped Frames'] = self.dropped_frames
        state['Data Rate [MB/s]'] = data_rate
        state['Frame Rate [fps]'] = frame_rate
        self.log.info(f"id: {self.id}, "
                      f"frame: {state['Frame Index']}, "
                      f"input: {state['Input Buffer Size']}, "
                      f"output: {state['Output Buffer Size']}, "
                      f"dropped: {state['Dropped Frames']}, "
                      f"data rate: {state['Data Rate [MB/s]']:.2f} [MB/s], "
                      f"frame rate: {state['Frame Rate [fps]']:.2f} [fps].")
        self.pre_frame_time = self.post_frame_time
        self.pre_frame_count_px = cap_info.nFrameCount

        return state

    def log_metadata(self):
        # log dcam camera settings
        self.log.info('dcam camera parameters')
        idprop = self.dcam.prop_getnextid(0)
        while idprop is not False:
            propname = self.dcam.prop_getname(idprop)
            propvalue = self.dcam.prop_getvalue(idprop)
            self.log.info(f'{propname}, {propvalue}')
            idprop = self.dcam.prop_getnextid(idprop)

    def print_existing_options(self):
        uppercase_dicts = {}
        for name, value in globals().items():
            if name.isupper() and isinstance(value, dict):
                uppercase_dicts[name] = value
                # print(name, value)
        return uppercase_dicts

    def _update_parameters(self):
        # grab parameter values
        self._get_min_max_step_values()
        # check binning options
        self._query_binning()
        # check pixel type options
        self._query_pixel_types()
        # check trigger mode options
        self._query_trigger_modes()
        # check trigger source options
        self._query_trigger_sources()
        # check trigger polarity options
        self._query_trigger_polarities()
        # check trigger active options
        self._query_trigger_active()
        # check sensor mode options
        self._query_sensor_modes()
        # check readout direction options
        self._query_readout_directions()

    def _get_min_max_step_values(self):
        # gather min max values
        # convert from s to ms
        self.min_exposure_time_ms = type(self).exposure_time_ms.minimum = self.dcam.prop_getattr(PROPERTIES["exposure_time"]).valuemin*1e3
        self.max_exposure_time_ms = type(self).exposure_time_ms.maximum = self.dcam.prop_getattr(PROPERTIES["exposure_time"]).valuemax*1e3
        # convert from s to us
        self.min_line_interval_us = type(self).line_interval_us.minimum = self.dcam.prop_getattr(PROPERTIES["line_interval"]).valuemin*1e6
        self.max_line_interval_us = type(self).line_interval_us.minimum =self.dcam.prop_getattr(PROPERTIES["line_interval"]).valuemax*1e6
        self.min_width_px = type(self).width_px.minimum = self.dcam.prop_getattr(PROPERTIES["image_width"]).valuemin
        self.max_width_px = type(self).width_px.maximum = self.dcam.prop_getattr(PROPERTIES["image_width"]).valuemax
        self.min_height_px = type(self).height_px.minimum = self.dcam.prop_getattr(PROPERTIES["image_height"]).valuemin
        self.max_height_px = type(self).height_px.maximum = self.dcam.prop_getattr(PROPERTIES["image_height"]).valuemax
        self.min_offset_x_px = self.dcam.prop_getattr(PROPERTIES["subarray_hpos"]).valuemin
        self.max_offset_x_px = self.dcam.prop_getattr(PROPERTIES["subarray_hpos"]).valuemax
        self.min_offset_y_px = self.dcam.prop_getattr(PROPERTIES["subarray_vpos"]).valuemin
        self.max_offset_y_px = self.dcam.prop_getattr(PROPERTIES["subarray_vpos"]).valuemax
        # convert from s to us
        self.step_exposure_time_ms = type(self).exposure_time_ms.step = self.dcam.prop_getattr(PROPERTIES["exposure_time"]).valuestep*1e3
        self.step_line_interval_us = type(self).line_interval_us.step = self.dcam.prop_getattr(PROPERTIES["line_interval"]).valuestep*1e6
        self.step_width_px = type(self).width_px.step = self.dcam.prop_getattr(PROPERTIES["image_width"]).valuestep
        self.step_height_px = type(self).height_px.step = self.dcam.prop_getattr(PROPERTIES["image_height"]).valuestep
        self.step_offset_x_px = self.dcam.prop_getattr(PROPERTIES["subarray_hpos"]).valuestep
        self.step_offset_y_px = self.dcam.prop_getattr(PROPERTIES["subarray_vpos"]).valuestep

        self.log.debug(f"min exposure time is: {self.min_exposure_time_ms} ms")
        self.log.debug(f"max exposure time is: {self.max_exposure_time_ms} ms")
        self.log.debug(f"min line interval is: {self.min_line_interval_us} us")
        self.log.debug(f"max line interval is: {self.max_line_interval_us} us")
        self.log.debug(f"min width is: {self.min_width_px} px")
        self.log.debug(f"max width is: {self.max_width_px} px")
        self.log.debug(f"min height is: {self.min_height_px} px")
        self.log.debug(f"max height is: {self.max_height_px} px")
        self.log.debug(f"min offset x is: {self.min_offset_x_px} px")
        self.log.debug(f"max offset x is: {self.max_offset_x_px} px")
        self.log.debug(f"min offset y is: {self.min_offset_y_px} px")
        self.log.debug(f"max offset y is: {self.max_offset_y_px} px")
        self.log.debug(f"step exposure time is: {self.step_exposure_time_ms} ms")
        self.log.debug(f"step line interval is: {self.step_line_interval_us} us")
        self.log.debug(f"step width is: {self.step_width_px} px")
        self.log.debug(f"step height is: {self.step_height_px} px")
        self.log.debug(f"step offset x is: {self.step_offset_x_px} px")
        self.log.debug(f"step offset y is: {self.step_offset_y_px} px")

    def _query_trigger_modes(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_mode']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_mode']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['trigger_mode'], prop_value)
           if reply != False:
               TRIGGERS['mode'][reply.lower()] = prop_value

    def _query_trigger_sources(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_source']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_source']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['trigger_source'], prop_value)
           if reply != False:
               TRIGGERS['source'][reply.lower()] = prop_value

    def _query_trigger_polarities(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_polarity']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_polarity']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['trigger_polarity'], prop_value)
           if reply != False:
               TRIGGERS['polarity'][reply.lower()] = prop_value
    
    def _query_trigger_active(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_active']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['trigger_active']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['trigger_active'], prop_value)
           if reply != False:
               TRIGGERS['active'][reply.lower()] = prop_value

    def _query_sensor_modes(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['sensor_mode']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['sensor_mode']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['sensor_mode'], prop_value)
           if reply != False:
               SENSOR_MODES[reply.lower()] = prop_value

    def _query_readout_directions(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['readout_direction']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['readout_direction']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['readout_direction'], prop_value)
           if reply != False:
               READOUT_DIRECTIONS[reply.lower()] = prop_value

    def _query_binning(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['binning']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['binning']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['binning'], prop_value)
           if reply != False:
               BINNING[reply.lower()] = prop_value

    def _query_pixel_types(self):
        min_prop_value = int(self.dcam.prop_getattr(PROPERTIES['pixel_type']).valuemin)
        max_prop_value = int(self.dcam.prop_getattr(PROPERTIES['pixel_type']).valuemax)
        for prop_value in range(min_prop_value, max_prop_value+1):
           reply = self.dcam.prop_getvaluetext(PROPERTIES['pixel_type'], prop_value)
           if reply != False:
               PIXEL_TYPES[reply.lower()] = prop_value


class HCamData(object):
    """
    Hamamatsu camera data object.

    Initially I tried to use create_string_buffer() to allocate storage for the 
    data from the camera but this turned out to be too slow. The software
    kept falling behind the camera and create_string_buffer() seemed to be the
    bottleneck.

    Using numpy makes a lot more sense anyways..
    """
    def __init__(self, size = None, **kwds):
        """
        Create a data object of the appropriate size.
        """
        super().__init__(**kwds)
        size = int(size)
        self.np_array = np.ascontiguousarray(np.empty(int(size/2), dtype=np.uint16))
        self.size = size

    def __getitem__(self, slice):
        return self.np_array[slice]

    def copyData(self, address):
        """
        Uses the C memmove function to copy data from an address in memory
        into memory allocated for the numpy array of this object.
        """
        ctypes.memmove(self.np_array.ctypes.data, address, self.size)

    def getData(self):
        return self.np_array

    def getDataPtr(self):
        return self.np_array.ctypes.data
