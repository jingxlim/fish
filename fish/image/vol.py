#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  Tools for analyzing light sheet microscopy data
#
# Davis Bennett
# davis.v.bennett@gmail.com
#
# License: MIT
#


def local_corr(images, offset=[0,1,1]):
    """
    Correlate each image in a distributed set of images with a shifted copy of itself. Returns an rdd of
    correlation coefficients.

    images : thunder.images object
    offset : the shift, in pixels, to apply to each image before correlation

    """
    from scipy.ndimage.interpolation import shift
    
    def correlate_signals(s1, s2):
        from numpy import corrcoef
        return corrcoef(s1, s2)[0][1]
    
    images_shifted = images.map(lambda v: shift(v.astype('float32'), offset, mode='reflect')).astype('float16')
    joined = images.toseries().tordd().join(images_shifted.toseries().tordd())
    
    return joined.mapValues(lambda v: correlate_signals(v[0], v[1]))


def baseline(data, window, percentile, downsample=1, axis=-1):
    """
    Get the baseline of a numpy array using a windowed percentile filter with optional downsampling

    data : Numpy array
        Data from which baseline is calculated

    window : int
        Window size for baseline estimation. If downsampling is used, window shrinks proportionally

    percentile : int
        Percentile of data used as baseline

    downsample : int
        Rate of downsampling used before estimating baseline. Defaults to 1 (no downsampling).

    axis : int
        For ndarrays, this specifies the axis to estimate baseline along. Default is -1.

    """
    from scipy.ndimage.filters import percentile_filter
    from scipy.interpolate import interp1d
    from numpy import ones

    size = ones(data.ndim, dtype='int')
    size[axis] *= window//downsample

    slices = [slice(None)] * data.ndim
    slices[axis] = slice(0, None, downsample)

    if downsample == 1:
        bl = percentile_filter(data, percentile=percentile, size=size)

    else:
        data_ds = data[slices]
        baseline_ds = percentile_filter(data_ds, percentile=percentile, size=size)
        interper = interp1d(range(0, data.shape[axis], downsample), baseline_ds, axis=axis, fill_value='extrapolate')
        bl = interper(range(data.shape[axis]))

    return bl


def dff(data, window, percentile, baseline_offset, downsample=1, axis=-1):
    """
    Estimate normalized change in fluorescence (dff) with the option to estimate baseline on downsampled data.
    Returns a vector with the same size as the input.

    If downsampling is required, the input data will be downsampled before baseline
    is estimated with a percentile filter. The baseline is then linearly interpolated to match the size of data.

    data : Numpy array
        Data to be processed

    window : int
        Window size for baseline estimation. If downsampling is used, window will shrink proportionally

    percentile : int
        Percentile of data used as baseline

    baseline_offset : float or int
        Value added to baseline before normalization, to prevent division-by-zero issues.

    downsample : int
        Rate of downsampling used before estimating baseline. Defaults to 1 (no downsampling).

    axis : int
        For ndarrays, this specifies the axis to estimate baseline along. Default is -1.
    """

    bl = baseline(data, window, percentile, downsample=downsample, axis=axis)
    return (data - bl) / (bl + baseline_offset)


def filter_flat(vol, mask):
    """
    Flatten an array and return a list of the elements at positions where the binary mask is True.

    vol : ndarray
    mask : binary ndarray or function. If a function, mask must take an ndarray as an argument and return a
    binary mask.
    """
    vol_flat = vol.ravel()

    # if mask is a function, call it on vol to make the mask
    if hasattr(mask, '__call__'):
        mask_flat = mask(vol).ravel()
    else:
        mask_flat = mask.ravel()

    return vol_flat[mask_flat]


def unfilter_flat(vec, mask):
    """
    Reverse the effect of filter_flat by taking a 1d ndarray and assigning each value to a position in an ndarray

    vec : 1-dimensional ndarray
    mask : binary ndarray
    """

    from numpy import zeros
    """
    Fill a binary mask with the values in vec
    """
    mask_flat = mask.ravel()
    vol = zeros(mask.shape).ravel()
    vol[mask_flat == True] = vec

    return vol.reshape(mask.shape)


def kvp_to_array(dims, data, ind=0, baseline=0):
    """ Convert a list of key-value pairs to a volume.

    :param dims: dimensions of the volume to fill with values
    :param data: list of iterables with 2 values, 2-tuples or 2-item lists.
    :param ind: if the value in each key-value pair is itself an iterable, ind specifies which element to use
    :param baseline: fill value for empty spots in the volume
    :return: vol, an ndarray
    """
    from numpy import zeros, array

    vol = zeros(dims, dtype=data[0][1].dtype) + array(baseline).astype(data[0][1].dtype)

    for k, v in data:
        # check if data contains a single value or an iterable
        if hasattr(v, '__iter__'):
            vol[k] = v[ind]
        else:
            vol[k] = v
    return vol


def sub_proj(im, ax, func, chop=16):
    """
    Project a volume in chunks along an axis.

    im : numpy array, data to be projected

    ax : int, axis to project along

    func : function that takes an axis as an argument, e.g. np.max

    chop : int, number of projections to generate

    """
    from numpy import rollaxis

    extra = im.shape[ax] % chop
    montage_dims = list(im.shape)
    montage_dims[ax] //= chop
    montage_dims.insert(ax, chop)

    slices_crop = [slice(None) for x in im.shape]
    slices_crop[ax] = slice(0, extra + 1, 1)

    # remove trailing data by projecting it down to a single plane
    im[slices_crop] = im[slices_crop].max(ax, keepdims=True)

    slices_keep = [slice(None) for x in im.shape]
    slices_keep[ax] = slice(extra, None)

    im_proj = func(im[slices_keep].reshape(montage_dims), axis=ax + 1)
    # stick the axis of projections in the front
    im_proj = rollaxis(im_proj, ax, 0)

    return im_proj


def redim(array, ndim, shape=None):
    """
    Add or remove trailing dimensions from an array by reshaping. Useful for turning N-dimensional data into the 2D
    shape required for matrix factorization / clustering, and for reversing this transformation. Returns a view of
    the input array.

    array : numpy array with 2 or more dimensions.

    ndim : int, desired number of dimensions when contracting dimensions.

    shape : tuple, desired shape when expanding dimensions.

    """

    from numpy import prod

    result = None
    if (ndim > array.ndim) and (shape is None):
        raise ValueError('Cannot expand dimensions without supplying a shape argument')

    if ndim < array.ndim:
        new_shape = (*array.shape[:(ndim - 1)], prod(array.shape[(ndim - 1):]))
        result = array.reshape(new_shape)

    elif ndim > array.ndim:
        new_shape = shape
        result = array.reshape(new_shape)

    elif ndim == array.ndim:
        new_shape = array.shape
        result = array.reshape(new_shape)

    return result


class InterpArray:

    def __init__(self, x, y, full_shape):
        """
        Create an array of numeric values representing a downsampled version of a larger array. This object is
        initialized with x and y values which define downsampled data used for interpolation and the points those
        values correspond to in the dimensions of the full, original array. Indexing this object with an index that is
        not an element of y returns values interpolated from x. Indexing is only supported on the first axis.

        x: numpy or dask array. Length of the first axis must match length of y

        y: list or numpy array of sorted integers matching the length of x. These values represent the indices at which
        the values of x (along its first axis) were sampled.

        full_shape: the full shape of the data that generated x. If x was generated by some larger numpy array z,
        then x == z[y], and full_shape == z.shape

        """
        from numpy import array
        # not exposing this to init yet
        axis = 0
        self.x = x
        self.full_shape = full_shape
        self.y = array(y)
        self.interpolation_axis = axis

    def __repr__(self):
        return f'An array with size {self.full_shape} sampled at {self.y}'

    def _get_interpolated_value(self, idx):
        from numpy import where, diff, array

        dists = self.y - idx
        ds_ind_pre = where(dists >= 0)[0][0] - 1

        if ds_ind_pre == -1:
            return self.x[0]

        interval = diff(self.y)[ds_ind_pre]
        coeffs = array([interval - abs(dists[ds_ind_pre]), abs(dists[ds_ind_pre])])

        coeffs = coeffs / interval

        bl_ = self.x[ds_ind_pre:ds_ind_pre + 2, ]

        result = coeffs[0] * bl_[0] + coeffs[1] * bl_[1]

        return result

    def __getitem__(self, idx):
        # only linear interpolation for now
        from numpy import array, arange
        from dask.array import stack
        from dask.array.core import Array as DaskArray
        from numpy import ndarray as NPArray

        if not isinstance(idx, tuple):
            # not the best way to de-slicify, but the simplest to code
            if isinstance(idx, slice):
                idx = arange(self.full_shape[self.interpolation_axis])[idx]
            idx = (idx,)

        if len(idx) == 1:
            try:
                result = [self._get_interpolated_value(idx_) for idx_ in idx[0]]
                if isinstance(self.x, NPArray):
                    result = array(result)
                elif isinstance(self.x, DaskArray):
                    result = stack(result)
            except TypeError:
                result = self._get_interpolated_value(idx[0])
        else:
            raise TypeError('Only 1D indexing supported at the moment')

        return result
