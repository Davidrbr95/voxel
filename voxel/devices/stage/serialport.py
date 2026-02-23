from serial import Serial
from serial import SerialException
from serial import EIGHTBITS
from serial import PARITY_NONE
from serial import STOPBITS_ONE
from serial.tools import list_ports
import time
 
class SerialPort:
    """
    A utility class for managing a RS232 serial connection using the pyserial library.
 
    """
 
    def __init__(self, com_port: str, baud_rate: int, report: bool = True):
        self.serial_port = Serial()
        self.com_port = com_port
        self.baud_rate = baud_rate
        # user feedback settings
        self.report = report
        self.print = self.report_to_console
 
    @staticmethod
    def scan_ports() -> list[str]:
        """Returns a sorted list of COM ports."""
        com_ports = [port.device for port in list_ports.comports()]
        com_ports.sort(key=lambda value: int(value[3:]))
        return com_ports
 
    def connect_to_serial(self, rx_size: int = 12800, tx_size: int = 12800, read_timeout: int = 1, write_timeout: int = 1) -> None:
        """Connect to the serial port."""
        # serial port settings
        self.serial_port.port = self.com_port
        self.serial_port.baudrate = self.baud_rate
        self.serial_port.parity = PARITY_NONE
        self.serial_port.bytesize = EIGHTBITS
        self.serial_port.stopbits = STOPBITS_ONE
        self.serial_port.xonoff = False
        self.serial_port.rtscts = False
        self.serial_port.dsrdtr = False
        self.serial_port.write_timeout = write_timeout
        self.serial_port.timeout = read_timeout
 
        # set the size of the rx and tx buffers before calling open
        self.serial_port.set_buffer_size(rx_size, tx_size)
 
        # try to open the serial port
        try:
            self.serial_port.open()
        except SerialException:
            self.print(f"SerialException: can't connect to {self.com_port} at {self.baud_rate}!")

        print('SERIAL in connect', self.is_open())
        if self.is_open():
            # clear the rx and tx buffers
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            # report connection status to user
            self.print("Connected to the serial port.")
            self.print(f"Serial port = {self.com_port} :: Baud rate = {self.baud_rate}")
 
    def disconnect_from_serial(self) -> None:
        """Disconnect from the serial port if it's open."""
        if self.is_open():
            self.serial_port.close()
            self.print("Disconnected from the serial port.")
 
    def is_open(self) -> bool:
        """Returns True if the serial port exists and is open."""
        # short circuits if serial port is None
        return self.serial_port and self.serial_port.is_open
 
    def report_to_console(self, message: str) -> None:
        """Print message to the output device, usually the console."""
        # useful if we want to output data to something other than the console (ui element etc)
        if self.report:
            print(message)
 
    def send_command(self, cmd: bytes) -> None:
        """Send a serial command to the device."""
        # always reset the buffers before a new command is sent
        self.serial_port.reset_input_buffer()
        self.serial_port.reset_output_buffer() # -- can be eliminated nothing breaks
        # send the serial command to the controller
        command = bytes(f"{cmd}\r", encoding="ascii")
        self.serial_port.write(command)
        # self.print(f"Send: {command.decode(encoding='ascii')}")
 
    def send_command_v2(self, cmd: bytes) -> None:
        """Send a serial command to the device."""
        # always reset the buffers before a new command is sent
        # t0 = time.perf_counter()
        # t_response = time.perf_counter()-t0
        # print("Time to reset input buffer:", t_response)


        # send the serial command to the controller
        # t0 = time.perf_counter()
        command = bytes(f"{cmd}\r", encoding="ascii")
        self.serial_port.write(command)
        # t_response = time.perf_counter()-t0
        # print("Time to send write command:", t_response)
 
    def send_command_v3(self, cmd: bytes) -> None:
        """Send a serial command to the device."""
        # always reset the buffers before a new command is sent
        t0 = time.perf_counter()
        # self.serial_port.reset_input_buffer()
        t_response = time.perf_counter()-t0
        print("Time to reset input buffer:", t_response)

        # self.serial_port.reset_output_buffer()
        # send the serial command to the controller
        t0 = time.perf_counter()
        command = bytes(f"{cmd}\r", encoding="ascii")
        self.serial_port.write(command)
        t_response = time.perf_counter()-t0
        print("Time to send write command:", t_response)
        # self.print(f"Send: {command.decode(encoding='ascii')}")
 
    def read_response(self) -> str:
        """Read a line from the serial response."""
        time.sleep(0.005)
        
        # t0 = time.perf_counter()
        
        response = self.serial_port.readline()

        # response = self.serial_port.read_until(b'\r\n')
        # t_response = time.perf_counter()-t0
        # print("Response time:", t_response, response)
        # response = self.serial_port.readall()
        # t0 = time.perf_counter()
        
        response = response.decode(encoding="ascii")
        
        # t_response = time.perf_counter()-t0
        # print("Decode time:", t_response, response)
        # self.print(f"Recv: {response.strip()}")
        return response # in case we want to read the response
    
    def read_response_V2(self) -> str:
        """Read a line from the serial response."""
        time.sleep(0.005)
        
        # t0 = time.perf_counter()
        
        response = self.serial_port.read_all()
        # t_response = time.perf_counter()-t0
        # print("Response time:", t_response, response)
        # t0 = time.perf_counter()
        
        response = response.decode(encoding="ascii")
        
        # t_response = time.perf_counter()-t0
        # print("Read response time:", t_response, response)
        return response # in case we want to read the response
    
    def read_response_slow(self) -> str:
        """Read a line from the serial response."""
        time.sleep(0.5)
        
        # t0 = time.perf_counter()
        
        response = self.serial_port.read_all()
        # t_response = time.perf_counter()-t0
        # print("Response time:", t_response, response)
        # t0 = time.perf_counter()
        
        response = response.decode(encoding="ascii")
        
        # t_response = time.perf_counter()-t0
        # print("Read response time:", t_response, response)
        return response # in case we want to read the response
    
    # def read_response(self, terminator: bytes = b"\r\n",
    #               hard_timeout: float = 0.10) -> str:
    #     """
    #     Read one complete reply line from the stage.

    #     Parameters
    #     ----------
    #     terminator : bytes
    #         Line terminator expected from the controller (default b"\r\n").
    #     hard_timeout : float
    #         Absolute upper-bound (in seconds) to wait for a full line
    #         before raising TimeoutError.

    #     Returns
    #     -------
    #     str
    #         The reply decoded as ASCII (including the terminator).

    #     Raises
    #     ------
    #     TimeoutError
    #         If no complete reply is received within *hard_timeout*.
    #     """
    #     # ------------------------------------------------------------------ send
    #     # t0_send = time.perf_counter()
    #     # (caller's write happens elsewhere – no sleep needed here)

    #     # ------------------------------------------------------------------ recv
    #     buf = bytearray()
    #     t0_recv = time.perf_counter()
    #     while True:
    #         # Grab everything waiting right now; `or 1` prevents a zero-length read
    #         buf += self.serial_port.read(self.serial_port.in_waiting or 1)

    #         # Finished?
    #         if buf.endswith(terminator):
    #             break

    #         # Hard timeout guard
    #         if time.perf_counter() - t0_recv > hard_timeout:
    #             raise TimeoutError(f"Incomplete reply after {hard_timeout*1e3:.1f} ms: {buf!r}")

    #         # Short nap to keep CPU usage low
    #         time.sleep(0.0003)

    #     # ------------------------------------------------------------------ stats
    #     # t_overall = time.perf_counter() - t0_send
    #     # t_response = time.perf_counter() - t0_recv
    #     # print(f"Overall response time: {t_overall:.6f}s")
    #     # print(f"  └─ receive time    : {t_response:.6f}s  {bytes(buf)!r}")

    #     # ------------------------------------------------------------------ decode
    #     # t0_decode = time.perf_counter()
    #     reply_str = buf.decode("ascii")
    #     # t_decode = time.perf_counter() - t0_decode
    #     # print(f"  └─ decode time     : {t_decode:.6f}s  {reply_str}")

    #     return reply_str
        
    def read_response_linebyline(self) -> str:
        """Read a line from the serial response."""
        response = self.serial_port.read()
        response = response.decode(encoding="ascii")
        # self.print(f"Recv: {response.strip()}")
        return response # in case we want to read the response