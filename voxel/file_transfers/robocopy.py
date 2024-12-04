# import os
# import shutil
# import time
# from pathlib import Path
# from voxel.descriptors.deliminated_property import DeliminatedProperty
# from subprocess import DEVNULL, Popen
# import logging
# from voxel.file_transfers.base import BaseFileTransfer


# class RobocopyFileTransfer(BaseFileTransfer):
#     """
#     Voxel driver for Robocopy file transfer process.

#     Process will transfer files with the following regex
#     format:

#     From -> \\\\local_path\\\\acquisition_name\\\\filename*
#     To -> \\\\external_path\\\\acquisition_name\\\\filename*

#     :param external_path: External path of files to be transferred
#     :param local_path: Local path of files to be transferred
#     :type external_path: str
#     :type local_path: str
#     """

#     def __init__(self, external_path: str, local_path: str):
#         super().__init__(external_path, local_path)
#         local_directory = Path(self._local_path, self._acquisition_name)
#         log_path = Path(local_directory, f"{self._filename}.log")
#         # Configure logging without assigning to self.log
#         logging.basicConfig(filename=log_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#         # Optionally, reassign self.log if you want to ensure it's properly set
#         self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
#         self._protocol = "robocopy"

#     def _run(self):
#         start_time = time.time()
#         local_directory = Path(self._local_path, self._acquisition_name)
#         external_directory = Path(self._external_path, self._acquisition_name)
#         log_path = Path(local_directory, f"{self._filename}.log")
#         transfer_complete = False
#         retry_num = 0
#         # loop over number of attempts in the event that a file transfer fails
#         while transfer_complete == False and retry_num <= self._max_retry-1:
#             # generate a list of subdirs and files in the parent local dir to delete at the end
#             delete_list = []
#             for name in os.listdir(local_directory.absolute()):
#                 if self.filename in name:
#                     delete_list.append(name)
#             # generate a list of files to copy
#             # path is the entire experiment path
#             # subdirs is any tile specific subdir i.e. zarr store
#             # files are any tile specific files
#             file_list = dict()
#             for path, subdirs, files in os.walk(local_directory.absolute()):
#                 for name in files:
#                     # check and only add if filename matches tranfer's filename but not the log file
#                     if self.filename in name and name != log_path:
#                         file_list[os.path.join(path, name)] = os.path.getsize(os.path.join(path, name))/1024**2
#             print('file_list copy', file_list)
#             total_size_mb = sum(file_list.values())
#             # sort the file list based on the file sizes and create a list for transfers
#             sorted_file_list = dict(sorted(file_list.items(), key = lambda item: item[1]))
#             total_transferred_mb = 0
#             # if file list is empty, transfer must be complete
#             if not sorted_file_list:
#                 transfer_complete = True
#             # if not, try to initiate transfer again
#             else:
#                 num_files = len(sorted_file_list)
#                 self.log.info(f'attempt {retry_num+1}/{self._max_retry}, tranferring {num_files} files.')
#                 for file_path, file_size_mb in sorted_file_list.items():
#                     # transfer just one file and iterate
#                     # split filename and path
#                     [local_dir, filename] = os.path.split(file_path)
#                     self.log.info(f'transfering {filename}')
#                     # specify external directory
#                     # need to change directories to str because they are Path objects
#                     external_dir = local_dir.replace(str(local_directory), str(external_directory))
#                     # robocopy flags
#                     # /j unbuffered copy for transfer speed stability
#                     # /mov deletes local files after transfer
#                     # /if move only the specified filename
#                     # /njh no job header in log file
#                     # /njs no job summary in log file
#                     cmd_with_args = f'{self._protocol} {local_dir} {external_dir} \
#                         /j /if {filename} /njh /njs /log:{log_path}'
#                     # stdout to PIPE will cause malloc errors on exist
#                     # no stdout will print subprocess to python
#                     # stdout to DEVNULL will supresss subprocess output
#                     subprocess = Popen(cmd_with_args, stdout=DEVNULL)
#                     # wait one second for process to start before monitoring log file for progress
#                     time.sleep(1.0)
#                     # lets monitor the progress of the individual file if size > 1 GB
#                     if file_size_mb > 1024:
#                         self.log.info(f'{filename} is > 1 GB')
#                         # wait for subprocess to start otherwise log file won't exist yet
#                         time.sleep(1.0)
#                         file_progress = 0
#                         previous_progress = 0
#                         stuck_time_s = 0
#                         while file_progress < 100:
#                             start_time_s = time.time()
#                             # open log file
#                             f = open(log_path, 'r')
#                             # read the last line
#                             line = f.readlines()[-1]
#                             # close the log file
#                             f.close()
#                             # try to find if there is a % in the last line
#                             try:
#                                 # convert the string to a float
#                                 file_progress = float(line.replace('%',''))
#                             # line did not contain %
#                             except:
#                                 file_progress = 0
#                             # sum to transferred amount to track progress
#                             self._progress = (total_transferred_mb +
#                                             file_size_mb * file_progress / 100) / total_size_mb * 100
#                             end_time_s = time.time()
#                             # keep track of how long stuck at same progress
#                             if self.progress == previous_progress:
#                                 stuck_time_s += (end_time_s - start_time_s)
#                                 # break if exceeds timeout
#                                 if stuck_time_s >= self._timeout_s:
#                                     self.log.info('timeout exceeded, restarting file transfer.')
#                                     break
#                             else:
#                                 stuck_time_s  = 0
#                             previous_progress = self.progress
#                             self.log.info(f'file transfer is {self.progress:.2f} % complete.')
#                             # pause for 10 sec
#                             time.sleep(10.0)
#                     else:
#                         subprocess.wait()
#                         self._progress = (total_transferred_mb + file_size_mb) / total_size_mb * 100
#                         self.log.info(f'file transfer is {self.progress:.2f} % complete.')
#                     self.log.info(f'{filename} transfer complete')
#                     # wait for process to finish before cleaning log file
#                     time.sleep(10.0)
#                     # clean up and remove the temporary log file
#                     # os.remove(log_path)
#                     # update the total transfered amount
#                     total_transferred_mb += file_size_mb
#                 # clean up the local subdirs and files
#                 for file in delete_list:
#                     # f is a relative path, convert to absolute
#                     local_file_path = os.path.join(local_directory.absolute(), file)
#                     external_file_path = os.path.join(external_directory.absolute(), file)
#                     # .zarr is directory but os.path.isdir will return False
#                     if os.path.isdir(local_file_path) or ".zarr" in local_dir:
#                         # TODO how to hash check zarr -> directory instead of file?
#                         shutil.rmtree(local_file_path)
#                     elif os.path.isfile(local_file_path):
#                         # verify transfer with hashlib
#                         if self._verify_transfer:
#                             # put in try except in case no external file found
#                             try:
#                                 # if hash is verified delete file
#                                 if self._verify_file(local_file_path, external_file_path):
#                                     # remove local file
#                                     self.log.info(f'deleting {local_file_path}')
#                                     os.remove(local_file_path)
#                                 # if has fails, external file is corrupt
#                                 else:
#                                     # remove external file, try again
#                                     self.log.info(f'hashes did not match, deleting {external_file_path}')
#                                     os.remove(external_file_path)
#                                     pass
#                             except:
#                                 self.log.warning(f'no external file exists at {external_file_path}')
#                         else:
#                             # remove local file
#                             self.log.info(f'deleting {local_file_path}')
#                             os.remove(local_file_path)
#                     else:
#                         raise ValueError(f'{local_file_path} is not a file or directory.')
#                 end_time = time.time()
#                 total_time = end_time - start_time
#                 self.log.info(f'transfer complete, total time: {total_time} sec')
#                 subprocess.kill()
#                 retry_num += 1

import os
import shutil
import time
from pathlib import Path
from voxel.descriptors.deliminated_property import DeliminatedProperty
from subprocess import DEVNULL, Popen
import logging
from voxel.file_transfers.base import BaseFileTransfer
import os
import shutil
import time
from pathlib import Path
from voxel.descriptors.deliminated_property import DeliminatedProperty
from subprocess import DEVNULL, Popen
import logging
from voxel.file_transfers.base import BaseFileTransfer


class RobocopyFileTransfer(BaseFileTransfer):
    """
    Voxel driver for Robocopy file transfer process.
    """

    def __init__(self, external_path: str, local_path: str):
        super().__init__(external_path, local_path)
        # Initialize logger
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._protocol = "robocopy"

    def _run(self):
        start_time = time.time()
        local_directory = Path(self._local_path, self._acquisition_name)
        external_directory = Path(self._external_path, self._acquisition_name)
        log_path = Path(local_directory, f"{self._filename}.log")

        # Ensure directories exist
        local_directory.mkdir(parents=True, exist_ok=True)
        external_directory.mkdir(parents=True, exist_ok=True)

        transfer_complete = False
        retry_num = 0

        complete_list = []
        while not transfer_complete and retry_num <= self._max_retry - 1:
            # Generate file lists
            delete_list = []
            for name in os.listdir(local_directory):
                if self.filename in name:
                    delete_list.append(name)

            file_list = {}
            for path, subdirs, files in os.walk(local_directory):
                for name in files:
                    if self.filename in name and name != log_path.name:
                        file_path = os.path.join(path, name)
                        file_list[file_path] = os.path.getsize(file_path) / 1024 ** 2

            print('Complete list', complete_list)
            print('File list keys',file_list.keys() )
            if set(complete_list) == set(file_list.keys()):
                break
            total_size_mb = sum(file_list.values())
            sorted_file_list = dict(sorted(file_list.items(), key=lambda item: item[1]))
            total_transferred_mb = 0


            if not sorted_file_list:
                transfer_complete = True
            else:
                num_files = len(sorted_file_list)
                self.log.info(f'Attempt {retry_num + 1}/{self._max_retry}, transferring {num_files} files.')
                for file_path, file_size_mb in sorted_file_list.items():
                    local_dir, filename = os.path.split(file_path)
                    self.log.info(f'Transferring {filename}')
                    external_dir = local_dir.replace(str(local_directory), str(external_directory))

                    # Ensure external directory exists
                    Path(external_dir).mkdir(parents=True, exist_ok=True)

                    # Build command as a list
                    cmd_with_args = [
                        self._protocol,
                        str(local_dir),
                        str(external_dir),
                        '/j',
                        '/if', filename,
                        '/njh',
                        '/njs',
                        f'/log:{str(log_path)}'
                    ]

                    # Start the subprocess
                    self.log.info(f'Executing command: {" ".join(cmd_with_args)}')
                    subprocess = Popen(cmd_with_args, stdout=DEVNULL)

                    # Wait for the log file to be created
                    wait_time_s = 0
                    while not os.path.exists(log_path):
                        time.sleep(1.0)
                        wait_time_s += 1.0
                        if wait_time_s >= self._timeout_s:
                            self.log.error('Timeout waiting for log file, restarting file transfer.')
                            subprocess.kill()
                            break

                    if file_size_mb > 1024 and os.path.exists(log_path):
                        # Monitor progress for large files
                        self.log.info(f'{filename} is > 1 GB')
                        file_progress = 0
                        previous_progress = 0
                        stuck_time_s = 0

                        while file_progress < 100:
                            start_time_s = time.time()
                            try:
                                with open(log_path, 'r') as f:
                                    lines = f.readlines()
                                    # Reverse iterate to find the last progress line
                                    progress_found = False
                                    for line in reversed(lines):
                                        line = line.strip()
                                        if line.endswith('%'):
                                            progress_str = line.strip('%').strip()
                                            file_progress = float(progress_str)
                                            progress_found = True
                                            break
                                    # if not progress_found:
                                    #     # Check if the last line indicates completion
                                    #     if lines and lines[-1].strip().startswith('1'):
                                    #         self.log.info('Transfer appears complete based on log file.')
                                    #         file_progress = 100
                                    #         break
                                    #     else:
                                    #         file_progress = previous_progress
                            except Exception as e:
                                self.log.warning(f'Error reading log file: {e}')
                                time.sleep(1.0)
                                continue

                            print(file_path, file_progress)

                            # Update progress
                            self._progress = ((total_transferred_mb +
                                               file_size_mb * file_progress / 100) / total_size_mb) * 100

                            end_time_s = time.time()
                            if self.progress == previous_progress:
                                stuck_time_s += (end_time_s - start_time_s)
                                if stuck_time_s >= self._timeout_s:
                                    self.log.error('Timeout exceeded, restarting file transfer.')
                                    subprocess.kill()
                                    break
                            else:
                                stuck_time_s = 0

                            previous_progress = self.progress
                            self.log.info(f'File transfer is {self.progress:.2f}% complete.')
                            time.sleep(10.0)
                    else:
                        subprocess.wait()
                        self._progress = ((total_transferred_mb + file_size_mb) / total_size_mb) * 100
                        self.log.info(f'File transfer is {self.progress:.2f}% complete.')

                    self.log.info(f'{filename} transfer complete')
                    total_transferred_mb += file_size_mb
                    complete_list.append(file_path)
                # clean up the local subdirs and files
                for file in delete_list:
                    # f is a relative path, convert to absolute
                    local_file_path = os.path.join(local_directory.absolute(), file)
                    external_file_path = os.path.join(external_directory.absolute(), file)
                    # .zarr is directory but os.path.isdir will return False
                    if os.path.isdir(local_file_path) or ".zarr" in local_dir:
                        # TODO how to hash check zarr -> directory instead of file?
                        shutil.rmtree(local_file_path)
                    elif os.path.isfile(local_file_path):
                        # verify transfer with hashlib
                        if self._verify_transfer:
                            # put in try except in case no external file found
                            try:
                                # if hash is verified delete file
                                if self._verify_file(local_file_path, external_file_path):
                                    # remove local file
                                    self.log.info(f'deleting {local_file_path}')
                                    os.remove(local_file_path)
                                # if has fails, external file is corrupt
                                else:
                                    # remove external file, try again
                                    self.log.info(f'hashes did not match, deleting {external_file_path}')
                                    os.remove(external_file_path)
                                    pass
                            except:
                                self.log.warning(f'no external file exists at {external_file_path}')
                        else:
                            # remove local file
                            self.log.info(f'deleting {local_file_path}')
                            os.remove(local_file_path)
                    else:
                        raise ValueError(f'{local_file_path} is not a file or directory.')
                end_time = time.time()
                total_time = end_time - start_time
                self.log.info(f'transfer complete, total time: {total_time} sec')
                subprocess.kill()
                retry_num += 1