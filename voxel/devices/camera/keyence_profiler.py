import logging
import ctypes
import math
import numpy as np
import concurrent.futures
import time
import voxel.devices.camera.sdks.keyence.LJXAwrap as LJXAwrap
from voxel.devices.camera.base import BaseCamera
from voxel.descriptors.deliminated_property import DeliminatedProperty
import threading
import multiprocessing as mp


SAMPLING_RATE = {
    10: 0,
    20: 1,
    50: 2,
    100: 3,
    200: 4,
    500: 5,
    1000: 6,
    2000: 7,
    4000: 8,
    5000: 16
}

EXPOSURE_TIME = {
    0.015: 0,
    0.03: 1,
    0.06: 2,
    0.08: 10,
    0.12: 3,
    0.16: 11,
    0.21: 12,
    0.24: 4,
    0.32: 13,
    0.38: 14,
    0.48: 5,
    0.64: 15,
    0.96: 6,
    1.7: 7,
    4.8: 8,
    9.6: 9
}

def no_lock(func):
    func.__no_lock__ = True
    return func

class Profiler(BaseCamera):
    def __init__(self, id, ip1, ip2, ip3, ip4, portno, hsportno):
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.id = id
        self.device_id = id
        self.ip1 = ip1
        self.ip2 = ip2
        self.ip3 = ip3
        self.ip4 = ip4
        self.portno = portno
        self.hsportno = hsportno
        # self.ethernetConfig = None
        self.ethernetConfig = LJXAwrap.LJX8IF_ETHERNET_CONFIG()
        self.ethernetConfig.abyIpAddress[0] = self.ip1  # IP address
        self.ethernetConfig.abyIpAddress[1] = self.ip2
        self.ethernetConfig.abyIpAddress[2] = self.ip3
        self.ethernetConfig.abyIpAddress[3] = self.ip4
        self.ethernetConfig.wPortNo = self.portno       # Port No.
        self.run_first = True
        self.close_flag = False
        self.my_callback = LJXAwrap.LJX8IF_CALLBACK_SIMPLE_ARRAY(self.callback)
        self._height = 1
        res = LJXAwrap.LJX8IF_EthernetOpen(self.device_id, self.ethernetConfig)
        print("Ethernet connection open for device", self.device_id)
        if res != 0:
            print("Failed to connect controller.")
        print("----")
        print('INITIALIZING')
        self.log.info("INITIALIZNG PROFILER")
        self.camera_ready_event = None
        self.scan_data_ready_event = None
        # self.close()
        # self.prepare()
        
    @no_lock
    def reset(self):
        """
        Reset the camera.
        """
        LJXAwrap.LJX8IF_ReturnToFactorySetting(self.device_id)
        print("Resetting controller to factory settings for device", self.device_id)
        LJXAwrap.LJX8IF_RebootController(self.device_id)
        print("Rebooting controller for device", self.device_id)
        time.sleep(20)
        self.highspeed_com_setup()
        return
    
    @no_lock
    def prepare(self):
        pass

    @no_lock
    def start_highspeed_session(self, total_lines=1000):
        _t0_total = time.perf_counter()
        total_lines = int(total_lines)

        _t0 = time.perf_counter()
        self.highspeed_com_setup(total_lines=total_lines)
        print(f"[KeyenceTiming] start_highspeed_session highspeed_com_setup={time.perf_counter() - _t0:.3f}s")

        _t0 = time.perf_counter()
        self.profile_data_count = self.profinfo.wProfileDataCount
        res = LJXAwrap.LJX8IF_StartHighSpeedDataCommunication(self.device_id)
        print("Starting high speed communication for device", self.device_id)
        print(f"[KeyenceTiming] start_highspeed_session StartHighSpeedDataCommunication={time.perf_counter() - _t0:.3f}s")
        if res != 0:
            raise RuntimeError(f"Error starting high speed communication: {hex(res)}")
        print(
            "[KeyenceTiming] start_highspeed_session total="
            f"{time.perf_counter() - _t0_total:.3f}s lines={total_lines}"
        )
    
    @no_lock
    def highspeed_com_setup(self, total_lines=1000):
        """
        Prepare the camera for acquisition.
        """
        self.log.info("highspeed_com_setup")
        total_lines = int(total_lines)
        ###
        print('P1')
        self.z_data = []      # Processed Z data per tile
        self.lumi_data = []   # Processed luminance data per tile
        self.profinfo = None
        self.start_x = 0
        self.start_y = 0
        self.tile_buffers = []      # List of dictionaries for each tile’s raw data
        self.current_tile_index = 0  # Global pointer for the callback
        self.total_lines = total_lines 
        self.profile_data_count = 0
        self.image_available = False
        self.z_val = [0] * 3200 * self.total_lines
        self.lumi_val = [0] * 3200 * self.total_lines
        print('P2')
        ###
        
        self.laser_on()
        print('P4')
        if self._get_setting(category=0x00, item=0x03)[0] != 1:
            print('Check that batch measurment set')
            self._change_batch_measurement(1)
        self._change_batch_count(bc_value=self._decimal_to_hex_split(self.total_lines))
        
        res = LJXAwrap.LJX8IF_InitializeHighSpeedDataCommunicationSimpleArray(
            self.device_id,
            self.ethernetConfig,
            self.hsportno,
            self.my_callback,
            self.total_lines,
            0
        )
        print('P5')
        print("Initializing high speed communication for device", self.device_id)
        if res != 0:
            print("Error initializing - res - prep")
        
        # if self.run_first:
        req = LJXAwrap.LJX8IF_HIGH_SPEED_PRE_START_REQ()
        req.bySendPosition = 2
        self.profinfo = LJXAwrap.LJX8IF_PROFILE_INFO()
        print(self.profinfo)
        res = LJXAwrap.LJX8IF_PreStartHighSpeedDataCommunication(
            self.device_id,
            req,
            self.profinfo
        )
        # self.run_first = False


        print('P6')
        print("Prestarting high speed communication for device", self.device_id)
        if res != 0:
            print("Error prestarting")
        # self.stop()

        if hasattr(self, 'camera_ready_event') and self.camera_ready_event is not None:
            print("[Profiler] Network Ready. Signaling Engine to start Stage.")
            self.camera_ready_event.set()
        else:
            print("[Profiler] Warning: camera_ready_event is None. Cannot signal Engine.")
        return

    def massfunc(self):
        my_callback = LJXAwrap.LJX8IF_CALLBACK_SIMPLE_ARRAY(self.callback)
        
        
        self.massfunc1(my_callback)
        self.massfunc2()
        self.massfunc3()

    def massfunc1(self, my_callback):
        my_callback = LJXAwrap.LJX8IF_CALLBACK_SIMPLE_ARRAY(self.callback)
        
            
    # def start_setup(self, my_callback):
    #     res = LJXAwrap.LJX8IF_InitializeHighSpeedDataCommunicationSimpleArray(
    #         self.device_id,
    #         self.ethernetConfig,
    #         self.hsportno,
    #         my_callback,
    #         self.total_lines,
    #         0
    #     )
    #     print("Initializing high speed communication for device", self.device_id)
    #     if res != 0:
    #         print("Error initializing")
    #     req = LJXAwrap.LJX8IF_HIGH_SPEED_PRE_START_REQ()
    #     req.bySendPosition = 2
    #     self.profinfo = LJXAwrap.LJX8IF_PROFILE_INFO()
    #     res = LJXAwrap.LJX8IF_PreStartHighSpeedDataCommunication(
    #         self.device_id,
    #         req,
    #         self.profinfo
    #     )
    #     print("Prestarting high speed communication for device", self.device_id)


    #     if res != 0:
    #         print("Error prestarting")
    
    def massfunc2(self):
        self.total_lines = self.total_lines
        self.profile_data_count = self.profinfo.wProfileDataCount
        res = LJXAwrap.LJX8IF_StartHighSpeedDataCommunication(self.device_id)
        print("Starting high speed communication for device", self.device_id)
        if res != 0:
            print("Error starting")

        # self._stage_speed_sync()
        # self._create_pattern()
        

    def massfunc3(self):
        # Allocate tile buffers in advance.
        num_tiles = 1 #len(self.exec_pattern)
        expected = self.profile_data_count * self.total_lines
        self.tile_buffers = []
        for _ in range(num_tiles):
            self.tile_buffers.append({
                "z": [0] * expected,
                "lumi": [0] * expected,
                "count": 0,
                "expected": expected,
                "complete": False
            })
        self.current_tile_index = 0

        LJXAwrap.LJX8IF_StartMeasure(self.device_id)
        # time.sleep(10)
        while not self.image_available:
            time.sleep(0.05)
        print(f"Starting wait_and_process_tile ")
        z_arr = self.get_z_val_array()
        # z_arr, lumi_arr = 
        # self.wait_and_process_tile(self.tile_buffers[0], self.profile_data_count)
        print(f"Starting append ")
        self.z_data.append(z_arr)

        # self.lumi_data.append(lumi_arr)
        print(f"returning data  ")
        # print(np.unique(self.get_z_data()))
        return #self.get_z_data(), self.total_lines

    @no_lock
    def get_z_val_array(self):
        # Vectorized conversion of packed profiler heights to mm.
        z_raw = np.asarray(self.z_val, dtype=np.int32)
        z_unit = float(self.get_z_unit())
        scale = (z_unit / 100.0) / 1000.0

        z_mm = (z_raw.astype(np.float64) - 32768.0) * scale
        z_mm[z_raw == 0] = np.nan

        z_val_arr = z_mm.reshape((self.total_lines, self.profinfo.wProfileDataCount))
        return np.around(z_val_arr, decimals=4)
        
    @property
    @no_lock
    def latest_frame(self):
        return np.ones((40, 3200))
    
    @no_lock
    def start_thread(self):
        self.image_available = False
        if self.scan_data_ready_event is not None:
            try:
                self.scan_data_ready_event.clear()
            except Exception:
                pass
        self.start_highspeed_session(self.total_lines)

        time.sleep(1) ## Extremely important sleep here!!!

        print('STARTING THREAD')
        self.log.info("start_thread")
        self.profile_data_count = self.profinfo.wProfileDataCount
        # start = time.time()
        # while time.time()-start<20:
        #     time.sleep(1)

        # print('STOP MEASURE')
        # LJXAwrap.LJX8IF_StopMeasure(self.device_id)
        # LJXAwrap.LJX8IF_StartMeasure(self.device_id)
        self.log.info(f"PK - 1")
    
        _wait_start = time.perf_counter()
        while not self.image_available:
            self.log.info(f"image available {self.image_available}")
            time.sleep(1)
        print(f"[KeyenceTiming] start_thread image_available=True after {time.perf_counter() - _wait_start:.3f}s")

        # if self.image_available:
        #     self.log.info(f"I AM TRUE ALWAYS")

        self.log.info("before the close in threads")
        _close_start = time.perf_counter()
        print("[KeyenceTiming] start_thread calling close()")
        self.close()
        print(f"[KeyenceTiming] start_thread close() returned in {time.perf_counter() - _close_start:.3f}s")
        print("[KeyenceTiming] start_thread exiting")

    # def stop_communication(self):
    #     LJXAwrap.LJX8IF_StopHighSpeedDataCommunication(self.device_id)
    #     print("\nStopping high speed communication for device", self.device_id)
    #     LJXAwrap.LJX8IF_FinalizeHighSpeedDataCommunication(self.device_id)
    #     print("Finalizing high speed communication for device", self.device_id)

    @no_lock
    def start(self, total_lines):
        self.total_lines = int(total_lines)
        self.height_px = int(total_lines)
        self.keyence_producer_thread = threading.Thread(target=self.start_thread, name="ProducerThread")
        self.keyence_producer_thread.start()
        # self.camera_ready_event.set()


    @no_lock
    def getFrame_alloc(self):
        _getframe_start = time.perf_counter()
        print('IN GET FRAME FUNCTION')
        self.log.info(f"Get frame function profiler")
        _wait_start = time.perf_counter()
        _wait_loops = 0
        while not self.image_available:
            self.log.info(f"image_available{self.image_available}")
            # print(self.image_available)
            time.sleep(0.05)
            _wait_loops += 1
        print(f"[KeyenceTiming] getFrame_alloc wait_for_image_available={time.perf_counter() - _wait_start:.3f}s loops={_wait_loops}")
        if self.scan_data_ready_event is not None:
            try:
                self.scan_data_ready_event.set()
                print("[KeyenceTiming] getFrame_alloc signaled scan_data_ready_event=True")
            except Exception as exc:
                print(f"[KeyenceTiming] getFrame_alloc failed to set scan_data_ready_event: {exc}")
        
        _t0 = time.perf_counter()
        z_arr = self.get_z_val_array()
        _z_elapsed = time.perf_counter() - _t0
        print(f"[KeyenceTiming] getFrame_alloc get_z_val_array={_z_elapsed:.3f}s shape={z_arr.shape}")

        _t0 = time.perf_counter()
        lumi_arr = np.array(self.lumi_val).reshape((self.total_lines, self.profinfo.wProfileDataCount))
        _lumi_elapsed = time.perf_counter() - _t0
        print(f"[KeyenceTiming] getFrame_alloc lumi_reshape={_lumi_elapsed:.3f}s shape={lumi_arr.shape}")

        # z_arr, lumi_arr = self.wait_and_process_tile(self.tile_buffers[0], self.profile_data_count)
        # print("This is z_arr", z_arr)
        # print("This is lumi_arr", lumi_arr)
        # print("Shape of z_arr:", z_arr.shape)
        # print("Shape of lumi_arr:", lumi_arr.shape)
        _t0 = time.perf_counter()
        combined_arr = np.stack((z_arr, lumi_arr), axis=0)
        _stack_elapsed = time.perf_counter() - _t0
        print(f"[KeyenceTiming] getFrame_alloc stack_arrays={_stack_elapsed:.3f}s shape={combined_arr.shape}")
        # self.z_data.append(z_arr)
        # self.lumi_data.append(lumi_arr)
        # LJXAwrap.LJX8IF_CALLBACK_SIMPLE_ARRAY(self.callback)
        # print(f"Starting wait_and_process_tile ")
        # z_arr, lumi_arr = self.wait_and_process_tile(self.tile_buffers[0], self.profile_data_count)
        # # print(f"Starting append ")
        # self.z_data.append(z_arr)
        # self.lumi_data.append(lumi_arr)
        # print(f"returning data  ")
        # self.keyence_producer_thread.join()

        print("[KeyenceTiming] getFrame_alloc calling thread_join()")
        self.thread_join()
        print(f"[KeyenceTiming] getFrame_alloc total={time.perf_counter() - _getframe_start:.3f}s")
        return combined_arr, self.total_lines

    @no_lock
    def thread_join(self):
        thread_alive_before = self.keyence_producer_thread.is_alive() if hasattr(self, "keyence_producer_thread") else False
        print(f"[KeyenceTiming] thread_join before join alive={thread_alive_before}")
        _t0 = time.perf_counter()
        self.keyence_producer_thread.join()
        join_elapsed = time.perf_counter() - _t0
        thread_alive_after = self.keyence_producer_thread.is_alive() if hasattr(self, "keyence_producer_thread") else False
        print(f"[KeyenceTiming] thread_join after join elapsed={join_elapsed:.3f}s alive={thread_alive_after}")
        print("In keyence, thread has been joined!!")


    @no_lock
    def immediate_start(self, total_lines):
        """
        Start the camera acquisition.
        """
        
        self.total_lines = total_lines
        self.profile_data_count = self.profinfo.wProfileDataCount
        res = LJXAwrap.LJX8IF_StartHighSpeedDataCommunication(self.device_id)
        print("Starting high speed communication for device", self.device_id)
        if res != 0:
            print("Error starting")

        # self._stage_speed_sync()
        # self._create_pattern()

        # Allocate tile buffers in advance.
        num_tiles = 1 #len(self.exec_pattern)
        expected = self.profile_data_count * total_lines
        self.tile_buffers = []
        for _ in range(num_tiles):
            self.tile_buffers.append({
                "z": [0] * expected,
                "lumi": [0] * expected,
                "count": 0,
                "expected": expected,
                "complete": False
            })
        self.current_tile_index = 0

        LJXAwrap.LJX8IF_StartMeasure(self.device_id)

        print("Starting measure for device", self.device_id)
        return
        
    def stop(self):
        pass

    @no_lock
    def close(self):
        """
        Close the camera and release resources.
        """
        # self.stop()
        # paired with preinitalization
        self.log.info("Running close")
        _close_start = time.perf_counter()
        print('H1x')
        _t0 = time.perf_counter()
        LJXAwrap.LJX8IF_StopMeasure(self.device_id)
        print(f"[KeyenceTiming] close StopMeasure={time.perf_counter() - _t0:.3f}s")
        print('H2x')
        _t0 = time.perf_counter()
        res = LJXAwrap.LJX8IF_StopHighSpeedDataCommunication(self.device_id)
        print(f"[KeyenceTiming] close StopHighSpeedDataCommunication={time.perf_counter() - _t0:.3f}s")
        print("LJXAwrap.LJX8IF_StoptHighSpeedDataCommunication:", hex(res))
        _t0 = time.perf_counter()
        self.laser_off()
        print(f"[KeyenceTiming] close laser_off={time.perf_counter() - _t0:.3f}s")
        print('H3x')
        _t0 = time.perf_counter()
        res = LJXAwrap.LJX8IF_FinalizeHighSpeedDataCommunication(self.device_id)
        print(f"[KeyenceTiming] close FinalizeHighSpeedDataCommunication={time.perf_counter() - _t0:.3f}s")
        print("LJXAwrap.LJX8IF_FinalizeHighSpeedDataCommunication:", hex(res))
        print('H4x')
        # LJXAwrap.LJX8IF_CommunicationClose(self.device_id)
        print('H5x')
        print(f"[KeyenceTiming] close total={time.perf_counter() - _close_start:.3f}s")
        # print("----")
        # print("Ethernet connection closed for device", self.device_id)
        return

    @no_lock
    def close_communication(self):
        LJXAwrap.LJX8IF_CommunicationClose(self.device_id)
        print('H6X')

    @no_lock
    def laser_on(self):
        _t0 = time.perf_counter()
        LJXAwrap.LJX8IF_ControlLaser(self.device_id, 1)
        print(f"[KeyenceTiming] laser_on={time.perf_counter() - _t0:.3f}s")
        print("Turning on laser for device", self.device_id)
        return
    
    @no_lock
    def laser_off(self):
        _t0 = time.perf_counter()
        LJXAwrap.LJX8IF_ControlLaser(self.device_id, 0)
        print(f"[KeyenceTiming] laser_off={time.perf_counter() - _t0:.3f}s")
        print("Turning off laser for device", self.device_id)
        return
    
    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    @no_lock
    def height_px(self):
        return self._height
    
    @height_px.setter
    @no_lock
    def height_px(self, value: int):
        self._height = value

    @property
    @no_lock
    def binning(self):
        binning = 1
        return binning
    
    @binning.setter
    @no_lock
    def binning(self, binning):
        pass

    @DeliminatedProperty(minimum=float('-inf'), maximum=float('inf'))
    @no_lock
    def width_px(self):
        return 3200#self.profinfo.wProfileDataCount
        
    
    @width_px.setter
    @no_lock
    def width_px(self, value: int):
        pass

    @property
    @no_lock
    def sampling_rate_hz(self):
        rate_value = self._get_setting(category=0x00, item=0x02)[0]
        rate_key = next(rate_key for rate_key, val in SAMPLING_RATE.items() if val == rate_value)
        return rate_key
    
    @sampling_rate_hz.setter
    @no_lock
    def sampling_rate_hz(self, rate):
        rate_value = SAMPLING_RATE[rate]
        self._set_setting(category=0x00, item=0x02, value=[rate_value, 0, 0, 0])
    
    @property
    @no_lock
    def exposure_time_ms(self):
        return 0.5
    
    @exposure_time_ms.setter
    @no_lock
    def exposure_time_ms(self, time):
        pass

    @property
    @no_lock
    def actual_exposure_time_ms(self):
        time_value = self._get_setting(category=0x01, item=0x06)[0]
        print('Time_value', time_value)
        time_key = next(time_key for time_key, val in EXPOSURE_TIME.items() if val == time_value)
        return time_key
    
    @actual_exposure_time_ms.setter
    @no_lock
    def actual_exposure_time_ms(self, time):
        time_value = EXPOSURE_TIME[time]
        self._set_setting(category=0x01, item=0x06, value=[time_value, 0, 0, 0])
    
    @property
    @no_lock
    def dynamic_range(self):
        dr_value = self._get_setting(category=0x01, item=0x05)[0]
        return dr_value
    
    @dynamic_range.setter
    @no_lock
    def dynamic_range(self, dr):
        self._set_setting(category=0x01, item=0x05, value=[dr, 0, 0, 0])
    
    @no_lock
    def _get_setting(self, category, item, depth=1, type=0x10):
        target_setting = LJXAwrap.LJX8IF_TARGET_SETTING()
        target_setting.byType = type         # Program No.
        target_setting.byCategory = category # Trigger category
        target_setting.byItem = item         # Item
        target_setting.byTarget1 = 0x00      # reserved
        target_setting.byTarget2 = 0x00      # reserved
        target_setting.byTarget3 = 0x00      # reserved
        target_setting.byTarget4 = 0x00      # reserved

        data_size = 4

        # Get setting to confirm
        setting_data_get = (ctypes.c_ubyte * data_size)()
        LJXAwrap.LJX8IF_GetSetting(self.device_id, depth,
                                         target_setting,
                                         setting_data_get, data_size)
        return setting_data_get
    
    @no_lock
    def _set_setting(self, category, item, value, depth=1, type=0x10):
        target_setting = LJXAwrap.LJX8IF_TARGET_SETTING()
        target_setting.byType = type         # Program No.
        target_setting.byCategory = category # Trigger category
        target_setting.byItem = item         # Item
        target_setting.byTarget1 = 0x00      # reserved
        target_setting.byTarget2 = 0x00      # reserved
        target_setting.byTarget3 = 0x00      # reserved
        target_setting.byTarget4 = 0x00      # reserved

        data_size = 4

        # Set the value
        err = ctypes.c_uint()
        py_arr = value
        setting_data_set = (ctypes.c_ubyte * data_size)(*py_arr)

        LJXAwrap.LJX8IF_SetSetting(self.device_id, depth,
                                         target_setting,
                                         setting_data_set, data_size, err)
    
    @no_lock
    def _change_batch_measurement(self, bm_value=1):
        self._set_setting(category=0x00, item=0x03, value=[bm_value, 0, 0, 0])
    
    @no_lock
    def _change_batch_count(self, bc_value=[39, 16]):
        print("In keyence, bc_value ", bc_value)
        self._set_setting(category=0x00, item=0x0A, value=[bc_value[1], bc_value[0], 0, 0])

    @no_lock
    def callback(self, p_header, p_height, p_lumi, luminance_enable, xpointnum, profnum, notify, user):
        self.log.info('WE ARE IN CALL BACK')

        print('In Keyence, we are in callback')
        print(f'In Keyence, the status of luminance_enable is {luminance_enable}')
        if (notify == 0) or (notify == 0x10000):
            if profnum != 0:
                print('C1')
                if self.image_available is False:
                    print('C2')
                    for i in range(xpointnum * profnum):
                        self.z_val[i] = p_height[i]
                        if luminance_enable == 1:
                            self.lumi_val[i] = p_lumi[i]
                    print('C3')
                    self.total_lines_acquired = profnum
                    self.image_available = True
        return

    # @no_lock
    # def _decimal_to_hex_split(self, decimal_num):
    #     hex_str = format(decimal_num, 'X')
    #     if len(hex_str) % 2 != 0:
    #         hex_str = '0' + hex_str
    #     return [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]

    @no_lock
    def _decimal_to_hex_split(self, decimal_num):
        hex_str = format(decimal_num, '04X')  # always 4 hex digits = 2 bytes
        return [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]

    
    @no_lock
    def process_data(self, raw_z, raw_lumi, total_lines, profile_data_count):
        print("IN process_data")
        ZUnit = self.get_z_unit()
        print("H!")
        z_np = np.array(raw_z, dtype=float)
        mask = (z_np == 0)
        converted = ((z_np - 32768) * (ZUnit / 100.0)) / 1000.0
        converted[mask] = np.nan
        print("H2")
        z_arr = np.around(converted.reshape((total_lines, profile_data_count)), decimals=4)
        lumi_arr = np.array(raw_lumi).reshape((total_lines, profile_data_count))
        print("H3")
        return z_arr, lumi_arr
    
    @no_lock
    def wait_and_process_tile(self, tile_buffer, profile_data_count):
        # Wait until this tile's data acquisition is complete (with a timeout)
        print("IN wait_and_process_tile")
        # wait_timeout = 10  # seconds
        # start_wait = time.perf_counter()
        while not self.image_available: #and time.perf_counter() - start_wait < wait_timeout:
            flag  = self.image_available
            self.log.info(f"complete flag: {flag}")
            # print(f"complete flag: {flag}")
            time.sleep(0.005)
        # if not tile_buffer["complete"]:
        #     self.log.info("Warning: tile acquisition did not complete within timeout.")
        return self.process_data(tile_buffer["z"], tile_buffer["lumi"], self.total_lines, profile_data_count)
    
    @no_lock
    def get_z_unit(self):
        ZUnit = ctypes.c_ushort()
        LJXAwrap.LJX8IF_GetZUnitSimpleArray(self.device_id, ZUnit)
        return ZUnit.value

    @no_lock
    def get_z_data(self):
        return np.array(self.z_data)

    @no_lock
    def get_lumi_data(self):
        return np.array(self.lumi_data)
    

        # # Use a thread pool to process tiles as soon as they are done.
        # self.log.info(f"Starting wait_and_process_tile ")
        # z_arr, lumi_arr = self.wait_and_process_tile(self.tile_buffers[0], self.profile_data_count)

        # # futures = []
        # # with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        #     # for idx, tile in enumerate(self.exec_pattern):
        #         # Issue stage movement for tile idx.
        #         # self.stage.run_tile(self.exec_pattern[tile][0],
        #         #                     self.start_x,
        #         #                     self.start_y + idx * LINE_WIDTH, 'X')
        #     # print(f"Tile {idx} stage movement commanded.")
        #         # Immediately schedule processing for this tile.
        #         # (The wait_and_process_tile function will block until the tile buffer is complete.)
         
        #     # self.log.info(f"Starting future submission")
        #     # future = executor.submit(self.wait_and_process_tile, self.tile_buffers[0], self.profile_data_count)
        
        #     # futures.append(future)
        #         # Continue to next tile command without waiting.
        #     # At this point, stage movement commands for all tiles have been issued.
        #     # We now wait for each tile's processing to finish.
        #     # self.log.info(f"Starting append of waiting ")
        #     # concurrent.futures.wait(futures)
            
        #     # for future in futures:
        #     # self.log.info(f"For loop of future ")
        #     # z_arr, lumi_arr = future.result()
        # self.log.info(f"Starting append ")
        # self.z_data.append(z_arr)
        #     # self.z_data.insert(0, z_arr)
        #     # np.insert(self.z_data, 0, z_arr)
        # self.lumi_data.append(lumi_arr)
        #     # self.lumi_data.insert(0, lumi_arr)
        #     # np.insert(self.lumi_data, 0, lumi_arr)

        # # finally:
            
        # #     LJXAwrap.LJX8IF_StopHighSpeedDataCommunication(self.device_id)
        # #     print("\nStopping high speed communication for device", self.device_id)
        # #     LJXAwrap.LJX8IF_FinalizeHighSpeedDataCommunication(self.device_id)
        # #     print("Finalizing high speed communication for device", self.device_id)
        # #     self.stage.set_speed(27.0, 'X')
        # self.log.info(f"returning data  ")
        # return self.get_z_data(), self.total_lines

         
    # def stop(self):
    #     """
    #     Stop the camera acquisition.
    #     """
    #     try:
    #         print('H1')
    #         # LJXAwrap.LJX8IF_StopMeasure(self.device_id)
    #         print('H2')
    #         # LJXAwrap.LJX8IF_StopHighSpeedDataCommunication(self.device_id)
    #         print("\nH3 - Stopping high speed communication for device", self.device_id)
    #         LJXAwrap.LJX8IF_FinalizeHighSpeedDataCommunication(self.device_id)
    #         print(" H 4- Finalizing high speed communication for device", self.device_id)
    #     except:
    #         print('FAILED TO STOP')
    #     self.laser_off()
    #     print("Stopping measure for device", self.device_id)
    #     return

    
    # def callback(self, p_header, p_height, p_lumi, luminance_enable, xpointnum, profnum, notify, user):
    #     # The callback writes incoming data sequentially into the tile buffers.
    #     self.log.info('STARTING CALL BACK FUNCTION')
    #     if notify in (0, 0x10000) and profnum != 0:
    #         self.log.info('IF notify')
    #         num_samples = xpointnum * profnum
    #         data_idx = 0  # pointer into the provided arrays
    #         while num_samples > 0 and self.current_tile_index < len(self.tile_buffers):
    #             self.log.info('WHILE num_samples')
    #             buf = self.tile_buffers[self.current_tile_index]
    #             remaining = buf["expected"] - buf["count"]
    #             if remaining <= 0:
    #                 self.log.info('if remaining')
    #                 buf["complete"] = True
    #                 self.current_tile_index += 1
    #                 continue
    #             n = min(num_samples, remaining)
    #             start = buf["count"]
    #             end = start + n
    #             buf["z"][start:end] = p_height[data_idx:data_idx+n]
    #             if luminance_enable == 1:
    #                 buf["lumi"][start:end] = p_lumi[data_idx:data_idx+n]
    #             buf["count"] += n
    #             data_idx += n
    #             num_samples -= n
    #             self.log.info('HX!')
    #             if buf["count"] == buf["expected"]:
    #                 buf["complete"] = True
    #                 self.current_tile_index += 1

    # def _create_pattern(self):
    #     self.exec_pattern = {}
    #     width = self.roi[0]
    #     num_of_tiles = math.ceil(width / LINE_WIDTH)
    #     for i in range(num_of_tiles):
    #         # Alternate scan direction for each tile.
    #         height = -self.roi[1] if i % 2 else self.roi[1]
    #         if i == num_of_tiles - 1:
    #             self.exec_pattern['Tile ' + str(i)] = (height, 0)
    #         else:
    #             self.exec_pattern['Tile ' + str(i)] = (height, LINE_WIDTH)
    #     print("Execution pattern:", self.exec_pattern)

    # def _stage_speed_sync(self):
    #     rates = {
    #         0: 10, 1: 20, 2: 50, 3: 100, 4: 200,
    #         5: 500, 6: 1000, 7: 2000, 8: 4000, 16: 5000
    #     }
    #     rate = self._get_setting(category=0x00, item=0x02)[0]
    #     self.stage.set_speed(rates[rate] * SAMPLING_PITCH_UM / 1000, 'X')
    #     self.timeout_sec = int(self.total_lines / rates[rate]) + 30
    #     print("Stage speed synced.")

        # my_callback = LJXAwrap.LJX8IF_CALLBACK_SIMPLE_ARRAY(self.callback)
        # # self.start_setup(my_callback)


        # self.total_lines = total_lines
        # self.profile_data_count = self.profinfo.wProfileDataCount
        # res = LJXAwrap.LJX8IF_StartHighSpeedDataCommunication(self.device_id)
        # print("Starting high speed communication for device", self.device_id)
        # self.log.info(f"starting the ocmmunication for devices")
        # if res != 0:
        #     print("Error starting")

        # # self._stage_speed_sync()
        # # self._create_pattern()

        # # Allocate tile buffers in advance.
        # # num_tiles = 1 #len(self.exec_pattern)
        # # expected = self.profile_data_count * total_lines
        # # self.tile_buffers = []
        # # for _ in range(num_tiles):
        # #     self.tile_buffers.append({
        # #         "z": [0] * expected,
        # #         "lumi": [0] * expected,
        # #         "count": 0,
        # #         "expected": expected,
        # #         "complete": False
        # #     })
        # # self.current_tile_index = 0

        # self.log.info(f"PK - 1")

        # # num_tiles = 1 #len(self.exec_pattern)
        # # expected = self.profile_data_count * self.total_lines
        # # self.tile_buffers = []
        # # for _ in range(num_tiles):
        # #     self.tile_buffers.append({
        # #         "z": [0] * expected,
        # #         "lumi": [0] * expected,
        # #         "count": 0,
        # #         "expected": expected,
        # #         "complete": False
        # #     })
        # self.log.info(f"PK - 2")
        # # self.current_tile_index = 0
        # # time.sleep(5)
        # # LJXAwrap.LJX8IF_StartMeasure(self.device_id)
        # while not self.image_available:
        #     time.sleep(0.05)
        # if self.image_available:
        #     print(' I AM TRUE')
        # # while not self.image_available:
        # #     time.sleep(0.05)
        
        # # print(f"Starting wait_and_process_tile ")
        # # z_arr = self.get_z_val_array()
        # # # z_arr, lumi_arr = 
        # # # self.wait_and_process_tile(self.tile_buffers[0], self.profile_data_count)
        # # print(f"Starting append ")
        # # self.z_data.append(z_arr)
        # # print(np.unique(z_arr))
        # # # self.lumi_data.append(lumi_arr)
        # # print(f"returning data  ")
        # # # print(np.unique(self.get_z_data()))
        # # return #self.get_z_data(), self.total_lines
    

        # # print(f"Starting wait_and_process_tile ")
        # # z_arr, lumi_arr = self.wait_and_process_tile(self.tile_buffers[0], self.profile_data_count)
        # # print(f"Starting append ")
        # # self.z_data.append(z_arr)
        # # self.lumi_data.append(lumi_arr)
        # # print(f"returning data  ")
        # # return self.get_z_data(), self.total_lines
