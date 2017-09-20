#
# This file is part of postpic.
#
# postpic is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# postpic is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with postpic. If not, see <http://www.gnu.org/licenses/>.
#
# Stephan Kuschel, 2014-2017
# Alexander Blinne, 2017
"""
The Core module for final data handling.

This module provides classes for dealing with axes, grid as well as the Field
class -- the final output of the postpic postprocessor.

Terminology
-----------

A data field with N numeric points has N 'grid' points,
but N+1 'grid_nodes' as depicted here:

+---+---+---+---+---+
|   |   |   |   |   |
+---+---+---+---+---+
|   |   |   |   |   |
+---+---+---+---+---+
|   |   |   |   |   |
+---+---+---+---+---+
  o   o   o   o   o     grid      (coordinates where data is sampled at)
o   o   o   o   o   o   grid_node (coordinates of grid cell boundaries)
|                   |   extent
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import collections
import copy

import numpy as np
import numpy.fft as fft
import scipy.ndimage as spnd
from . import helper

__all__ = ['Field', 'Axis']


class Axis(object):
    '''
    Axis handling for a single Axis.
    '''

    def __init__(self, name='', unit=''):
        self.name = name
        self.unit = unit
        self._grid_node = np.array([])
        self._linear = None

    def __copy__(self):
        '''
        returns a shallow copy of the object.
        This method is called by `copy.copy(obj)`.
        '''
        cls = type(self)
        ret = cls.__new__(cls)
        ret.__dict__.update(self.__dict__)
        return ret

    def islinear(self, force=False):
        """
        Checks if the axis has a linear grid.
        """
        if self._linear is None or force:
            self._linear = np.var(np.diff(self._grid_node)) < 1e-7
        return self._linear

    @property
    def grid_node(self):
        return self._grid_node

    @grid_node.setter
    def grid_node(self, value):
        gn = np.float64(value)
        if len(gn.shape) != 1:
            raise TypeError('Only 1 dimensional arrays can be assigend.')
        self._grid_node = gn
        self._linear = None

    @property
    def grid(self):
        return np.convolve(self.grid_node, np.ones(2) / 2.0, mode='valid')

    @grid.setter
    def grid(self, grid):
        gn = np.convolve(grid, np.ones(2) / 2.0, mode='full')
        gn[0] = grid[0] + (grid[0] - gn[1])
        gn[-1] = grid[-1] + (grid[-1] - gn[-2])
        self.grid_node = gn
        self._linear = None

    @property
    def spacing(self):
        if not self.islinear():
            raise TypeError('Grid must be linear to calculate gridspacing')
        return self.grid_node[1] - self.grid_node[0]

    @property
    def extent(self):
        if len(self._grid_node) < 2:
            ret = None
        else:
            ret = [self._grid_node[0], self._grid_node[-1]]
        return ret

    @property
    def label(self):
        if self.unit == '':
            ret = self.name
        else:
            ret = self.name + ' [' + self.unit + ']'
        return ret

    def setextent(self, extent, n):
        '''
        creates a linear grid with the given extent and n grid points
        (thus n+1 grid_node)
        '''
        if n == 1 and type(extent) is int:
            gn = np.array([extent - 0.5, extent + 0.5])
        else:
            gn = np.linspace(extent[0], extent[-1], n + 1)
        self.grid_node = gn

    def half_resolution(self):
        '''
        removes every second grid_node.
        '''
        ret = copy.copy(self)
        ret.grid_node = ret.grid_node[::2]
        return ret

    def _extent_to_slice(self, extent):
        a, b = extent
        if a is None:
            a = self._grid_node[0]
        if b is None:
            b = self._grid_node[-1]
        return slice(*np.searchsorted(self.grid, np.sort([a, b])))

    def _normalize_slice(self, index):
        """
        Applies some checks and transformations to the object passed
        to __getitem__
        """
        if isinstance(index, slice):
            if any(helper.is_non_integer_real_number(x) for x in (index.start, index.stop)):
                if index.step is not None:
                    raise IndexError('Non-Integer slices should have step == None')
                return self._extent_to_slice((index.start, index.stop))
            return index
        else:
            if helper.is_non_integer_real_number(index):
                index = helper.find_nearest_index(self.grid, index)
            return slice(index, index+1)

    def __getitem__(self, key):
        """
        Returns an Axis which consists of a sub-part of this object defined by
        a slice containing floats or integers or a float or an integer
        """
        ax = copy.copy(self)
        ax.grid = ax.grid[self._normalize_slice(key)]
        return ax

    def __len__(self):
        ret = len(self._grid_node) - 1
        ret = 0 if ret < 0 else ret
        return ret

    def __str__(self):
        return '<Axis "' + str(self.name) + \
               '" (' + str(len(self)) + ' grid points)'


def _updatename(operator, reverse=False):
    def ret(func):
        @functools.wraps(func)
        def f(s, o):
            res = func(s, o)
            try:
                (a, b) = (o, s) if reverse else (s, o)
                res.name = a.name + ' ' + operator + ' ' + b.name
            except AttributeError:
                pass
            return res
        return f
    return ret


class Field(object):
    '''
    The Field Object carries a data matrix together with as many Axis
    Objects as the data matrix's dimensions. Additionaly the Field object
    provides any information that is necessary to plot _and_ annotate
    the plot. It will also suggest a content based filename for saving.

    {x,y,z}edges can be the edges or grid_nodes given for each dimension. This is
    made to work with np.histogram oder np.histogram2d.
    '''

    def __init__(self, matrix, xedges=None, yedges=None, zedges=None, name='', unit=''):
        if xedges is not None:
            self._matrix = np.asarray(matrix)  # dont sqeeze. trust numpys histogram functions.
        else:
            self._matrix = np.squeeze(matrix)
        self.name = name
        self.unit = unit
        self.axes = []
        self.infostring = ''
        self.infos = []
        self._label = None  # autogenerated if None
        if xedges is not None:
            self._addaxisnodes(xedges, name='x')
        elif self.dimensions > 0:
            self._addaxis((0, 1), name='x')
        if yedges is not None:
            self._addaxisnodes(yedges, name='y')
        elif self.dimensions > 1:
            self._addaxis((0, 1), name='y')
        if zedges is not None:
            self._addaxisnodes(zedges, name='z')
        elif self.dimensions > 2:
            self._addaxis((0, 1), name='z')

        # Additions due to FFT capabilities

        # self.axes_transform_state is False for axes which live in spatial domain
        # and it is True for axes which live in frequency domain
        # This assumes that fields are initially created in spatial domain.
        self.axes_transform_state = [False] * len(self.shape)

        # self.transformed_axes_origins stores the starting values of the grid
        # from before the last transform was executed, this is used to
        # recreate the correct axis interval upon inverse transform
        self.transformed_axes_origins = [None] * len(self.shape)

    def __copy__(self):
        '''
        returns a shallow copy of the object.
        This method is called by `copy.copy(obj)`.
        Just copy enough to create copies for operator overloading.
        '''
        cls = type(self)
        ret = cls.__new__(cls)
        ret.__dict__.update(self.__dict__)  # shallow copy
        for k in ['infos', 'axes_transform_state', 'transformed_axes_origins']:
            # copy iterables one level deeper
            # but matrix is not copied!
            ret.__dict__[k] = copy.copy(self.__dict__[k])
        # create shallow copies of Axis objects
        ret.axes = [copy.copy(ret.axes[i]) for i in range(len(ret.axes))]
        return ret

    def __array__(self):
        '''
        will be called by numpy function in case an numpy array is needed.
        '''
        return self.matrix

    def _addaxisobj(self, axisobj):
        '''
        uses the given axisobj as the axis obj in the given dimension.
        '''
        # check if number of grid points match
        matrixpts = self.shape[len(self.axes)]
        if matrixpts != len(axisobj):
            raise ValueError(
                'Number of Grid points in next missing Data '
                'Dimension ({:d}) has to match number of grid points of '
                'new axis ({:d})'.format(matrixpts, len(axisobj)))
        self.axes.append(axisobj)

    def _addaxisnodes(self, grid_node, **kwargs):
        ax = Axis(**kwargs)
        ax.grid_node = grid_node
        self._addaxisobj(ax)
        return

    def _addaxis(self, extent, **kwargs):
        '''
        adds a new axis that is supported by the matrix.
        '''
        matrixpts = self.shape[len(self.axes)]
        ax = Axis(**kwargs)
        ax.setextent(extent, matrixpts)
        self._addaxisobj(ax)

    def setaxisobj(self, axis, axisobj):
        '''
        replaces the current axisobject for axis axis by the
        new axisobj axisobj.
        '''
        axid = helper.axesidentify[axis]
        if not len(axisobj) == self.shape[axid]:
            raise ValueError('Axis object has {:3n} grid points, whereas '
                             'the data matrix has {:3n} on axis {:1n}'
                             ''.format(len(axisobj),
                                       self.shape[axid], axid))
        self.axes[axid] = axisobj

    def islinear(self):
        return [a.islinear() for a in self.axes]

    @property
    def label(self):
        if self._label:
            ret = self._label
        elif self.unit == '':
            ret = self.name
        else:
            ret = self.name + ' [' + self.unit + ']'
        return ret

    @label.setter
    def label(self, x):
        self._label = x
        return

    @property
    def matrix(self):
        return self._matrix

    @matrix.setter
    def matrix(self, other):
        if other.shape != self.shape:
            raise ValueError("Shape of old and new matrix must be identical")
        self._matrix = other

    @property
    def shape(self):
        return self.matrix.shape

    @property
    def grid_nodes(self):
        return np.squeeze([a.grid_node for a in self.axes])

    @property
    def grid(self):
        return np.squeeze([a.grid for a in self.axes])

    @property
    def dimensions(self):
        '''
        returns only present dimensions.
        [] and [[]] are interpreted as -1
        np.array(2) is interpreted as 0
        np.array([1,2,3]) is interpreted as 1
        and so on...
        '''
        ret = len(self.shape)  # works for everything with data.
        if np.prod(self.shape) == 0:  # handels everything without data
            ret = -1
        return ret

    @property
    def extent(self):
        '''
        returns the extents in a linearized form,
        as required by "matplotlib.pyplot.imshow".
        '''
        return np.ravel([a.extent for a in self.axes])

    @extent.setter
    def extent(self, newextent):
        '''
        sets the new extent to the specific values
        '''
        if not self.dimensions * 2 == len(newextent):
            raise TypeError('size of newextent doesnt match self.dimensions * 2')
        for i in range(len(self.axes)):
            newax = copy.copy(self.axes[i])
            newax.setextent(newextent[2 * i:2 * i + 2],
                            self.shape[i])
            self.setaxisobj(i, newax)
        return

    @property
    def real(self):
        return self.replace_data(self.matrix.real)

    @property
    def imag(self):
        return self.replace_data(self.matrix.imag)

    @property
    def angle(self):
        return self.replace_data(np.angle(self))

    def replace_data(self, other):
        ret = copy.copy(self)
        ret.matrix = other
        return ret

    def pad(self, pad_width, mode='constant', **kwargs):
        '''
        Pads the matrix using np.pad and takes care of the axes.
        See documentation of np.pad.

        In contrast to np.pad, pad_width may be given as integers, which will be interpreted
        as pixels, or as floats, which will be interpreted as distance along the appropriate axis.

        All other parameters are passed to np.pad unchanged.
        '''
        ret = copy.copy(self)
        if not self.islinear():
            raise ValueError('Padding the axes is only meaningful with linear axes.'
                             'Please apply np.pad to the matrix by yourself and update the axes'
                             'as you like.')

        if not isinstance(pad_width, collections.Iterable):
            pad_width = [pad_width]

        if len(pad_width) == 1:
            pad_width *= self.dimensions

        if len(pad_width) != self.dimensions:
            raise ValueError('Please check your pad_width argument. If it is an Iterable, its'
                             'length must equal the number of dimensions of this Field.')

        pad_width_numpy = []

        for i, axis_pad in enumerate(pad_width):
            if not isinstance(axis_pad, collections.Iterable):
                axis_pad = [axis_pad, axis_pad]

            if len(axis_pad) > 2:
                raise ValueError

            if len(axis_pad) == 1:
                axis_pad = list(axis_pad)*2

            axis = ret.axes[i]

            dx = axis.spacing
            axis_pad = [int(np.ceil(p/dx))
                        if helper.is_non_integer_real_number(p)
                        else p
                        for p
                        in axis_pad]
            pad_width_numpy.append(axis_pad)

            extent = axis.extent
            newextent = [extent[0] - axis_pad[0]*dx, extent[1] + axis_pad[1]*dx]
            gridpoints = len(axis.grid_node) - 1 + axis_pad[0] + axis_pad[1]

            axis.setextent(newextent, gridpoints)

        ret._matrix = np.pad(self, pad_width_numpy, mode, **kwargs)

        return ret

    def half_resolution(self, axis):
        '''
        Halfs the resolution along the given axis by removing
        every second grid_node and averaging every second data point into one.

        if there is an odd number of grid points, the last point will
        be ignored. (that means, the extent will change by the size of
        the last grid cell)
        '''
        axis = helper.axesidentify[axis]
        ret = copy.copy(self)
        n = ret.matrix.ndim
        s1 = [slice(None), ] * n
        s2 = [slice(None), ] * n
        # ignore last grid point if self.matrix.shape[axis] is odd
        lastpt = ret.shape[axis] - ret.shape[axis] % 2
        # Averaging over neighboring points
        s1[axis] = slice(0, lastpt, 2)
        s2[axis] = slice(1, lastpt, 2)
        m = (ret.matrix[s1] + ret.matrix[s2]) / 2.0
        ret._matrix = m
        ret.setaxisobj(axis, ret.axes[axis].half_resolution())
        return ret

    def autoreduce(self, maxlen=4000):
        '''
        Reduces the Grid to a maximum length of maxlen per dimension
        by just executing half_resolution as often as necessary.
        '''
        ret = self  # half_resolution will take care for the copy
        for i in range(len(ret.axes)):
            if len(ret.axes[i]) > maxlen:
                ret = ret.half_resolution(i)
                ret = ret.autoreduce(maxlen=maxlen)
                break
        return ret

    def cutout(self, newextent):
        '''
        only keeps that part of the matrix, that belongs to newextent.
        '''
        slices = self._extent_to_slices(newextent)
        return self[slices]

    def squeeze(self):
        '''
        removes axes that have length 1, reducing self.dimensions
        '''
        ret = copy.copy(self)
        ret.axes = [ax for ax in ret.axes if len(ax) > 1]
        ret._matrix = np.squeeze(ret.matrix)
        assert tuple(len(ax) for ax in ret.axes) == ret.shape
        return ret

    def mean(self, axis=-1):
        '''
        takes the mean along the given axis.
        '''
        ret = copy.copy(self)
        if self.dimensions == 0:
            return self
        ret._matrix = np.mean(ret.matrix, axis=axis)
        ret.axes.pop(axis)
        return ret

    def _transform_state(self, axes):
        """
        Returns the collective transform state of the given axes

        If all mentioned axis i have self.axes_transform_state[i]==True return True
        (All axes live in frequency domain)
        If all mentioned axis i have self.axes_transform_state[i]==False return False
        (All axes live in spatial domain)
        Else return None
        (Axes have mixed transform_state)
        """
        for b in [True, False]:
            if all(self.axes_transform_state[i] == b for i in axes):
                return b
        return None

    def fft(self, axes=None):
        '''
        Performs Fourier transform on any number of axes.

        The argument axis is a tuple giving the numebers of the axes that
        should be transformed. Automatically determines forward/inverse transform.
        Transform is only applied if all mentioned axes are in the same space.
        If an axis is transformed twice, the origin of the axis is restored.
        '''
        # If axes is None, transform all axes
        if axes is None:
            axes = range(self.dimensions)

        # List axes uniquely and in ascending order
        axes = sorted(set(axes))

        if not all(self.axes[i].islinear() for i in axes):
            raise ValueError("FFT only allowed for linear grids")

        # Get the collective transform state of the axes
        transform_state = self._transform_state(axes)

        if transform_state is None:
            raise ValueError("FFT only allowed if all mentioned axes are in same transform state")

        # Record current axes origins of transformed axes
        new_origins = {i: self.axes[i].grid[0] for i in axes}

        # Grid spacing
        dx = {i: self.axes[i].spacing for i in axes}

        # Unit volume of transform
        dV = np.product(list(dx.values()))

        # Number of grid cells of transform
        N = np.product([self.shape[i] for i in axes])

        # Total volume of transform
        V = dV*N

        # Total volume of conjugate space
        Vk = (2*np.pi)**len(dx)/dV

        # normalization factor ensuring Parseval's Theorem
        fftnorm = np.sqrt(V/Vk)

        # new axes in conjugate space
        new_axes = {
            i: fft.fftshift(2*np.pi*fft.fftfreq(self.shape[i], dx[i]))
            for i in axes
        }

        ret = copy.copy(self)

        # Transforming from spatial domain to frequency domain ...
        if transform_state is False:
            new_axesobjs = {
                i: Axis('k'+self.axes[i].name,
                        '1/'+self.axes[i].unit)
                for i in axes
            }
            ret.matrix = fftnorm \
                * fft.fftshift(fft.fftn(self.matrix, axes=axes, norm='ortho'), axes=axes)

        # ... or transforming from frequency domain to spatial domain
        elif transform_state is True:
            new_axesobjs = {
                i: Axis(self.axes[i].name.lstrip('k'),
                        self.axes[i].unit.lstrip('1/'))
                for i in axes
            }
            ret.matrix = fftnorm \
                * fft.ifftn(fft.ifftshift(self.matrix, axes=axes), axes=axes, norm='ortho')

        # Update axes objects
        for i in axes:
            # restore original axes origins
            if self.transformed_axes_origins[i]:
                new_axes[i] += self.transformed_axes_origins[i] - new_axes[i][0]

            # update axes objects
            new_axesobjs[i].grid = new_axes[i]
            ret.setaxisobj(i, new_axesobjs[i])

            # update transform state and record axes origins
            ret.axes_transform_state[i] = not transform_state
            ret.transformed_axes_origins[i] = new_origins[i]

        return ret

    def _apply_linear_phase(self, dx):
        '''
        Apply a linear phase as part of translating the grid points.

        dx should be a mapping from axis number to translation distance
        All axes must have same transform_state and transformed_axes_origins not None
        '''
        transform_state = self._transform_state(dx.keys())
        if transform_state is None:
            raise ValueError("Translation only allowed if all mentioned axes"
                             "are in same transform state")

        if any(self.transformed_axes_origins[i] is None for i in dx.keys()):
            raise ValueError("Translation only allowed if all mentioned axes"
                             "have transformed_axes_origins not None")

        axes = [ax.grid for ax in self.axes]  # each axis object returns new numpy array
        for i in range(len(axes)):
            gridlen = len(axes[i])
            if transform_state is True:
                # center the axes around 0 to eliminate global phase
                axes[i] -= axes[i][gridlen//2]
            else:
                # start the axes at 0 to eliminate global phase
                axes[i] -= axes[i][0]

        # build mesh
        mesh = np.meshgrid(*axes, indexing='ij', sparse=True)

        # calculate linear phase
        arg = sum([dx[i]*mesh[i] for i in dx.keys()])

        # apply linear phase with correct sign and global phase
        ret = copy.copy(self)
        if transform_state is True:
            ret.matrix = self.matrix * np.exp(1.j * arg)
        else:
            ret.matrix = self.matrix * np.exp(-1.j * arg)

        for i in dx.keys():
            ret.transformed_axes_origins[i] += dx[i]

        return ret

    def shift_grid_by(self, dx, interpolation='fourier'):
        '''
        Translate the Grid by dx.
        This is useful to remove the grid stagger of field components.

        If all axis will be shifted, dx may be a list.
        Otherwise dx should be a mapping from axis to translation distance.

        The keyword-argument interpolation indicates the method to be used and
        may be one of ['linear', 'fourier'].
        In case of interpolation = 'fourier' all axes must have same transform_state.
        '''
        if interpolation not in ['fourier', 'linear']:
            raise ValueError("Requested method {} is not supported".format(method))

        if not isinstance(dx, collections.Mapping):
            dx = dict(enumerate(dx))

        dx = {helper.axesidentify[i]: v for i, v in dx.items()}
        axes = sorted(dx.keys())

        if interpolation == 'fourier':
            ret = self.fft(axes)
            ret = ret._apply_linear_phase(dx)
            ret = ret.fft(axes)

        if interpolation == 'linear':
            gridspacing = np.array([ax.spacing for ax in self.axes])
            shift = np.zeros(len(self.axes))
            for i, d in dx.items():
                shift[i] = d
            shift_px = shift/gridspacing
            ret = copy.copy(self)
            if np.isrealobj(self.matrix):
                ret.matrix = spnd.shift(self.matrix, -shift_px, order=1, mode='nearest')
            else:
                real, imag = self.matrix.real.copy(), self.matrix.imag.copy()
                ret.matrix = np.empty_like(matrix)
                spnd.shift(real, -shift_px, output=ret.matrix.real, order=1, mode='nearest')
                spnd.shift(imag, -shift_px, output=ret.matrix.imag, order=1, mode='nearest')

            for i in axes:
                ret.axes[i].grid_node = self.axes[i].grid_node + dx[i]

        return ret

    def topolar(self, extent=None, shape=None, angleoffset=0):
        '''
        remaps the current kartesian coordinates to polar coordinates
        extent should be given as extent=(phimin, phimax, rmin, rmax)
        '''
        ret = copy.deepcopy(self)
        if extent is None:
            extent = [-np.pi, np.pi, 0, self.extent[1]]
        extent = np.asarray(extent)
        if shape is None:
            maxpt_r = np.min((np.floor(np.min(self.shape) / 2), 1000))
            shape = (1000, maxpt_r)

        extent[0:2] = extent[0:2] - angleoffset
        ret.matrix = helper.transfromxy2polar(self.matrix, self.extent,
                                              np.roll(extent, 2), shape).T
        extent[0:2] = extent[0:2] + angleoffset

        ret.extent = extent
        if ret.axes[0].name.startswith('$k_') \
           and ret.axes[1].name.startswith('$k_'):
            ret.axes[0].name = '$k_\phi$'
            ret.axes[1].name = '$|k|$'
        return ret

    def exporttocsv(self, filename):
        if self.dimensions == 1:
            data = np.asarray(self.matrix)
            x = np.linspace(self.extent[0], self.extent[1], len(data))
            np.savetxt(filename, np.transpose([x, data]), delimiter=' ')
        elif self.dimensions == 2:
            export = np.asarray(self.matrix)
            np.savetxt(filename, export)
        else:
            raise Exception('Not Implemented')
        return

    def __str__(self):
        return '<Feld "' + self.name + '" ' + str(self.shape) + '>'

    def _extent_to_slices(self, extent):
        if not self.dimensions * 2 == len(extent):
            raise TypeError('size of extent doesnt match self.dimensions * 2')

        extent = np.reshape(np.asarray(extent), (self.dimensions, 2))
        return [ax._extent_to_slice(ex) for ax, ex in zip(self.axes, extent)]

    def _normalize_slices(self, key):
        if not isinstance(key, collections.Iterable):
            key = (key,)
        if len(key) != self.dimensions:
            raise IndexError("{}D Field requires a {}-tuple of slices as index"
                             "".format(self.dimensions, self.dimensions))

        return [ax._normalize_slice(sl) for ax, sl in zip(self.axes, key)]

    # Operator overloading
    def __getitem__(self, key):
        key = self._normalize_slices(key)
        field = copy.copy(self)
        field._matrix = field.matrix[key]
        for i, sl in enumerate(key):
            field.setaxisobj(i, field.axes[i][sl])
        return field

    @_updatename('+')
    def __iadd__(self, other):
        self.matrix += np.asarray(other)
        return self

    def __add__(self, other):
        ret = copy.copy(self)
        ret.matrix = ret.matrix + np.asarray(other)
        return ret
    __radd__ = _updatename('+', reverse=True)(__add__)
    __add__ = _updatename('+', reverse=False)(__add__)

    def __neg__(self):
        ret = copy.copy(self)
        ret.matrix = -self.matrix
        ret.name = '-' + ret.name
        return ret

    @_updatename('-')
    def __isub__(self, other):
        self.matrix -= np.asarray(other)
        return self

    @_updatename('-')
    def __sub__(self, other):
        ret = copy.copy(self)
        ret.matrix = ret.matrix - np.asarray(other)
        return ret

    @_updatename('-', reverse=True)
    def __rsub__(self, other):
        ret = copy.copy(self)
        ret.matrix = np.asarray(other) - ret.matrix
        return ret

    @_updatename('^')
    def __pow__(self, other):
        ret = copy.copy(self)
        ret.matrix = self.matrix ** np.asarray(other)
        return ret

    @_updatename('^', reverse=True)
    def __rpow__(self, other):
        ret = copy.copy(self)
        ret.matrix = np.asarray(other) ** self.matrix
        return ret

    @_updatename('*')
    def __imul__(self, other):
        self.matrix *= np.asarray(other)
        return self

    def __mul__(self, other):
        ret = copy.copy(self)
        ret.matrix = ret.matrix * np.asarray(other)
        return ret
    __rmul__ = _updatename('*', reverse=True)(__mul__)
    __mul__ = _updatename('*', reverse=False)(__mul__)

    def __abs__(self):
        ret = copy.copy(self)
        ret.matrix = np.abs(ret.matrix)
        ret.name = '|{}|'.format(ret.name)
        return ret

    @_updatename('/')
    def __itruediv__(self, other):
        self.matrix /= np.asarray(other)
        return self

    @_updatename('/')
    def __truediv__(self, other):
        ret = copy.copy(self)
        ret.matrix = ret.matrix / np.asarray(other)
        return ret

    @_updatename('/', reverse=True)
    def __rtruediv__(self, other):
        ret = copy.copy(self)
        ret.matrix = np.asarray(other) / ret.matrix
        return ret

    # python 2
    __idiv__ = __itruediv__
    __div__ = __truediv__
