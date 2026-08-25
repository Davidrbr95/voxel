import logging
import multiprocessing
import os
import sys
import tempfile
import json
from ctypes import c_wchar
from math import ceil
from multiprocessing import Array, Process
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from time import perf_counter, sleep
from typing import List, Optional

import numpy as np
import acquire_zarr as aqz
from xml.etree import ElementTree as ET
from PyImarisWriter import PyImarisWriter as pw


from voxel.writers.base import BaseWriter

CHUNK_COUNT_PX = 32
DIVISIBLE_FRAME_COUNT_PX = 32

COMPRESSIONS = {
    "lz4": aqz.CompressionCodec.BLOSC_LZ4,
    "zstd": aqz.CompressionCodec.BLOSC_ZSTD,
    "none": aqz.CompressionCodec.NONE,
}

DATA_TYPES = {"uint8": aqz.DataType.UINT8, "unit8": aqz.DataType.UINT8, "uint16": aqz.DataType.UINT16}

VERSIONS = {"v3": aqz.ZarrVersion.V3}
if hasattr(aqz.ZarrVersion, "V2"):
    VERSIONS["v2"] = aqz.ZarrVersion.V2

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
        self._shard_size_x_chunks = None
        self._shard_size_y_chunks = None
        self._shard_size_z_chunks = None
        self._version = None
        self._multiscale = None
        self._shuffle = 0
        self._clevel = 1
        self._b3d_enabled = False
        self._b3d_mode = 2
        self._b3d_quant_step = 1.0
        self._b3d_conversion = 2.127659574
        self._b3d_background = 100.731672
        self._b3d_read_noise = 1.480570
        self._b3d_tile_size = 24
        self._b3d_zstd_level = 3
        self._b3d_backend = "auto"
        self._b3d_cuda_batch_layers = 16
        # Camera stacks normally arrive as z,y,x.  OTLS acquisition is different:
        # frames advance along physical x and each frame is a z,y plane, so its
        # input order is x,z,y.  Files are always emitted in canonical OME z,y,x.
        self._input_axis_order = "zyx"
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
    def shard_size_x_chunks(self) -> Optional[int]:
        return self._shard_size_x_chunks

    @shard_size_x_chunks.setter
    def shard_size_x_chunks(self, value: Optional[int]) -> None:
        self._shard_size_x_chunks = None if value is None else max(1, int(value))

    @property
    def shard_size_y_chunks(self) -> Optional[int]:
        return self._shard_size_y_chunks

    @shard_size_y_chunks.setter
    def shard_size_y_chunks(self, value: Optional[int]) -> None:
        self._shard_size_y_chunks = None if value is None else max(1, int(value))

    @property
    def shard_size_z_chunks(self) -> Optional[int]:
        return self._shard_size_z_chunks

    @shard_size_z_chunks.setter
    def shard_size_z_chunks(self, value: Optional[int]) -> None:
        self._shard_size_z_chunks = None if value is None else max(1, int(value))

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
        frame_count_px = int(max(0, frame_count_px))
        self._frame_count_px = frame_count_px
        # Keep legacy/internal field in sync because prepare() still references it.
        self._frame_count_px_px = frame_count_px

    @property
    def chunk_count_px(self) -> int:
        """Get the chunk count in pixels

        :return: Chunk count in pixels
        :rtype: int
        """
        return CHUNK_COUNT_PX

    @property
    def input_axis_order(self) -> str:
        """Axis order of incoming shared-memory volumes (``zyx`` or ``xzy``)."""
        return self._input_axis_order

    @input_axis_order.setter
    def input_axis_order(self, value: str) -> None:
        normalized = str(value).strip().lower()
        if normalized not in {"zyx", "xzy"}:
            raise ValueError("input_axis_order must be 'zyx' or 'xzy'")
        self._input_axis_order = normalized


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
        if isinstance(shuffle, bool):
            normalized = 1 if shuffle else 0
        elif isinstance(shuffle, str):
            names = {"none": 0, "off": 0, "byte": 1, "on": 1, "bit": 2}
            try:
                normalized = names[shuffle.strip().lower()]
            except KeyError as exc:
                raise ValueError("shuffle must be NONE/OFF, BYTE/ON, BIT, or 0/1/2") from exc
        else:
            normalized = int(shuffle)
        if normalized not in (0, 1, 2):
            raise ValueError("shuffle must be NONE/OFF, BYTE/ON, BIT, or 0/1/2")
        self.log.info(f"setting zarr shuffle to: {normalized}")
        self._shuffle = normalized

    @property
    def b3d_enabled(self) -> bool:
        return self._b3d_enabled

    @b3d_enabled.setter
    def b3d_enabled(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("b3d_enabled must be a bool")
        self._b3d_enabled = value

    @property
    def b3d_mode(self) -> int:
        return self._b3d_mode

    @b3d_mode.setter
    def b3d_mode(self, value: int) -> None:
        result = int(value)
        if result not in (1, 2):
            raise ValueError("b3d_mode must be 1 or 2")
        self._b3d_mode = result

    @staticmethod
    def _positive_float(value, name: str) -> float:
        result = float(value)
        if not np.isfinite(result) or result <= 0:
            raise ValueError(f"{name} must be finite and greater than zero")
        return result

    @property
    def b3d_quant_step(self) -> float:
        return self._b3d_quant_step

    @b3d_quant_step.setter
    def b3d_quant_step(self, value: float) -> None:
        self._b3d_quant_step = self._positive_float(value, "b3d_quant_step")

    @property
    def b3d_conversion(self) -> float:
        return self._b3d_conversion

    @b3d_conversion.setter
    def b3d_conversion(self, value: float) -> None:
        self._b3d_conversion = self._positive_float(value, "b3d_conversion")

    @property
    def b3d_background(self) -> float:
        return self._b3d_background

    @b3d_background.setter
    def b3d_background(self, value: float) -> None:
        result = float(value)
        if not np.isfinite(result):
            raise ValueError("b3d_background must be finite")
        self._b3d_background = result

    @property
    def b3d_read_noise(self) -> float:
        return self._b3d_read_noise

    @b3d_read_noise.setter
    def b3d_read_noise(self, value: float) -> None:
        result = float(value)
        if not np.isfinite(result) or result < 0:
            raise ValueError("b3d_read_noise must be finite and non-negative")
        self._b3d_read_noise = result

    @property
    def b3d_tile_size(self) -> int:
        return self._b3d_tile_size

    @b3d_tile_size.setter
    def b3d_tile_size(self, value: int) -> None:
        result = int(value)
        if not 1 <= result <= 65535:
            raise ValueError("b3d_tile_size must be between 1 and 65535")
        self._b3d_tile_size = result

    @property
    def b3d_zstd_level(self) -> int:
        return self._b3d_zstd_level

    @b3d_zstd_level.setter
    def b3d_zstd_level(self, value: int) -> None:
        result = int(value)
        if not 1 <= result <= 22:
            raise ValueError("b3d_zstd_level must be between 1 and 22")
        self._b3d_zstd_level = result

    @property
    def b3d_backend(self) -> str:
        return self._b3d_backend

    @b3d_backend.setter
    def b3d_backend(self, value: str) -> None:
        result = str(value).strip().lower()
        if result == "gpu":
            result = "cuda"
        if result not in {"auto", "cpu", "cuda"}:
            raise ValueError("b3d_backend must be 'auto', 'cpu', or 'cuda'")
        self._b3d_backend = result

    @property
    def b3d_cuda_batch_layers(self) -> int:
        """Z chunk layers per CUDA encode call; CPU codecs ignore this."""
        return self._b3d_cuda_batch_layers

    @b3d_cuda_batch_layers.setter
    def b3d_cuda_batch_layers(self, value: int) -> None:
        result = int(value)
        if not 1 <= result <= 64:
            raise ValueError("b3d_cuda_batch_layers must be between 1 and 64")
        self._b3d_cuda_batch_layers = result

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
        # The B3D fork exposes only Zarr v3. Keep accepting the legacy YAML's
        # v2 value so the application can start; modern acquire-zarr writes v3.
        valid = ["v2", "v3"]
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
        # shear = np.tan(self.theta_deg * np.pi / 180.0) * size_y / size_z
        shear = -1.414214
        # shift tile in x, unit pixels
        shift_x = scale_x * (self._x_position_mm * 1000 / size_z)
        # shift tile in y, unit pixels
        shift_y = -scale_y * (self._y_position_mm * 1000 / size_x)
        # shift tile in z, unit pixels
        shift_z = scale_z * (self._z_position_mm * 1000 / size_y)

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
        if self._input_axis_order == "xzy":
            # Incoming (scan x, camera z, camera y) becomes OME (z, y, x).
            image_size = pw.ImageSize(
                x=self._frame_count_px,
                y=self._column_count_px,
                z=self._row_count_px,
                c=1,
                t=1,
            )
            self.stack_shapes[0] = (
                self._row_count_px,
                self._column_count_px,
                self._frame_count_px,
            )
            block_size = pw.ImageSize(
                x=self._chunk_size_x_px,
                y=self._chunk_size_y_px,
                z=self._chunk_size_z_px,
                c=1,
                t=1,
            )
        else:
            image_size_z = int(self._frame_count_px)
            image_size = pw.ImageSize(
                x=self._column_count_px,
                y=self._row_count_px,
                z=image_size_z,
                c=1,
                t=1,
            )
            self.stack_shapes[0] = (
                image_size_z,
                self._row_count_px,
                self._column_count_px,
            )
            block_size = pw.ImageSize(
                x=self._column_count_px,
                y=self._row_count_px,
                z=CHUNK_COUNT_PX,
                c=1,
                t=1,
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
            # print('xml name', self.filename_xml)
            self.filename_xml = self.filename_xml[:-5]+'.xml'
            # print('xml name 2', self.filename_xml)
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
            if self._b3d_enabled:
                imgload.set('format', 'bdv.b3d.zarr3')
                imgload.set('version', '1.0')
                views = ET.SubElement(imgload, 'views')
                for itime in range(self.ntimes):
                    for isetup in range(self.nsetups):
                        if self.setup_id_present[itime][isetup]:
                            view = ET.SubElement(
                                views,
                                'view',
                                {
                                    'setup': str(isetup),
                                    'timepoint': str(itime),
                                },
                            )
                            zarr = ET.SubElement(view, 'zarr', {'type': 'relative'})
                            zarr.text = os.path.basename(filename)
                            ET.SubElement(view, 'dataset').text = '0'
            else:
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
            # print('Before registrations', self.ntimes, self.nsetups)
            # print(self.setup_id_present[itime][isetup])
            for itime in range(self.ntimes):
                for isetup in range(self.nsetups):
                    # print(self.setup_id_present)
                    # print(self.setup_id_present[itime][isetup])
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
            # print('End of xml writing function', self.filename_xml)
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

    def _modern_compression_settings(self):
        """Build acquire-zarr >=0.6 compression settings."""
        if self._b3d_enabled:
            # Complete B3D array codecs are mutually exclusive with
            # ordinary Blosc CompressionSettings.
            return None
        if self.compression == "none":
            return None
        return aqz.CompressionSettings(
            compressor=aqz.Compressor.BLOSC1,
            codec=self._compression,
            level=self._clevel,
            shuffle=self._shuffle,
        )

    def _modern_b3d_codec_settings(self):
        """Build the selected custom acquire-zarr B3D codec settings."""
        if not self._b3d_enabled:
            return None
        settings_name = f"B3DMode{self._b3d_mode}CodecSettings"
        settings_class = getattr(aqz, settings_name, None)
        if settings_class is None:
            raise RuntimeError(
                f"B3D Mode {self._b3d_mode} requires acquire-zarr exposing "
                f"{settings_name}"
            )
        if self._data_type != "uint16":
            raise ValueError(
                f"b3d.mode{self._b3d_mode} version 1 supports only uint16 data"
            )
        backend = {
            "auto": aqz.B3DBackend.AUTO,
            "cpu": aqz.B3DBackend.CPU,
            "cuda": aqz.B3DBackend.CUDA,
        }[self._b3d_backend]
        return settings_class(
            quant_step=self._b3d_quant_step,
            conversion=self._b3d_conversion,
            background=self._b3d_background,
            read_noise=self._b3d_read_noise,
            tile_size=self._b3d_tile_size,
            zstd_level=self._b3d_zstd_level,
            backend=backend,
            cuda_batch_layers=self._b3d_cuda_batch_layers,
        )

    def _ome_dimension_values(self):
        """Return canonical OME z,y,x sizes, chunks, shards, and scales."""
        if self._input_axis_order == "xzy":
            sizes = {
                "z": self.row_count_px,
                "y": self.column_count_px,
                "x": self.frame_count_px,
            }
        else:
            sizes = {
                "z": self.frame_count_px,
                "y": self.row_count_px,
                "x": self.column_count_px,
            }
        chunks = {
            "z": self._chunk_size_z_px,
            "y": self._chunk_size_y_px,
            "x": self._chunk_size_x_px,
        }
        configured_shards = {
            "z": self._shard_size_z_chunks,
            "y": self._shard_size_y_chunks,
            "x": self._shard_size_x_chunks,
        }
        shards = {
            axis: configured_shards[axis]
            or (1 if axis == "z" else ceil(sizes[axis] / chunks[axis]))
            for axis in "zyx"
        }
        scales = {
            "z": float(self._z_voxel_size_um or 1.0),
            "y": float(self._y_voxel_size_um or 1.0),
            "x": float(self._x_voxel_size_um or 1.0),
        }
        return sizes, chunks, shards, scales

    def _modern_ome_dimensions(self):
        sizes, chunks, shards, scales = self._ome_dimension_values()
        return [
            aqz.Dimension(
                name=axis,
                kind=aqz.DimensionType.SPACE,
                unit="micrometer",
                scale=scales[axis],
                array_size_px=sizes[axis],
                chunk_size_px=chunks[axis],
                shard_size_chunks=shards[axis],
            )
            for axis in "zyx"
        ]

    def _create_modern_stream_settings(self, filepath: Path):
        compression_settings = self._modern_compression_settings()
        b3d_codec_settings = self._modern_b3d_codec_settings()
        dimensions = self._modern_ome_dimensions()
        array_kwargs = {
            "output_key": "0",
            "compression": compression_settings,
            "codec": b3d_codec_settings,
            "dimensions": dimensions,
            "data_type": DATA_TYPES[self._data_type],
        }
        if self._multiscale:
            array_kwargs["downsampling_method"] = aqz.DownsamplingMethod.MEAN
        array_settings = aqz.ArraySettings(**array_kwargs)
        if self._version != "v3":
            logger = getattr(self, "log", None)
            if logger is not None:
                logger.warning(
                    "acquire-zarr >=0.6 writes Zarr v3; treating configured version %s as v3",
                    self._version,
                )
        return aqz.StreamSettings(
            store_path=str(filepath),
            version=aqz.ZarrVersion.V3,
            overwrite=False,
            arrays=[array_settings],
        )

    def _create_legacy_stream_settings(self, filepath: Path):
        if self._b3d_enabled:
            raise RuntimeError(
                "B3D requires acquire-zarr exposing ArraySettings and "
                "B3DMode1CodecSettings/B3DMode2CodecSettings"
            )
        compression_settings = aqz.CompressionSettings(
            codec=self._compression,
            compressor=aqz.Compressor.BLOSC1,
            clevel=self._clevel,
            shuffle=self._shuffle,
        )
        version = VERSIONS.get(self._version)
        if version is None:
            raise RuntimeError(f"Installed acquire-zarr does not support {self._version}")
        settings = aqz.StreamSettings(
            store_path=str(filepath),
            data_type=DATA_TYPES[self._data_type],
            version=version,
            multiscale=self._multiscale,
            compression=compression_settings if self.compression != "none" else None,
        )
        sizes, chunks, shards, _ = self._ome_dimension_values()
        settings.dimensions.extend(
            [
                aqz.Dimension(
                    name=axis,
                    type=aqz.DimensionType.SPACE,
                    array_size_px=sizes[axis],
                    chunk_size_px=chunks[axis],
                    shard_size_chunks=shards[axis],
                )
                for axis in "zyx"
            ]
        )
        return settings

    def _create_stream_settings(self, filepath: Path):
        if hasattr(aqz, "ArraySettings"):
            return self._create_modern_stream_settings(filepath)
        return self._create_legacy_stream_settings(filepath)

    def _append_xzy_volume_as_ome_zyx(
        self, stream, volume_xzy, shared_progress=None
    ) -> None:
        """Transpose a staged OTLS x,z,y volume into bounded z,y,x appends."""
        if tuple(volume_xzy.shape) != (
            int(self.frame_count_px),
            int(self.row_count_px),
            int(self.column_count_px),
        ):
            raise ValueError(
                "Staged xzy volume shape does not match writer geometry: "
                f"{tuple(volume_xzy.shape)}"
            )
        # Keep transpose memory bounded. acquire-zarr may buffer these slabs until
        # a complete z chunk is available.
        slab_depth = max(1, min(int(self._chunk_size_z_px or 1), 8))
        for z_start in range(0, int(self.row_count_px), slab_depth):
            z_stop = min(int(self.row_count_px), z_start + slab_depth)
            block_zyx = np.ascontiguousarray(
                np.transpose(volume_xzy[:, z_start:z_stop, :], (1, 2, 0))
            )
            stream.append(block_zyx)
            if shared_progress is not None:
                shared_progress.value = 0.8 + 0.2 * (
                    z_stop / float(self.row_count_px)
                )

    @staticmethod
    def _read_stable_zarr_metadata(
        metadata_paths, stability_seconds: float = 0.25, timeout_seconds: float = 5.0
    ):
        """Wait for acquire-zarr metadata writes to finish and parse them."""
        deadline = perf_counter() + timeout_seconds
        previous = None
        unchanged_since = None
        last_error = None
        while perf_counter() < deadline:
            try:
                snapshot = tuple(path.read_bytes() for path in metadata_paths)
                parsed = tuple(json.loads(data) for data in snapshot)
            except (OSError, json.JSONDecodeError) as exc:
                last_error = exc
                previous = None
                unchanged_since = None
                sleep(0.02)
                continue
            now = perf_counter()
            if snapshot == previous:
                if unchanged_since is not None and now - unchanged_since >= stability_seconds:
                    return parsed
            else:
                previous = snapshot
                unchanged_since = now
            sleep(0.02)
        raise RuntimeError(
            "acquire-zarr metadata did not become stable after close"
        ) from last_error

    @staticmethod
    def _atomic_write_json(path: Path, payload) -> None:
        """Replace one JSON file atomically so readers never observe a partial write."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            delete=False,
        )
        temporary_path = Path(handle.name)
        try:
            with handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def _write_ome_zarr_metadata(self, filepath: Path) -> None:
        """Atomically publish OME and valid-frame metadata after stream close."""
        _, _, _, scales = self._ome_dimension_values()
        root_metadata_path = filepath / "zarr.json"
        array_metadata_path = filepath / "0" / "zarr.json"
        root_metadata, array_metadata = self._read_stable_zarr_metadata(
            (root_metadata_path, array_metadata_path)
        )
        root_attributes = dict(root_metadata.get("attributes", {}) or {})
        root_attributes["ome"] = {
            "version": "0.5",
            "multiscales": [
                {
                    "name": Path(self._filename).stem,
                    "axes": [
                        {"name": axis, "type": "space", "unit": "micrometer"}
                        for axis in "zyx"
                    ],
                    "datasets": [
                        {
                            "path": "0",
                            "coordinateTransformations": [
                                {
                                    "type": "scale",
                                    "scale": [scales[axis] for axis in "zyx"],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        root_attributes["valid_frame_count_px"] = int(self._frame_count_px)
        root_metadata["attributes"] = root_attributes

        array_attributes = dict(array_metadata.get("attributes", {}) or {})
        array_attributes["valid_frame_count_px"] = int(self._frame_count_px)
        array_metadata["attributes"] = array_attributes

        # Publish the array metadata first and the root group last.  The root is
        # the store's entry point, so a reader that sees the new root also sees
        # the completed child metadata.
        self._atomic_write_json(array_metadata_path, array_metadata)
        self._atomic_write_json(root_metadata_path, root_metadata)

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

        settings = self._create_stream_settings(filepath)
        stream = aqz.ZarrStream(settings)
        staged_volume = None
        staged_path = None
        if self._input_axis_order == "xzy":
            filepath.parent.mkdir(parents=True, exist_ok=True)
            staged_file = tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{filepath.stem}.",
                suffix=".xzy.tmp",
                dir=str(filepath.parent),
                delete=False,
            )
            staged_path = Path(staged_file.name)
            staged_file.close()
            staged_volume = np.memmap(
                staged_path,
                mode="w+",
                dtype=self._data_type,
                shape=(
                    int(self.frame_count_px),
                    int(self.row_count_px),
                    int(self.column_count_px),
                ),
            )

        try:
            chunk_total = ceil(self._frame_count_px / CHUNK_COUNT_PX)
            for chunk_num in range(chunk_total):
                # Wait for new data.
                while self.done_reading.is_set():
                    sleep(0.001)
                # Attach a reference to the data from shared memory.
                shm = SharedMemory(self.shm_name, create=False, size=shm_nbytes)
                frames = np.ndarray(shm_shape, self._data_type, buffer=shm.buf)
                frame_start = int(chunk_num * CHUNK_COUNT_PX)
                remaining_frames = int(self._frame_count_px - frame_start)
                valid_frames = int(
                    min(int(frames.shape[0]), max(0, remaining_frames))
                )
                if valid_frames <= 0:
                    shm.close()
                    self.done_reading.set()
                    break

                if staged_volume is not None:
                    frame_stop = frame_start + valid_frames
                    staged_volume[frame_start:frame_stop, :, :] = frames[:valid_frames]
                else:
                    stream.append(frames[:valid_frames])
                frames = None
                shm.close()
                self.done_reading.set()
                if staged_volume is not None:
                    shared_progress.value = 0.8 * (chunk_num + 1) / chunk_total
                else:
                    shared_progress.value = (chunk_num + 1) / chunk_total

            if staged_volume is not None:
                staged_volume.flush()
                self._append_xzy_volume_as_ome_zyx(
                    stream, staged_volume, shared_progress=shared_progress
                )

            stream.close()
            stream = None
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if staged_volume is not None:
                staged_volume.flush()
                del staged_volume
            if staged_path is not None:
                try:
                    os.remove(staged_path)
                except OSError:
                    pass

        self._write_ome_zarr_metadata(filepath)

        # check and empty queue to avoid code hanging in process
        if not shared_log_queue.empty:
            shared_log_queue.get_nowait()
