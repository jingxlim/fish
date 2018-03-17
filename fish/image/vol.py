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


def get_metadata(param_file):
    """
    Parse imaging metadata file, returning a dictionary of imaging parameters

    param_file : str, .xml file containing metadata
    """

    import xml.etree.ElementTree as ET
    from lxml import etree
    from numpy import array

    parser = etree.XMLParser(recover=True)

    exp_dict = {}
    root = ET.parse(param_file, parser=parser).getroot()

    for r in root.findall('info'):
        exp_dict[r.keys()[0]] = r.items()[0][1]

    # convert dimensions from a string formatted 'X_sizexY_sizexZsize' to a numpy array
    if type(exp_dict['dimensions']) is str:
        exp_dict['dimensions'] = array(exp_dict['dimensions'].split('x')).astype('int')

    # convert z step from string to float
    if type(exp_dict['z_step']) is str:
        exp_dict['z_step'] = float(exp_dict['z_step'])

    return exp_dict


def get_stack_dims(inDir):
    """
    :param inDir: a string representing a path to a directory containing metadata
    :return: dims, a list of integers representing the xyz dimensions of the data
    """
    import xml.etree.ElementTree as ET
    from lxml import etree
    from os.path import split

    parser = etree.XMLParser(recover=True)
    
    channel = 0
    if split(split(inDir)[0])[1] == 'CHN01':
        channel = 1

    dims = ET.parse(inDir + 'ch' + str(channel) + '.xml', parser=parser)
    root = dims.getroot()

    for info in root.findall('info'):
        if info.get('dimensions'):
            dims = info.get('dimensions')

    dims = dims.split('x')
    dims = [int(float(num)) for num in dims]

    return dims


def get_stack_freq(inDir):
    """
    Get the temporal data from the Stack_frequency.txt file found in
    directory inDir. Return volumetric sampling rate in Hz,
    total recording length in S, and total number
    of planes in a tuple.
    """
    f = open(inDir + 'Stack_frequency.txt')
    times = [float(line) for line in f]

    # third value should be an integer
    times[2] = int(times[2])

    return times


def rearrange_bidirectional_stack(stack_data):
    """
    Re-arrange the z planes in data that were acquired bidirectionally. Convert from temporal order to spatial order.
    For stacks with an even number of planes, the odd-numbered planes are acquired first, and vice versa.
    For example, a stack with 8 total planes with be acquired in this order: 1, 3, 5. 7, 6, 4, 2, 0

    stack_data: 3-dimensional numpy array

    returns a 3-dimensional numpy array with the same values as stack_data but re-arranged.
    """

    from numpy import zeros, ceil
    z = stack_data.shape[0]
    midpoint = int(ceil(z / 2))
    z_range_old = range(z)
    z_range_new = zeros(z, dtype='int')

    if (z % 2) == 0:
        z_range_new[1::2] = z_range_old[:midpoint]
        z_range_new[0::2] = z_range_old[midpoint:][::-1]
        return stack_data[z_range_new]
    else:
        z_range_new[0::2] = z_range_old[:midpoint]
        z_range_new[1::2] = z_range_old[midpoint:][::-1]
        return stack_data[z_range_new]


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


def montage_projection(im_dir, trange=None, context=None):
    """
    Generate a montage of x projections.

    im_dir : str, path to directory containing [x,y,z] data saved as tif
    
    trange : object which can be used for linear indexing, set of timepoints to use

    context : spark context object for parallelization
    """
    import thunder as td
    from glob import glob
    from skimage.util.montage import montage2d
    from skimage.exposure import rescale_intensity as rescale
    import numpy as np
    from pyklb import readfull

    exp_name = im_dir.split('/')[-2]

    print('Exp name: {0}'.format(exp_name))

    fnames = glob(im_dir + 'TM*.klb')
    fnames.sort()

    def klb_loader(v):
        return pyklb.readfull(v)

    ims = td.images.fromlist(fnames, accessor=klb_loader, engine=context)

    print('Experiment dims: {0}'.format(ims.shape))
    
    if trange is None:
        trange = np.arange(ims.shape[0])
    
    ims_cropped = ims[trange].median_filter([1, 3, 3])
    dims = ims_cropped.dims

    #todo: apply registration if available

    from scipy.ndimage import percentile_filter
    float_dtype = 'float32'
    
    def my_dff(y, perc, window): 
        baseFunc = lambda x: percentile_filter(x.astype(float_dtype), perc, window, mode='reflect')
        b = baseFunc(y)
        return ((y - b) / (b + .1))

    dff_fun = lambda v: my_dff(v, 15, 800) 
    chop = 16

    reshape_fun = lambda v: v.reshape(dims[0], dims[1], chop, dims[2] // chop)
    montage_fun = lambda v: montage2d(v.T).T

    def im_fun(v):
        return montage_fun(reshape_fun(v).max(3))
    
    out_dtype = 'uint16'
    
    montage_ims = ims_cropped.map_as_series(dff_fun, value_size=ims_cropped.shape[0], dtype=float_dtype, chunk_size='35').map(im_fun)
    dff_lim = montage_ims.map(lambda v: [v.max(), v.min()]).toarray()
    rescale_fun = lambda v: rescale(v, in_range=(dff_lim.min(), dff_lim.max()), out_range=out_dtype).astype(out_dtype)

    montage_rescaled = montage_ims.map(rescale_fun).toarray()[:,-1::-1,:]
    return montage_rescaled
