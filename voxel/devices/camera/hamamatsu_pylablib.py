import logging
import time
import numpy as np
import os
import sys
# Get the current script directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define the paths to Voxel and View
voxel_path = os.path.join(current_dir, '../voxel')
view_path = os.path.join(current_dir, '../View')

# Add these paths to sys.path if they are not already present
if voxel_path not in sys.path:
    sys.path.append(r"C:\Users\ARPA\Desktop\ControlCodes\UHR-OTLS-control-Dec2024\voxel")
    print(f"Added {voxel_path} to sys.path")

if view_path not in sys.path:
    sys.path.append(view_path)
    print(f"Added {view_path} to sys.path")
import logging
import numpy as np

from pylablib.devices.DCAM import (
    DCAMCamera,
    DCAMError,
    DCAMTimeoutError,
    get_cameras_number
)
from voxel.devices.camera.base import BaseCamera
from voxel.descriptors.deliminated_property import DeliminatedProperty

BUFFER_SIZE_MB = 2000
##################################################################
# 1) Helper function to open the correct DCAMCamera by serial
##################################################################
def open_camera_by_serial(desired_serial):
    """
    Search all connected DCAM cameras by index (0..N-1),
    open each, check if its reported serial number matches `desired_serial`.
    Return the opened DCAMCamera if found; raise ValueError if not found.
    """
    n_cameras = get_cameras_number()
    logging.info(f"Number of connected DCAM cameras: {n_cameras}")
    for idx in range(n_cameras):
        try:
            cam = DCAMCamera(idx=idx)
            info = cam.get_device_info()
            # info.serial_number might look like "S/N 306727" or just "306727"
            sn_str = info.serial_number.replace("S/N", "").strip()
            logging.info(f"Opened camera idx={idx}, model={info.model}, serial={sn_str}")
            # print(desired_serial, type(desired_serial), sn_str, type(sn_str), sn_str == desired_serial, len(sn_str), len(desired_serial))
            sn_str = sn_str.replace(': ', '')
            if sn_str == desired_serial:
                print('found match')
                logging.info("Found matching camera serial=%s", desired_serial)
                return cam
            else:
                cam.close()
        except DCAMError as e:
            logging.warning(f"Failed to open camera idx={idx}: {e}")

    raise ValueError(f"No DCAM camera found matching serial={desired_serial}")


##################################################################
# 2) Our "Camera" class which wraps the DCAMCamera
##################################################################
class Camera(BaseCamera):
    """
    Rewritten Hamamatsu camera class using pylablib's DCAMCamera behind the scenes.
    """

    def __init__(self, id: str):
        """
        :param id: The desired camera serial number (e.g. 306727).
        """
        super().__init__()
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.id = str(id)  # store as string

        self.log.info("Initializing Hamamatsu camera via pylablib DCAM")
        self._cam = open_camera_by_serial(self.id)  # store the DCAMCamera
        self._latest_frame = None
        # Track parameters for ring buffer usage
        self._buffer_size_frames = 0
        self.dropped_frames = 0
        self.pre_frame_count_px = 0
        self.pre_frame_time = 0

        # Attempt to query the camera’s default ROI/binning properties:
        # We can store them in some local variables if needed
        self._update_parameters()

    ##################################################################
    # 2A) PROPERTIES
    ##################################################################

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def exposure_time_ms(self):
        """
        Get/Set the camera exposure time in ms.
        DCAMCamera uses seconds internally, so we convert.
        """
        exp_s = self._cam.get_exposure()
        return exp_s * 1000.0

    @exposure_time_ms.setter
    def exposure_time_ms(self, val_ms):
        self._cam.set_exposure(val_ms / 1000.0)
        self.log.info(f"Exposure time set to: {val_ms} ms")
        self._update_parameters()

    @property
    def pixel_type(self):
        """
        Return a string like "mono16" or "unknown" if the camera has that enumerated property.
        The DCAM property name is "PIXEL TYPE" or similar.
        """
        # We get the numeric value from DCAM, try to map it to the textual label
        values = {1: 'mono8', 16:'mono16', 12:'mono12'}
        try:
            attr = self._cam.get_attribute("BIT PER CHANNEL", error_on_missing=False)
            if attr is None:
                return "unknown"
            val = attr.get_value()
            # Attempt to get text label for that numeric val
            # If the label is "MONO16", we return "mono16".
            # text_label = attr.ilabels.get(val, None)
            text_label = values[val]
            if text_label:
                return text_label.lower()
            return f"unknown({val})"
        except DCAMError:
            return "unknown"

    @pixel_type.setter
    def pixel_type(self, val_str: str):
        """
        e.g. "mono16", "mono8".
        We'll look up the DCAM numeric code and set that property.
        """
        # Get the attribute object for "PIXEL TYPE"
        attr = self._cam.get_attribute("BIT PER CHANNEL", error_on_missing=False)
        if attr is None:
            self.log.warning("Camera does not support 'PIXEL TYPE'. Cannot set pixel_type.")
            return

        # Convert something like "mono16" to uppercase "MONO16"
        # Then check if that is in the attribute's labels dict
        print('VAL STRING', val_str)
        values = {'mono8': 8, 'mono16': 16, 'mono12': 12}
        bpp = values[val_str]
        # uppercase = val_str.upper()
        # if uppercase not in attr.labels:
        #     self.log.warning(f"pixel_type '{val_str}' not recognized among {list(attr.labels.keys())}")
        #     return

        # numeric_code = attr.labels[uppercase]  # e.g. 11 for MONO16
        # print('Numeric_code ', numeric_code)
        attr.set_value(bpp)
        print(f"pixel type set to: {val_str} => code {bpp}")
        self.log.info(f"pixel type set to: {val_str} => code {bpp}")
        self._update_parameters()

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def width_px(self):
        """
        Return the current SUBARRAY HSIZE from DCAM.
        """
        hstart, hend, _, _, _, _ = self._cam.get_roi()
        return hend - hstart

    @width_px.setter
    def width_px(self, value):
        # We'll get the existing ROI, then modify just the width
        (hstart, hend, vstart, vend, hbin, _) = self._cam.get_roi()
        # keep the same hstart, just set hend = hstart+value
        new_hend = hstart + value
        # pass it back to set_roi
        self._cam.set_roi(hstart, new_hend, vstart, vend, hbin=hbin, vbin=hbin)
        self.log.info(f"Set width_px => {value}")
        self._update_parameters()

    @property
    def width_offset_px(self):
        """
        Return SUBARRAY HPOS
        """
        (hstart, hend, _, _, _, _) = self._cam.get_roi()
        return hstart

    @width_offset_px.setter
    def width_offset_px(self, val):
        (old_hstart, old_hend, vstart, vend, hbin, _) = self._cam.get_roi()
        width = old_hend - old_hstart
        new_hstart = val
        new_hend   = new_hstart + width
        self._cam.set_roi(new_hstart, new_hend, vstart, vend, hbin, hbin)
        self.log.info(f"Set width_offset_px => {val}")
        self._update_parameters()

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    def height_px(self):
        (hstart, hend, vstart, vend, hbin, vbin) = self._cam.get_roi()
        return vend - vstart

    @height_px.setter
    def height_px(self, value):
        (hstart, hend, vstart, vend, hbin, _) = self._cam.get_roi()
        new_vend = vstart + value
        self._cam.set_roi(hstart, hend, vstart, new_vend, hbin, hbin)
        self.log.info(f"Set height_px => {value}")
        self._update_parameters()

    @property
    def height_offset_px(self):
        (hstart, hend, vstart, vend, hbin, vbin) = self._cam.get_roi()
        return vstart

    @height_offset_px.setter
    def height_offset_px(self, val):
        (hstart, hend, old_vstart, old_vend, hbin, vbin) = self._cam.get_roi()
        height = old_vend - old_vstart
        new_vstart = val
        new_vend   = new_vstart + height
        self._cam.set_roi(hstart, hend, new_vstart, new_vend, hbin, hbin)
        self.log.info(f"Set height_offset_px => {val}")
        self._update_parameters()

    @property
    def binning(self):
        """
        Return the current binning factor (assumes hbin=vbin).
        """
        (_, _, _, _, hbin, _) = self._cam.get_roi()
        return hbin

    @binning.setter
    def binning(self, val_str_or_int):
        """
        For example: "1x1" or "2x2" => integer 1 or 2. 
        """
        if isinstance(val_str_or_int, str):
            # parse "2x2" => 2
            val = int(val_str_or_int.split("x")[0])
        else:
            val = val_str_or_int

        # get current ROI
        (hstart, hend, vstart, vend, old_hbin, old_vbin) = self._cam.get_roi()
        self._cam.set_roi(hstart, hend, vstart, vend, hbin=val, vbin=val)
        self.log.info(f"Set binning => {val_str_or_int}")
        self._update_parameters()

    @property
    def trigger(self):
        """
        Return a dict with 'mode', 'source', 'polarity', 'active'.
        DCAMCamera lumps some of these into set_trigger_mode("int","ext","software").
        For 'polarity' and 'active', we read attribute values directly.
        """
        out = {}
        # DCAMCamera's get_trigger_mode() => "int", "ext", "software", or "master_pulse"
        out["source"] = self._cam.get_trigger_mode()  # e.g. "ext"
        # Polarity (TRIGGER POLARITY)
        try:
            pol_attr = self._cam.get_attribute("TRIGGER POLARITY", error_on_missing=False)
            if pol_attr:
                val = pol_attr.get_value(enum_as_str=True)
                out["polarity"] = str(val).lower()
            else:
                out["polarity"] = "unsupported"
        except DCAMError:
            out["polarity"] = "error"
        # Active (TRIGGER ACTIVE)
        try:
            act_attr = self._cam.get_attribute("TRIGGER ACTIVE", error_on_missing=False)
            if act_attr:
                val2 = act_attr.get_value(enum_as_str=True)
                out["active"] = str(val2).lower()
            else:
                out["active"] = "unsupported"
        except DCAMError:
            out["active"] = "error"
        # "mode" is a bit ambiguous in pylablib. 
        # Some cameras have "TRIGGER MODE" with enumerations like NORMAL, PIV, START, etc.
        # We can attempt to read it if present:
        try:
            mode_attr = self._cam.get_attribute("TRIGGER MODE", error_on_missing=False)
            if mode_attr:
                val3 = mode_attr.get_value(enum_as_str=True)
                out["mode"] = str(val3).lower()
            else:
                out["mode"] = "unsupported"
        except DCAMError:
            out["mode"] = "error"

        return out

    @trigger.setter
    def trigger(self, trig_dict):
        """
        Example usage:
          trig_dict = {
            "mode": "start", 
            "source": "external",
            "polarity": "positive", 
            "active": "syncreadout"
          }
        We map "source" => set_trigger_mode("ext" or "int" or "software"),
        "polarity" => set_attribute_value("TRIGGER POLARITY", 1 or 2),
        etc.
        """
        # source => "external" => "ext" in DCAMCamera
        src = trig_dict.get("source", "internal")
        if src.lower() == "external":
            self._cam.set_trigger_mode("ext")
        elif src.lower() == "internal":
            self._cam.set_trigger_mode("int")
        elif src.lower() == "software":
            self._cam.set_trigger_mode("software")
        else:
            self.log.warning(f"Unknown trigger source '{src}', ignoring.")

        # polarity => "positive" => numeric 2, "negative" => 1
        pol = trig_dict.get("polarity", None)
        if pol:
            pol_attr = self._cam.get_attribute("TRIGGER POLARITY", error_on_missing=False)
            if pol_attr:
                # check pol_attr.labels => could be {"POSITIVE": 2, "NEGATIVE": 1}
                upper_pol = pol.upper()
                if upper_pol in pol_attr.labels:
                    pol_val = pol_attr.labels[upper_pol]
                    pol_attr.set_value(pol_val)
                else:
                    self.log.warning(f"Requested polarity '{pol}' not recognized among {pol_attr.labels}")
        # active => "syncreadout" => maybe numeric code "SYNCREADOUT": 3 or 4
        act = trig_dict.get("active", None)
        if act:
            act_attr = self._cam.get_attribute("TRIGGER ACTIVE", error_on_missing=False)
            if act_attr:
                up_act = act.upper()
                if up_act in act_attr.labels:
                    act_val = act_attr.labels[up_act]
                    act_attr.set_value(act_val)
                else:
                    self.log.warning(f"Requested active '{act}' not recognized among {act_attr.labels}")
        # mode => "start" => might be a DCAM property "TRIGGER MODE" with enumerations:
        md = trig_dict.get("mode", None)
        if md:
            mode_attr = self._cam.get_attribute("TRIGGER MODE", error_on_missing=False)
            if mode_attr:
                up_md = md.upper()
                if up_md in mode_attr.labels:
                    md_val = mode_attr.labels[up_md]
                    mode_attr.set_value(md_val)
                else:
                    self.log.warning(f"Requested TRIGGER MODE '{md}' not recognized among {mode_attr.labels}")
        self.log.info(f"Trigger set to: {trig_dict}")

    ##################################################################
    # 2B) ACQUISITION METHODS
    ##################################################################

    def prepare(self):
        """
        Equivalent to allocating a ring buffer. 
        We'll guess how many frames we want in the ring buffer. 
        """
        # Decide a buffer size. Or you can pass it in from user config.
        # For example, 200 frames:
        frame_size_mb = self.width_px*self.height_px/self.binning**2*2/1e6
        self._buffer_size_frames = round(BUFFER_SIZE_MB / frame_size_mb)
        print('Camera prepare', 'number of frames', self._buffer_size_frames)
        self.log.info(f"Preparing acquisition: ring buffer of {self._buffer_size_frames} frames")
        # Nothing else is strictly needed here. We'll do it in start() or setup_acquisition().

    def start(self, frames=None):
        """
        Start acquisition. If frames is None => indefinite. We'll pick 'sequence' mode with buffer of self._buffer_size_frames.
        """
        # “sequence” = continuous ring buffer. “snap” = single or fixed n
        # Let’s do a typical sequence:
        if frames is None:
            frames = self._buffer_size_frames
        self._cam.setup_acquisition(mode="sequence", nframes=frames)
        self._cam.start_acquisition()
        self.dropped_frames = 0
        self.pre_frame_time = 0
        self.pre_frame_count_px = 0
        self.log.info("Acquisition started.")

    def getFrame(self):
        """
        Return exactly *one* new frame if available, otherwise None.
        In pylablib: read_multiple_images() returns a list of new frames.
        """
        # frames = self._cam.read_multiple_images()  # all new frames in buffer
        # if len(frames) == 0:
        #     return None
        # # We'll just return the oldest. 
        # self.log.info('Number of frames retrieved {%0.8f}', len(frames))
        # f = frames[0]
        # self._latest_frame = f
        frame = self._cam.read_oldest_image(peek=False, return_info=False)
        self._latest_frame = frame
        return frame

    def stop(self):
        """
        Stop the acquisition.
        """
        self._cam.stop_acquisition()
        self.log.info("Acquisition stopped.")

    def abort(self):
        """
        Same as stop for your original code.
        """
        self.stop()

    def close(self):
        """
        Close the camera to free resources.
        """
        if self._cam.is_opened():
            self._cam.stop_acquisition()
            self._cam.close()
            self.log.info("Camera closed.")

    @property
    def latest_frame(self):
        """
        Return the last retrieved frame (cached).
        """
        return self._latest_frame

    ##################################################################
    # 2C) UTILITY & STATE
    ##################################################################

    def signal_acquisition_state(self):
        """
        Return some info about frame count, buffer usage, data rate, etc.
        (similar to the original code).
        """
        # transfer_info => (last_buff_index, total_frame_count)
        (last_idx, frame_count) = self._cam.get_transfer_info()
        post_time = self._now()
        out_buffer_size = frame_count - self.pre_frame_count_px
        in_buffer_size = self._buffer_size_frames - out_buffer_size

        # If out_buffer_size > self._buffer_size_frames => overrun => dropped frames
        if out_buffer_size > self._buffer_size_frames:
            new_dropped = out_buffer_size - self._buffer_size_frames
            self.dropped_frames += new_dropped

        time_diff = post_time - self.pre_frame_time if self.pre_frame_time != 0 else 0
        if time_diff > 0:
            frame_rate = out_buffer_size / time_diff
        else:
            # fallback: 1 / exposure
            frame_rate = 1.0 / (self.exposure_time_ms / 1000.0)

        # estimate data rate in MB/s
        # pixel_type => "mono8" => 1 byte/pixel, else 2 bytes/pixel
        bit_to_byte = 1 if self.pixel_type == "mono8" else 2
        data_rate = (frame_rate *
                     self.width_px *
                     self.height_px /
                     (self.binning ** 2) *
                     bit_to_byte / 1e6
                    )

        state = {
            'Frame Index': frame_count,
            'Input Buffer Size': in_buffer_size,
            'Output Buffer Size': out_buffer_size,
            'Dropped Frames': self.dropped_frames,
            'Data Rate [MB/s]': data_rate,
            'Frame Rate [fps]': frame_rate,
        }
        self.log.info(
            f"id={self.id}, frame={frame_count}, input={in_buffer_size}, "
            f"output={out_buffer_size}, dropped={self.dropped_frames}, "
            f"data={data_rate:.2f} MB/s, fps={frame_rate:.2f}"
        )

        self.pre_frame_time = post_time
        self.pre_frame_count_px = frame_count
        return state

    def log_metadata(self):
        """
        Log all DCAM camera attributes: name => current value
        """
        all_attrs = self._cam._list_attributes()
        self.log.info("DCAM camera attributes:")
        for attr in all_attrs:
            try:
                val = attr.get_value(enum_as_str=True)
                self.log.info(f"{attr.name}: {val}")
            except DCAMError:
                pass

    def _update_parameters(self):
        """
        Refresh min/max/step for ROI properties, line interval, enumerations, etc.
        We intentionally skip min/max for exposure since your camera’s exposure is truly a float.
        """
        self.log.debug("[_update_parameters] Updating camera parameter metadata...")

        # 1) SUBARRAY HPOS => width_offset range
        try:
            attr_hpos = self._cam.get_attribute("SUBARRAY HPOS", error_on_missing=False)
            if attr_hpos:
                self.min_offset_x_px = int(attr_hpos.min)
                self.max_offset_x_px = int(attr_hpos.max)
                self.step_offset_x_px = int(attr_hpos.step)
                self.log.debug(
                    f"SUBARRAY HPOS => range=[{self.min_offset_x_px},{self.max_offset_x_px}], "
                    f"step={self.step_offset_x_px}"
                )
        except DCAMError:
            pass

        # 2) SUBARRAY HSIZE => width_px range
        try:
            attr_hsize = self._cam.get_attribute("SUBARRAY HSIZE", error_on_missing=False)
            if attr_hsize:
                self.min_width_px = int(attr_hsize.min)
                self.max_width_px = int(attr_hsize.max)
                self.step_width_px = int(attr_hsize.step)
                # Optionally, update the DeliminatedProperty bounds:
                type(self).width_px.minimum = self.min_width_px
                type(self).width_px.maximum = self.max_width_px

                self.log.debug(
                    f"SUBARRAY HSIZE => range=[{self.min_width_px},{self.max_width_px}], "
                    f"step={self.step_width_px}"
                )
        except DCAMError:
            pass

        # 3) SUBARRAY VPOS => height_offset range
        try:
            attr_vpos = self._cam.get_attribute("SUBARRAY VPOS", error_on_missing=False)
            if attr_vpos:
                self.min_offset_y_px = int(attr_vpos.min)
                self.max_offset_y_px = int(attr_vpos.max)
                self.step_offset_y_px = int(attr_vpos.step)
                self.log.debug(
                    f"SUBARRAY VPOS => range=[{self.min_offset_y_px},{self.max_offset_y_px}], "
                    f"step={self.step_offset_y_px}"
                )
        except DCAMError:
            pass

        # 4) SUBARRAY VSIZE => height_px range
        try:
            attr_vsize = self._cam.get_attribute("SUBARRAY VSIZE", error_on_missing=False)
            if attr_vsize:
                self.min_height_px = int(attr_vsize.min)
                self.max_height_px = int(attr_vsize.max)
                self.step_height_px = int(attr_vsize.step)
                # Optionally, update the DeliminatedProperty bounds:
                type(self).height_px.minimum = self.min_height_px
                type(self).height_px.maximum = self.max_height_px

                self.log.debug(
                    f"SUBARRAY VSIZE => range=[{self.min_height_px},{self.max_height_px}], "
                    f"step={self.step_height_px}"
                )
        except DCAMError:
            pass

        # 5) INTERNAL LINE INTERVAL => line_interval_us
        #    Some cameras might not support this property
        try:
            attr_lineint = self._cam.get_attribute("INTERNAL LINE INTERVAL", error_on_missing=False)
            if attr_lineint:
                self.min_line_interval_us = attr_lineint.min * 1e6
                self.max_line_interval_us = attr_lineint.max * 1e6
                self.step_line_interval_us = attr_lineint.step * 1e6
                self.log.debug(
                    f"INTERNAL LINE INTERVAL => range=[{self.min_line_interval_us},{self.max_line_interval_us}] us, "
                    f"step={self.step_line_interval_us} us"
                )
        except DCAMError:
            pass

        # 6) If you want to re-query enumerations for binning, pixel type, triggers, etc.
        #    For example, see what binning steps are valid:
        try:
            valid_bins = self._cam._get_valid_binnings()
            self.log.debug(f"Valid binning factors => {valid_bins}")
        except Exception:
            pass

        # ... similarly for pixel type or triggers if needed

        self.log.debug("[_update_parameters] Done updating.")
        # Similarly, you could read subarray attributes, binning, etc.

    def _now(self):
        """
        Return current time in seconds; used for data rate calculation. 
        You can just do time.time() if you prefer.
        """
        import time
        return time.time()

def main():
    # Set up logging (optional)
    logging.basicConfig(level=logging.INFO)

    # ----------------------------------------------------------------------------
    # Parse or use static camera config:
    camera_config = {
        "id": 306727,  # Hamamatsu camera serial number
        "exposure_time_ms": 1.0,
        "pixel_type": "mono16",
        "height_offset_px": 960,
        "height_px": 128,
        "width_offset_px": 0,
        "width_px": 2048,
        "trigger": {
            "mode": "start",
            "source": "internal",
            "polarity": "positive",
            "active": "syncreadout"
        },
        "binning": "1x1"
    }

    # try:
    # ----------------------------------------------------------------------------
    # 1) Initialize the Camera
    # ----------------------------------------------------------------------------
    cam = Camera(id=camera_config["id"])
    
    # ----------------------------------------------------------------------------
    # 2) Configure the Camera using the provided settings
    # ----------------------------------------------------------------------------
    cam.exposure_time_ms = camera_config["exposure_time_ms"]
    cam.pixel_type = camera_config["pixel_type"]
    cam.height_offset_px = camera_config["height_offset_px"]
    cam.height_px = camera_config["height_px"]
    cam.width_offset_px = camera_config["width_offset_px"]
    cam.width_px = camera_config["width_px"]
    cam.trigger = camera_config["trigger"]
    cam.binning = camera_config["binning"]

    # ----------------------------------------------------------------------------
    # 3) Prepare Acquisition
    # ----------------------------------------------------------------------------
    cam.prepare()

    # ----------------------------------------------------------------------------
    # 4) Start Acquisition
    # ----------------------------------------------------------------------------
    cam.start()  # indefinite run

    # ----------------------------------------------------------------------------
    # 5) Grab a few frames (as a quick demo)
    # ----------------------------------------------------------------------------
    for i in range(5):
        frame = cam.getFrame()  # blocks until one frame arrives or timeout
        print(frame)
        if frame is None:
            print(f"No frame received on iteration {i}.")
            break
        else:
            print(f"Got frame {i}: shape={frame.shape}, dtype={frame.dtype}")
        time.sleep(0.1)

    # ----------------------------------------------------------------------------
    # 6) Stop and Close
    # ----------------------------------------------------------------------------
    cam.stop()
    cam.close()

    # except Exception as exc:
    #     logging.error(f"Error during camera operation: {exc}")
    #     # Attempt to stop/close camera if open:
    #     try:
    #         cam.stop()
    #         cam.close()
    #     except:
    #         pass

if __name__ == "__main__":
    main()
