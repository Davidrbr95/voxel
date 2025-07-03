import logging
import multiprocessing
import os
import sys
from ctypes import c_wchar
from math import ceil
from multiprocessing import Array, Process
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from time import perf_counter, sleep
from typing import List

import numpy as np
import acquire_zarr as aqz
from xml.etree import ElementTree as ET
from PyImarisWriter import PyImarisWriter as pw


from voxel.writers.base import BaseWriter

CHUNK_COUNT_PX = 64
DIVISIBLE_FRAME_COUNT_PX = 64

COMPRESSIONS = {
    "lz4": aqz.CompressionCodec.BLOSC_LZ4,
    "zstd": aqz.CompressionCodec.BLOSC_ZSTD,
    "none": aqz.CompressionCodec.NONE,
}

DATA_TYPES = {"unit8": aqz.DataType.UINT16, "uint16": aqz.DataType.UINT16}

VERSIONS = {"v2": aqz.ZarrVersion.V2, "v3": aqz.ZarrVersion.V3}

SHUFFLES = {True: 1, False: 0}


class ZarrWriter(BaseWriter):
    """
    Voxel driver for the Zarr writer.

    Writer will save data to the following location

    path\\acquisition_name\\filename.zarr
    """

    def __init__(self, path: str) -> None:
        """
        Module for handling Zarr data writing processes.

        :param path: The path for the data writer.
        :type path: str
        """
        super().__init__(path)
        self._compression = aqz.CompressionCodec.NONE  # initialize as no compression
        self._chunk_size_x_px = None
        self._chunk_size_y_px = None
        self._chunk_size_z_px = None
        self._version = None
        self._multiscale = None
        self._shuffle = 0
        self._clevel = 1
        self.nilluminations=1
        self.nchannels=1
        self.ntiles=1
        self.nangles=1
        self.ntimes = 1
        self.nsetups = self.nilluminations * self.nchannels * self.ntiles * self.nangles
        self.attribute_counts = {'illumination': self.nilluminations, 'channel': self.nchannels,
                                 'angle': self.nangles, 'tile': self.ntiles}
        self.stack_shapes = {}
        self.affine_matrices = {}
        self.affine_names = {}
        self.calibrations = {}
        self.voxel_size_xyz = {}
        self.voxel_units = {}
        self.exposure_time = {}
        self.exposure_units = {}
        self.attribute_labels = {}
        self.setup_id_present = [[True] * self.nsetups]

    @property
    def chunk_size_x_px(self) -> int:
        """Get the chunk size x of the writer.

        :return: Chunk size in x in pixels
        :rtype: int
        """
        return self._chunk_size_x_px

    @chunk_size_x_px.setter
    def chunk_size_x_px(self, chunk_size_x_px: int) -> None:
        """Set the chunk size in x of the writer.

        :param value: Chunk size in x in pixels
        :type value: int
        """
        self.log.info(f"setting chunk size in x to: {chunk_size_x_px} [px]")
        self._chunk_size_x_px = chunk_size_x_px

    @property
    def chunk_size_y_px(self) -> int:
        """Get the chunk size y of the writer.

        :return: Chunk size in y in pixels
        :rtype: int
        """
        return self._chunk_size_y_px

    @chunk_size_y_px.setter
    def chunk_size_y_px(self, chunk_size_y_px: int) -> None:
        """Set the chunk size in y of the writer.

        :param value: Chunk size in y in pixels
        :type value: int
        """
        self.log.info(f"setting chunk size in y to: {chunk_size_y_px} [px]")
        self._chunk_size_y_px = chunk_size_y_px

    @property
    def chunk_size_z_px(self) -> int:
        """Get the chunk size z of the writer.

        :return: Chunk size in z in pixels
        :rtype: int
        """
        return self._chunk_size_z_px

    @chunk_size_z_px.setter
    def chunk_size_z_px(self, chunk_size_z_px: int) -> None:
        """Set the chunk size in z of the writer.

        :param value: Chunk size in z in pixels
        :type value: int
        """
        self.log.info(f"setting chunk size in z to: {chunk_size_z_px} [px]")
        self._chunk_size_z_px = chunk_size_z_px

    @property
    def frame_count_px(self) -> int:
        """Get the number of frames in the writer.

        :return: Frame number in pixels
        :rtype: int
        """
        return self._frame_count_px

    @frame_count_px.setter
    def frame_count_px(self, frame_count_px: int) -> None:
        """Set the number of frames in the writer.

        :param value: Frame number in pixels
        :type value: int
        """
        self.log.info(f"setting frame count to: {frame_count_px} [px]")
        if frame_count_px % DIVISIBLE_FRAME_COUNT_PX != 0:
            frame_count_px = ceil(frame_count_px / DIVISIBLE_FRAME_COUNT_PX) * DIVISIBLE_FRAME_COUNT_PX
            self.log.info(f"adjusting frame count to: {frame_count_px} [px]")
        self._frame_count_px = frame_count_px

    @property
    def chunk_count_px(self) -> int:
        """Get the chunk count in pixels

        :return: Chunk count in pixels
        :rtype: int
        """
        return CHUNK_COUNT_PX


    @property
    def theta_deg(self):
        """Get theta value of the writer.

        :return: Theta value in deg
        :rtype: float
        """

        return self._theta_deg

    @theta_deg.setter
    def theta_deg(self, theta_deg: float):
        """Set the theta value of the writer.

        :param value: Theta value in deg
        :type value: float
        """

        self.log.info(f"setting theta to: {theta_deg} [deg]")
        self._theta_deg = theta_deg

    @property
    def multiscale(self) -> bool:
        """Get the multiscale setting of the zarr writer.

        :return: Multiscale setting
        :rtype: bool
        """
        return self._multiscale

    @multiscale.setter
    def multiscale(self, multiscale: bool) -> None:
        """Set the multiscale setting of the zarr writer.

        :param value: Multiscale setting
        :type value: bool
        """
        if type(multiscale) is not bool:
            raise ValueError("multiscale setting must be true or false")
        self.log.info(f"setting multiscale setting to: {multiscale}")
        self._multiscale = multiscale

    @property
    def clevel(self) -> str:
        """Get the compression level of the zarr writer.

        :return: Compression level
        :rtype: int
        """
        return self._clevel

    @clevel.setter
    def clevel(self, clevel: int) -> None:
        """Set the compression level.

        :param clevel: Compression level
        :type shuffle: int
        """
        self._clevel = clevel

    @property
    def shuffle(self) -> str:
        """Get the shuffle mode of the zarr writer.

        :return: Shuffle mode
        :rtype: str
        """
        return self._shuffle

    @shuffle.setter
    def shuffle(self, shuffle: str) -> None:
        """Set the compression shuffle mode.

        :param shuffle: Shuffle mode
        * **on**
        * **off**
        :type shuffle: str
        """
        valid = list(SHUFFLES.keys())
        if shuffle not in valid:
            raise ValueError("shuffle must be one of %r." % valid)
        self.log.info(f"setting zarr shuffle to: {shuffle}")
        self._shuffle = SHUFFLES[shuffle]

    def _determine_setup_id(self, illumination=0, channel=0, tile=0, angle=0):
        """Takes the view attributes (illumination, channel, tile, angle) and converts them into unique setup_id.
        Parameters:
        -----------
            illumination: int
            channel: int
            tile: int
            angle: int

        Returns:
        --------
            setup_id: int, >=0 (first setup)
            """
        if self.nsetups is not None:
            setup_id_matrix = np.arange(self.nsetups)
            setup_id_matrix = setup_id_matrix.reshape((self.nilluminations, self.nchannels, self.ntiles, self.nangles))
            setup_id = setup_id_matrix[illumination, channel, tile, angle]
        else:
            setup_id = None
        return setup_id
    
    @property
    def version(self) -> str:
        """Get the version of the zarr writer.

        :return: Zarr version
        :rtype: str
        """
        return self._version

    @version.setter
    def version(self, version: str) -> None:
        """Set the version of the zarr writer.

        :param value: Zarr version
        * **v2**
        * **v3**
        :type value: str
        """
        valid = list(VERSIONS.keys())
        if version not in valid:
            raise ValueError("version must be one of %r." % valid)
        self.log.info(f"setting zarr version to: {version}")
        self._version = version

    @property
    def compression(self) -> str:
        """Get the compression codec of the writer.

        :return: Compression codec
        :rtype: str
        """
        return next(key for key, value in COMPRESSIONS.items() if value == self._compression)

    @compression.setter
    def compression(self, compression: str) -> None:
        """Set the compression codec of the writer.

        :param value: Compression codec
        * **lz4**
        * **zstd**
        * **none**
        :type value: str
        """
        valid = list(COMPRESSIONS.keys())
        if compression not in valid:
            raise ValueError("compression type must be one of %r." % valid)
        self.log.info(f"setting compression mode to: {compression}")
        self._compression = COMPRESSIONS[compression]

    @property
    def filename(self) -> str:
        """
        The base filename of file writer.

        :return: The base filename
        :rtype: str
        """
        return self._filename

    @filename.setter
    def filename(self, filename: str) -> None:
        """
        The base filename of file writer.

        :param value: The base filename
        :type value: str
        """
        self._filename = filename if filename.endswith(".zarr") else f"{filename}.zarr"
        self.log.info(f"setting filename to: {filename}")

    def delete_files(self) -> None:
        """Delete all files generated by the writer."""
        filepath = Path(self._path, self._acquisition_name, self._filename).absolute()
        os.remove(filepath)

    def prepare(self) -> None:
        """Prepare the writer."""
        self.tile_list = list()
        self.channel_list = list()
        self.dataset_dict = dict()
        self.voxel_size_dict = dict()
        self.affine_deskew_dict = dict()
        self.affine_scale_dict = dict()
        self.affine_shift_dict = dict()

        self.log.info(f"{self._filename}: intializing writer.")
        # Specs for reconstructing the shared memory object.
        self._shm_name = Array(c_wchar, 32)  # hidden and exposed via property.
        # opinioated decision on chunking dimension order
        chunk_dim_order = ("z", "y", "x")
        # This is almost always going to be: (chunk_size, rows, columns).
        chunk_shape_map = {
            "x": self._column_count_px,
            "y": self._row_count_px,
            "z": CHUNK_COUNT_PX,
        }
        shm_shape = [chunk_shape_map[x] for x in chunk_dim_order]
        shm_nbytes = int(np.prod(shm_shape, dtype=np.int64) * np.dtype(self._data_type).itemsize)
        tile_position = (self._x_position_mm, self._y_position_mm, self._z_position_mm)
        if tile_position not in self.tile_list:
            self.tile_list.append(tile_position)
        self.current_tile_num = self.tile_list.index(tile_position)
        if self._channel not in self.channel_list:
            self.channel_list.append(self._channel)
        self.current_channel_num = self.channel_list.index(self._channel)
        
                # Add dimensions to dictionary with key (tile#, channel#)
        tile_dimensions = (
            # self._frame_count_px_px,
            self._row_count_px,
            self._column_count_px,
            self._frame_count_px_px,
        )

        self.dataset_dict[(self.current_tile_num, self.current_channel_num)] = (
            tile_dimensions
        )

        # Add voxel size to dictionary with key (tile#, channel#)
        # effective voxel size in x direction
        size_x = self._x_voxel_size_um

        # effective voxel size in y direction
        ## notice modifications
        size_y = self._y_voxel_size_um * np.cos(self.theta_deg * np.pi / 180.0)

        # effective voxel size in z direction (scan)
        size_z = self._z_voxel_size_um

        voxel_sizes = (size_x, size_y, size_z)
        self.voxel_size_dict[(self.current_tile_num, self.current_channel_num)] = (
            voxel_sizes
        )
        self.voxel_size_xyz[0] = voxel_sizes
        self.voxel_units[0] = "um"
        self.exposure_time[0] = 0
        self.exposure_units[0] = "s"
        self.calibrations[0]  = (1, 1, 1)

        print('size_x', size_x, 'size_y', size_y, 'size_z', size_z)
        print('_x_position_mm', self._x_position_mm, '_y_position_mm', self._y_position_mm, '_z_position_mm', self._z_position_mm)

        # Create affine matrix dictionary with key (tile#, channel#)
        # normalized scaling in x
        scale_x = size_x / size_y
        # normalized scaling in y
        scale_y = size_y / size_y
        # normalized scaling in z (scan)
        scale_z = size_z / size_y
        # shearing based on theta and y/z pixel sizes
        shear = np.tan(self.theta_deg * np.pi / 180.0) * size_y / size_z
        # shift tile in x, unit pixels
        shift_x = scale_x * (self._x_position_mm * 1000 / size_z)
        # shift tile in y, unit pixels
        shift_y = 1*scale_y * (self._y_position_mm * 1000 / size_x)
        # shift tile in z, unit pixels
        shift_z = -1*scale_z * (self._z_position_mm * 1000 / size_y)

        affine_deskew = np.array(
            ([1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, shear, 1.0, 0.0])
        )

        affine_scale = np.array(
            (
                [scale_x, 0.0, 0.0, 0.0],
                [0.0, scale_y, 0.0, 0.0],
                [0.0, 0.0, scale_z, 0.0],
            )
        )

        affine_shift = np.array(
            (
                [1.0, 0.0, 0.0, shift_y],
                [0.0, 1.0, 0.0, shift_z],
                [0.0, 0.0, 1.0, shift_x],
            )
        )

        self.affine_deskew_dict[0] = (
            affine_deskew
        )
        self.affine_scale_dict[0] = (
            affine_scale
        )
        self.affine_shift_dict[0] = (
            affine_shift
        )
        # voxel size metadata to create the converter
        image_size_z = int(ceil(self._frame_count_px / CHUNK_COUNT_PX) * CHUNK_COUNT_PX)
        image_size = pw.ImageSize(
            x=self._column_count_px, y=self._row_count_px, z=image_size_z, c=1, t=1
        )
        self.stack_shapes[0] = (image_size_z, self._row_count_px, self._column_count_px)
        block_size = pw.ImageSize(
            x=self._column_count_px, y=self._row_count_px, z=CHUNK_COUNT_PX, c=1, t=1
        )
        # create run process
        self._process = Process(
            target=self._run,
            args=(
                shm_shape,
                shm_nbytes,
                self._progress,
                self._log_queue,
            ),
        )

    def write_xml(self, camera_name="default",  microscope_name="default",
                        microscope_version="0.0", user_name="user"):
            """
            Write XML header file for the HDF5 file.

            Parameters:
            -----------
                camera_name: str, optional
                    Name of the camera (same for all setups at the moment)
                microscope_name: str, optional
                microscope_version: str, optional
                user_name: str, optional
            """
            # filepath = Path(self._path, self._acquisition_name, self._filename).absolute()
            self.filename_xml = str(Path(self._path, self._acquisition_name, self._filename).absolute())
            print('xml name', self.filename_xml)
            self.filename_xml = self.filename_xml[:-5]+'.xml'
            print('xml name 2', self.filename_xml)
            filename = self.filename[:-5]+'.zarr'
            try:
                # check if tile position already exists
                self.current_tile_num = self.tile_list.index(
                    (
                        self._x_position_mm,
                        self._y_position_mm,
                        self._z_position_mm,
                    )
                )
            except self.current_tile_num.DoesNotExist:
                # if does not exist, increment tile number by 1
                self.current_tile_num = len(self.tile_list) + 1
            
            root = ET.Element('SpimData')
            root.set('version', '0.2')
            bp = ET.SubElement(root, 'BasePath')
            bp.set('type', 'relative')
            bp.text = '.'

            # new XML data, added by @nvladimus
            # generator = ET.SubElement(root, 'generatedBy')
            # library = ET.SubElement(generator, 'library')
            # library.set('version', self.__version__)
            # library.text = "npy2bdv"
            # microscope = ET.SubElement(generator, 'microscope')
            # ET.SubElement(microscope, 'name').text = microscope_name
            # ET.SubElement(microscope, 'version').text = microscope_version
            # ET.SubElement(microscope, 'user').text = user_name
            # end of new XML data

            seqdesc = ET.SubElement(root, 'SequenceDescription')
            imgload = ET.SubElement(seqdesc, 'ImageLoader')
            imgload.set('format', 'bdv.multimg.zarr')
            el = ET.SubElement(imgload, 'zarr')
            el.set('type', 'relative')
            el.text = os.path.basename(filename)
            # write ViewSetups
            viewsets = ET.SubElement(seqdesc, 'ViewSetups')
            for iillumination in range(self.nilluminations):
                for ichannel in range(self.nchannels):
                    for itile in range(self.ntiles):
                        for iangle in range(self.nangles):
                            isetup = self._determine_setup_id(iillumination, ichannel, itile, iangle)
                            if any([self.setup_id_present[t][isetup] for t in range(len(self.setup_id_present))]):
                                vs = ET.SubElement(viewsets, 'ViewSetup')
                                ET.SubElement(vs, 'id').text = str(isetup)
                                ET.SubElement(vs, 'name').text = str(os.path.basename(filename))
                                nz, ny, nx = tuple(self.stack_shapes[isetup])
                                ET.SubElement(vs, 'size').text = '{} {} {}'.format(nx, ny, nz)
                                vox = ET.SubElement(vs, 'voxelSize')
                                ET.SubElement(vox, 'unit').text = self.voxel_units[isetup]
                                dx, dy, dz = self.voxel_size_xyz[isetup]
                                ET.SubElement(vox, 'size').text = '{} {} {}'.format(dx, dy, dz)
                                # new XML data, added by @nvladimus
                                cam = ET.SubElement(vs, 'camera')
                                ET.SubElement(cam, 'name').text = camera_name
                                ET.SubElement(cam, 'exposureTime').text = '{}'.format(self.exposure_time[isetup])
                                ET.SubElement(cam, 'exposureUnits').text = self.exposure_units[isetup]
                                # end of new XML data
                                a = ET.SubElement(vs, 'attributes')
                                ET.SubElement(a, 'illumination').text = str(iillumination)
                                ET.SubElement(a, 'channel').text = str(ichannel)
                                ET.SubElement(a, 'tile').text = str(itile)
                                ET.SubElement(a, 'angle').text = str(iangle)

            # write Attributes
            for attribute in self.attribute_counts.keys():
                attrs = ET.SubElement(viewsets, 'Attributes')
                attrs.set('name', attribute)
                for i_attr in range(self.attribute_counts[attribute]):
                    att = ET.SubElement(attrs, attribute.capitalize())
                    ET.SubElement(att, 'id').text = str(i_attr)
                    if attribute in self.attribute_labels.keys() and i_attr < len(self.attribute_labels[attribute]):
                        name = str(self.attribute_labels[attribute][i_attr])
                    else:
                        name = str(i_attr)
                    ET.SubElement(att, 'name').text = name

            # Time points
            tpoints = ET.SubElement(seqdesc, 'Timepoints')
            tpoints.set('type', 'range')
            ET.SubElement(tpoints, 'first').text = str(0)
            ET.SubElement(tpoints, 'last').text = str(self.ntimes - 1)

            # missing views
            if any(True in l for l in self.setup_id_present):
                miss_views = ET.SubElement(seqdesc, 'MissingViews')
                for t in range(len(self.setup_id_present)):
                    for i in range(len(self.setup_id_present[t])):
                        if not self.setup_id_present[t][i]:
                            miss_view = ET.SubElement(miss_views, 'MissingView')
                            miss_view.set('timepoint', str(t))
                            miss_view.set('setup', str(i))

            # Transformations of coordinate system
            vregs = ET.SubElement(root, 'ViewRegistrations')
            print('Before registrations', self.ntimes, self.nsetups)
            # print(self.setup_id_present[itime][isetup])
            for itime in range(self.ntimes):
                for isetup in range(self.nsetups):
                    print(self.setup_id_present)
                    print(self.setup_id_present[itime][isetup])
                    if self.setup_id_present[itime][isetup]:
                        vreg = ET.SubElement(vregs, 'ViewRegistration')
                        vreg.set('timepoint', str(itime))
                        vreg.set('setup', str(isetup))
                        
                        # write arbitrary affine transformation, specific for each view
                        if isetup in self.affine_matrices.keys():
                            vt = ET.SubElement(vreg, 'ViewTransform')
                            vt.set('type', 'affine')
                            ET.SubElement(vt, 'Name').text = self.affine_names[isetup]
                            mx_string = np.array2string(self.affine_matrices[isetup].flatten(), formatter={'float':lambda x: "%.6f" % x})
                            ET.SubElement(vt, 'affine').text = mx_string[1:-1].strip()
                        
                        # write arbitrary affine transformation, specific for each view
                        if isetup in self.affine_deskew_dict.keys():
                            vt = ET.SubElement(vreg, 'ViewTransform')
                            vt.set('type', 'affine')
                            ET.SubElement(vt, 'Name').text = 'deskew'
                            mx_string = np.array2string(self.affine_deskew_dict[isetup].flatten(), formatter={'float':lambda x: "%.6f" % x})
                            ET.SubElement(vt, 'affine').text = mx_string[1:-1].strip()
                                                # write arbitrary affine transformation, specific for each view
                        
                        if isetup in self.affine_scale_dict.keys():
                            vt = ET.SubElement(vreg, 'ViewTransform')
                            vt.set('type', 'affine')
                            ET.SubElement(vt, 'Name').text = 'scale'
                            mx_string = np.array2string(self.affine_scale_dict[isetup].flatten(), formatter={'float':lambda x: "%.6f" % x})
                            ET.SubElement(vt, 'affine').text = mx_string[1:-1].strip()

                        if isetup in self.affine_shift_dict.keys():
                            vt = ET.SubElement(vreg, 'ViewTransform')
                            vt.set('type', 'affine')
                            ET.SubElement(vt, 'Name').text = 'shift'
                            mx_string = np.array2string(self.affine_shift_dict[isetup].flatten(), formatter={'float':lambda x: "%.6f" % x})
                            ET.SubElement(vt, 'affine').text = mx_string[1:-1].strip()

                        # write registration transformation (calibration)
                        vt = ET.SubElement(vreg, 'ViewTransform')
                        vt.set('type', 'affine')
                        ET.SubElement(vt, 'Name').text = 'calibration'
                        calx, caly, calz = self.calibrations[isetup]
                        ET.SubElement(vt, 'affine').text = \
                            '{} 0.0 0.0 0.0 0.0 {} 0.0 0.0 0.0 0.0 {} 0.0'.format(calx, caly, calz)

            self._xml_indent(root)
            tree = ET.ElementTree(root)
            print('End of xml writing function', self.filename_xml)
            tree.write(self.filename_xml, xml_declaration=True, encoding='utf-8', method="xml")
        
    def _xml_indent(self, elem, level=0):
        """Pretty printing function"""
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for elem in elem:
                self._xml_indent(elem, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i
    def _run(
        self,
        shm_shape: List[int],
        shm_nbytes: int,
        shared_progress: multiprocessing.Value,
        shared_log_queue: multiprocessing.Queue,
    ) -> None:
        """
        Main run function of the Zarr writer.

        :param shm_shape: Shared memory address shape
        :type shm_shape: list
        :param shm_nbytes: Shared memory address bytes
        :type shm_nbytes: int
        :param shared_progress: Shared progress value of the writer
        :type shared_progress: multiprocessing.Value
        :param shared_log_queue: Shared queue for passing log statements
        :type shared_log_queue: multiprocessing.Queue
        """
        # internal logger for process
        logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
        datefmt = "%Y-%m-%d,%H:%M:%S"
        log_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
        log_handler = logging.StreamHandler(sys.stdout)
        log_handler.setFormatter(log_formatter)
        logger.addHandler(log_handler)
        filepath = Path(self._path, self._acquisition_name, self._filename).absolute()

        print(self._compression, aqz.Compressor.BLOSC1, self._clevel, self._shuffle)
        compression_settings = aqz.CompressionSettings(
            codec=self._compression,  # compression codec
            compressor=aqz.Compressor.BLOSC1,  # compressor
            clevel=self._clevel,  # compression level
            shuffle=self._shuffle,  # shuffle filter
        )

        settings = aqz.StreamSettings(
            store_path=str(filepath),
            data_type=DATA_TYPES[self._data_type],
            version=VERSIONS[self._version],
            multiscale=self._multiscale,
            # compression=compression_settings,
        )

        settings.dimensions.extend(
            [
                aqz.Dimension(
                    name="z",
                    type=aqz.DimensionType.SPACE,
                    array_size_px=self.frame_count_px,
                    chunk_size_px=self._chunk_size_z_px,
                    shard_size_chunks=1,  # hardcode shard to 1 in z
                ),
                aqz.Dimension(
                    name="y",
                    type=aqz.DimensionType.SPACE,
                    array_size_px=self.row_count_px,
                    chunk_size_px=self._chunk_size_y_px,
                    shard_size_chunks=ceil(self.row_count_px / self._chunk_size_y_px),
                ),
                aqz.Dimension(
                    name="x",
                    type=aqz.DimensionType.SPACE,
                    array_size_px=self.column_count_px,
                    chunk_size_px=self._chunk_size_x_px,
                    shard_size_chunks=ceil(self.column_count_px / self._chunk_size_x_px),
                ),
            ]
        )

        stream = aqz.ZarrStream(settings)

        chunk_total = ceil(self._frame_count_px / CHUNK_COUNT_PX)
        for chunk_num in range(chunk_total):
            # Wait for new data.
            while self.done_reading.is_set():
                sleep(0.001)
            # Attach a reference to the data from shared memory.
            shm = SharedMemory(self.shm_name, create=False, size=shm_nbytes)
            frames = np.ndarray(shm_shape, self._data_type, buffer=shm.buf)
            shared_log_queue.put(
                f"{self._filename}: writing chunk " f"{chunk_num + 1}/{chunk_total} of size {frames.shape}."
            )
            start_time = perf_counter()
            # Put the frames into the stream
            stream.append(frames)
            frames = None
            shared_log_queue.put(f"{self._filename}: writing chunk took " f"{perf_counter() - start_time:.2f} [s]")
            shm.close()
            self.done_reading.set()
            # update shared value progress range 0-1
            shared_progress.value = (chunk_num + 1) / chunk_total

            shared_log_queue.put(f"{self._filename}: {self._progress.value * 100:.2f} [%] complete.")

        # check and empty queue to avoid code hanging in process
        if not shared_log_queue.empty:
            shared_log_queue.get_nowait()