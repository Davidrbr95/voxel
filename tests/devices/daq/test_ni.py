from pathlib import Path
import os, sys
import time
# Get the current script directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define the paths to Voxel and View
voxel_path = os.path.join(current_dir, '../../../../Voxel')
view_path = os.path.join(current_dir, '../../../../View')

# Add these paths to sys.path if they are not already present
if voxel_path not in sys.path:
    sys.path.append(voxel_path)
    print(f"Added {voxel_path} to sys.path")

if view_path not in sys.path:
    sys.path.append(view_path)
    print(f"Added {view_path} to sys.path")

# from voxel.devices.daq.ni import DAQ
from ruamel.yaml import YAML

from voxel.devices.daq.ni import DAQ

this_dir = Path(__file__).parent.resolve() # directory of this test file.
config_path = r"C:\Users\AIBS\Desktop\UHR-OTLS-control\Control\gui_config.yaml"#this_dir / Path("test_ni.yaml")
config = YAML().load(Path(config_path))
print(config.keys())
ao_task = config['instrument_view']['livestream_tasks']['PCIe-6738']['tasks']['co_task']
# do_task = config['pcie-6738']['tasks']['do_task']
# co_task = config['pcie-6738']['tasks']['co_task']
daq = DAQ("Dev2")
daq.tasks = config['instrument_view']['livestream_tasks']['PCIe-6738']['tasks']
# daq.add_task('co')
# daq.add_task('do')
# daq.add_task('co')
# daq.generate_waveforms('co', 'CH561')
# daq.generate_waveforms('do',  'CH61')
# daq.write_ao_waveforms()
# daq.write_do_waveforms()
#daq.plot_waveforms_to_pdf()
if daq.tasks.get('co_task', None) is not None:
    pulse_count = daq.tasks['co_task']['timing'].get('pulse_count', None)
    daq.add_task('co', pulse_count)
daq.start()
time.sleep(10)
daq.close_all()