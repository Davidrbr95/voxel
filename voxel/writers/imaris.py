import logging
import multiprocessing
import sys
from ctypes import c_wchar
from datetime import datetime
from math import ceil
from multiprocessing import Array, Process
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from time import perf_counter, sleep
import re
import numpy as np
import os
from matplotlib.colors import hex2color
from PyImarisWriter import PyImarisWriter as pw
from xml.etree import ElementTree as ET

from voxel.descriptors.deliminated_property import DeliminatedProperty
from voxel.writers.base import BaseWriter

CHUNK_COUNT_PX = 32
DIVISIBLE_FRAME_COUNT_PX = 32

COMPRESSION_TYPES = {
    "lz4shuffle": pw.eCompressionAlgorithmShuffleLZ4,
    "none": pw.eCompressionAlgorithmNone,
}


class ImarisProgressChecker(pw.CallbackClass):
    """
    Class for tracking progress of an active Imaris writer.
    """

    def __init__(self):
        self.progress = 0  # a float representing the progress (0 to 1.0)

    def RecordProgress(self, progress, total_bytes_written):
        self.progress = progress


class ImarisWriter(BaseWriter):
    """
    Voxel driver for the Imaris writer.

    Writer will save data to the following location

    path\\acquisition_name\\filename.ims

    :param path: Path for the data writer
    :type path: str
    """

    def __init__(self, path: str):
        super().__init__(path)
        self._color = "#ffffff"  # initialize as white
        # Internal flow control attributes to monitor compression progress
        self.callback_class = ImarisProgressChecker()
        self.nilluminations=1
        self.nchannels=1
        self.ntiles=1
        self.nangles=1
        self.ntimes = 1
        self.filepath = None
        self.nsetups = self.nilluminations * self.nchannels * self.ntiles * self.nangles
        self.attribute_counts = {'illumination': self.nilluminations, 'channel': self.nchannels,
                                 'angle': self.nangles, 'tile': self.ntiles}
        # self.nlevels = len(subsamp)
        # self.chunks = self._compute_chunk_size(blockdim)
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
    def frame_count_px(self):
        """Get the number of frames in the writer.

        :return: Frame number in pixels
        :rtype: int
        """

        return self._frame_count_px

    @frame_count_px.setter
    def frame_count_px(self, frame_count_px: int):
        """Set the number of frames in the writer.

        :param value: Frame number in pixels
        :type value: int
        """

        self.log.info(f"setting frame count to: {frame_count_px} [px]")
        self._frame_count_px = int(max(0, frame_count_px))

    @property
    def chunk_count_px(self):
        """Get the chunk count in pixels

        :return: Chunk count in pixels
        :rtype: int
        """

        return CHUNK_COUNT_PX

    @property
    def compression(self):
        """Get the compression codec of the writer.

        :return: Compression codec
        :rtype: str
        """

        return next(
            key
            for key, value in COMPRESSION_TYPES.items()
            if value == self._compression
        )

    @compression.setter
    def compression(self, compression: str):
        """Set the compression codec of the writer.

        :param value: Compression codec
        * **lz4shuffle**
        * **none**
        :type value: str
        """

        valid = list(COMPRESSION_TYPES.keys())
        if compression not in valid:
            raise ValueError("compression type must be one of %r." % valid)
        self.log.info(f"setting compression mode to: {compression}")
        self._compression = COMPRESSION_TYPES[compression]

    @property
    def filename(self):
        """
        The base filename of file writer.

        :return: The base filename
        :rtype: str
        """

        return self._filename

    @filename.setter
    def filename(self, filename: str):
        """
        The base filename of file writer.

        :param value: The base filename
        :type value: str
        """

        self._filename = filename if filename.endswith(".ims") else f"{filename}.ims"
        self.log.info(f"setting filename to: {filename}")

    @property
    def color(self):
        """
        The color of the writer.

        :return: Color
        :rtype: str
        """

        return self._color

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

    @color.setter
    def color(self, color: str):
        """
        The color of the writer.

        :param value: Color
        :type value: str
        """

        if re.search(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color):
            self._color = color
        else:
            raise ValueError("%r is not a valid hex color code." % color)
        self.log.info(f"setting color to: {color}")

    def delete_files(self):
        """
        Delete all files generated by the writer.
        """
        filepath = Path(self._path, self._acquisition_name, self._filename).absolute()
        os.remove(filepath)

    def prepare(self):
        """
        Prepare the writer.
        """
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
        shm_nbytes = int(
            np.prod(shm_shape, dtype=np.int64) * np.dtype(self._data_type).itemsize
        )

        # Check if tile position already exists
        tile_position = (self._x_position_mm, self._y_position_mm, self._z_position_mm)
        if tile_position not in self.tile_list:
            self.tile_list.append(tile_position)
        self.current_tile_num = self.tile_list.index(tile_position)

        # Check if tile channel already exists
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
        shear = np.tan(self._theta_deg * np.pi / 180.0) * size_y / size_z
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
        image_size_z = int(self._frame_count_px)
        image_size = pw.ImageSize(
            x=self._column_count_px, y=self._row_count_px, z=image_size_z, c=1, t=1
        )
        self.stack_shapes[0] = (image_size_z, self._row_count_px, self._column_count_px)
        block_size = pw.ImageSize(
            x=self._column_count_px, y=self._row_count_px, z=CHUNK_COUNT_PX, c=1, t=1
        )
        sample_size = pw.ImageSize(x=1, y=1, z=1, c=1, t=1)
        # compute the start/end extremes of the enclosed rectangular solid.
        # (x0, y0, z0) position (in [um]) of the beginning of the first voxel,
        # (xf, yf, zf) position (in [um]) of the end of the last voxel.
        x0 = self._x_position_mm - (
            self._x_voxel_size_um * 0.5 * self._column_count_px
        )
        y0 = self._y_position_mm - (self._y_voxel_size_um * 0.5 * self._row_count_px)
        z0 = self._z_position_mm
        xf = self._x_position_mm + (
            self._x_voxel_size_um * 0.5 * self._column_count_px
        )
        yf = self._y_position_mm + (self._y_voxel_size_um * 0.5 * self._row_count_px)
        zf = self._z_position_mm + self._frame_count_px * self._z_voxel_size_um
        image_extents = pw.ImageExtents(-x0, -y0, -z0, -xf, -yf, -zf)
        # c = channel, t = time. These fields are unused for now.
        # Note: ImarisWriter performs MUCH faster when the dimension sequence
        #   is arranged: x, y, z, c, t.
        #   It is more efficient to transpose/reshape the data into this
        #   shape beforehand instead of defining an arbitrary
        #   DimensionSequence and passing the chunk data in as-is.
        dimension_sequence = pw.DimensionSequence("x", "y", "z", "c", "t")
        # lookups for deducing order
        dim_map = {"x": 0, "y": 1, "z": 2, "c": 3, "t": 4}
        # name parameters
        parameters = pw.Parameters()
        parameters.set_channel_name(0, self._channel)
        # create options object
        opts = pw.Options()
        opts.mEnableLogProgress = True
        # set threads to double number of cores
        thread_count = 2 * multiprocessing.cpu_count()
        opts.mNumberOfThreads = thread_count
        # set compression type
        opts.mCompressionAlgorithmType = self._compression
        # color parameters
        color_infos = [pw.ColorInfo()]
        color_infos[0].set_base_color(pw.Color(*(*hex2color(self._color), 1.0)))
        adjust_color_range = False
        # date time parameters
        time_infos = [datetime.today()]
        # create run process
        self._process = Process(
            target=self._run,
            args=(
                chunk_dim_order,
                shm_shape,
                shm_nbytes,
                image_size,
                block_size,
                sample_size,
                image_extents,
                dimension_sequence,
                dim_map,
                parameters,
                opts,
                color_infos,
                adjust_color_range,
                time_infos,
                self._progress,
                self._log_queue,
            ),
        )
    def _update_setup_id_present(self, isetup, itime):
        """Update the lookup table (list of lists) for missing setups"""
        if len(self.setup_id_present) <= itime:
            self.setup_id_present.append([False] * self.nsetups)
        self.setup_id_present[itime][isetup] = True

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

    ### THIS WAS COMMENTED OUT
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
        self.filename_xml = self.filename_xml[:-4]+'.xml'
        print('xml name 2', self.filename_xml)
        filename = self.filename[:-4]+'.zarr'
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

    ### THIS WAS COMMENTED OUT
    def _run(
        self,
        chunk_dim_order: tuple,
        shm_shape: list,
        shm_nbytes: int,
        image_size: pw.ImageSize,
        block_size: pw.ImageSize,
        sample_size: pw.ImageSize,
        image_extents: pw.ImageExtents,
        dimension_sequence: pw.DimensionSequence,
        dim_map: dict,
        parameters: pw.Parameters,
        opts: pw.Options,
        color_infos: pw.ColorInfo,
        adjust_color_range: bool,
        time_infos: datetime,
        shared_progress: multiprocessing.Value,
        shared_log_queue: multiprocessing.Queue,
    ):
        """
        Main run function of the Imaris writer.

        :param chunk_dim_order: Dimension order of chunks
        :type chunk_dim_order: tuple
        :param shm_shape: Shared memory address shape
        :type shm_shape: list
        :param shm_nbytes: Shared memory address bytes
        :type shm_nbytes: int
        :param image_size: Size of the array to be written
        :type image_size: PyImarisWriter.ImageSize
        :param block_size: Size of each block to be written
        :type block_size: PyImarisWriter.ImageSize
        :param sample_size: Sample size (i.e. number of arrays) to be written
        :type sample_size: PyImarisWriter.ImageSize
        :param image_extents: Physical extents of the array to be written
        :type image_extents: PyImarisWriter.ImageExtents
        :param dimension_sequence: Dimension sequence of the writer
        :type dimension_sequence: PyImarisWriter.DimensionSequence
        :param dim_map: Dictionary map of dimension order
        :type dim_map: dict
        :param parameters: Parameters of the Imaris writer
        :type parameters: PyImarisWriter.Parameters
        :param opts: Options of the Imaris writer
        :type opts: PyImarisWriter.Options
        :param color_infos: Color information of the Imaris writer
        :type color_infos: PyImarisWriter.ColorInfo
        :param adjust_color_range: Adjust color range for the Imaris writer
        :type adjust_color_range: bool
        :param time_infos: Time information of the Imaris writer
        :type time_infos: datetime
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
        # self.write_xml(filepath)
        application_name = "PyImarisWriter"
        application_version = "1.0.0"

        converter = pw.ImageConverter(
            self._data_type,
            image_size,
            sample_size,
            dimension_sequence,
            block_size,
            filepath,
            opts,
            application_name,
            application_version,
            self.callback_class,
        )
        chunk_total = ceil(self._frame_count_px / CHUNK_COUNT_PX)
        for chunk_num in range(chunk_total):
            block_index = pw.ImageSize(x=0, y=0, z=chunk_num, c=0, t=0)
            # Wait for new data.
            while self.done_reading.is_set():
                sleep(0.001)
            # Attach a reference to the data from shared memory.
            shm = SharedMemory(self.shm_name, create=False, size=shm_nbytes)
            frames = np.ndarray(shm_shape, self._data_type, buffer=shm.buf)
            frame_start = int(chunk_num * CHUNK_COUNT_PX)
            remaining_frames = int(self._frame_count_px - frame_start)
            valid_frames = int(min(int(frames.shape[0]), max(0, remaining_frames)))
            if valid_frames <= 0:
                shm.close()
                self.done_reading.set()
                shared_progress.value = 1.0
                break
            shared_log_queue.put(
                f"{self._filename}: writing chunk "
                f"{chunk_num+1}/{chunk_total} of size {frames.shape}."
            )
            start_time = perf_counter()
            dim_order = [dim_map[x] for x in chunk_dim_order]
            # Put the frames back into x, y, z, c, t order.
            converter.CopyBlock(frames[:valid_frames].transpose(dim_order), block_index)
            frames = None
            shared_log_queue.put(
                f"{self._filename}: writing chunk took "
                f"{perf_counter() - start_time:.3f} [s]"
            )
            shm.close()
            self.done_reading.set()
            # update shared value progress range 0-1
            shared_progress.value = (chunk_num+1)/chunk_total

        # wait for file writing to finish
        if self.callback_class.progress < 1.0:
            shared_log_queue.put(
                f"{self._filename}: waiting for data writing to complete for "
                f"{self._filename}. "
                f"current progress is {100*self.callback_class.progress:.1f}%."
            )
        while self.callback_class.progress < 1.0:
            sleep(0.5)
            shared_log_queue.put(
                f"{self._filename}: waiting for data writing to complete for "
                f"{self._filename}. "
                f"current progress is {100*self.callback_class.progress:.1f}%."
            )

        converter.Finish(
            image_extents,
            parameters,
            time_infos,
            color_infos,
            adjust_color_range,
        )
        converter.Destroy()
