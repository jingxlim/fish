#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  Register, downsample, save dff as tif
#
# Davis Bennett
# davis.v.bennett@gmail.com
#
# License: MIT
#


def get_sc(app_name):
    from pyspark import SparkConf, SparkContext

    conf = SparkConf().setAppName(app_name)
    sc = SparkContext(conf=conf)
    return sc


def get_background_offset(raw_path):
    from numpy import median
    from glymur import jp2k

    background_im_fname = raw_path + 'Background_0.tif'
    background_im = jp2k.Jp2k(background_im_fname)[:]
    return median(background_im)


def prepare_images(files, context, median_filter_size, background_offset):
    from thunder import images as tdims
    from fish.util.fileio import read_image

    images = tdims.fromlist(files, accessor=read_image, engine=context)
    images = images.map(lambda v: (v - background_offset).clip(1, None))
    images = images.median_filter(size=median_filter_size)
    return images


def get_params(path):
    import json
    with open(path,'w') as f:
        params = json.load(f)
    return params


def motion_correction(images, reg_path, overwrite=False):
    from scipy.ndimage.interpolation import shift
    from os.path import exists
    from os import makedirs
    from skimage.io import imsave
    from fish.image.alignment import estimate_translation
    from numpy import save, array, zeros, vstack, load
    from scipy.ndimage.filters import median_filter

    ref_range = range((images.shape[0] // 2) - 5, (images.shape[0] // 2) + 5)
    medfilt_window = 200

    if not exists(reg_path):
        makedirs(reg_path)
        overwrite = True

    try:
        affs = load(reg_path + 'regparams_affine.npy')
        print('Registration params found')
    except FileNotFoundError:
        print('Registration params not found, performing registration')
        overwrite = True

    if overwrite:
        ref = images[ref_range].mean()
        imsave(reg_path + 'anat_reference.tif', ref)
        reg = images.map(lambda v: estimate_translation(ref.max(0), v.max(0))).toarray()
        affs = array([r.affine for r in reg])
        save(reg_path + 'regparams_affine.npy', affs)

    x_trans = median_filter(affs[:, -2, -1], size=medfilt_window)
    y_trans = median_filter(affs[:, 0, -1], size=medfilt_window)
    z_trans = zeros(x_trans.shape)
    trans = vstack([z_trans, y_trans, x_trans])
    shifter = lambda v: shift(v[1], -trans[:, v[0][0]], cval=0).astype('float32')
    images_transformed = images.map(shifter, with_keys=True)

    return images_transformed


def apply_dff(images, dff_fun, out_dtype):
    from numpy import array
    from skimage.exposure import rescale_intensity as rescale

    images_dff = images.map_as_series(dff_fun, value_size=images.shape[0], dtype=images.dtype)

    bounds = images_dff.map(lambda v: array([v.min(), v.max()])).toarray()
    mn, mx = bounds.min(), bounds.max()
    images_rescaled = images_dff.map(lambda v: rescale(v, in_range=(mn, mx), out_range=out_dtype).astype(out_dtype))
    dff_lim = (mn, mx)
    return images_rescaled, dff_lim


def rdd_to_tif(kv, path):
    from skimage.io import imsave
    key = kv[0][0]
    val = kv[1]
    fname = 't_{:06d}.tif'.format(key)
    imsave(path + fname, val, compress=1)


def save_images(images, out_path, multifile, exp_name):
    # save the images
    if multifile:
        images.resc.tordd().foreach(lambda v: rdd_to_tif(v, out_path))
    else:
        from skimage.io import imsave
        imsave(out_path + exp_name + '.tif', images.toarray(), compress=1)


def main():
    from argparse import ArgumentParser
    from fish.image.zds import ZDS
    from fish.image.vol import dff
    from skimage.transform import downscale_local_mean
    from functools import partial
    import json
    from os.path import exists
    from os import makedirs

    parser = ArgumentParser(description='Generate a df/f volume from raw light sheet data, and save as .tif files.')
    parser.add_argument('-raw', help='A directory of raw files.')
    parser.add_argument('-params', help='A path to a json file containing dff params.')
    parser.add_argument('-out', help='Directory to contain output.')
    args = parser.parse_args()

    dset = ZDS(args.raw)
    params = get_params(args.params)

    if not exists(args.out):
        makedirs(args.out)

    reg_path = args.out + 'reg/'

    sc = get_sc('dff_movie')
    dff_fun = partial(dff, window=params['baseline_window'] * dset.metadata['volume_rate'],
                      percentile=params['baseline_percentile'],
                      baseline_offset=params['baseline_offset'],
                      downsample=params['baseline_downsampling'])

    ims = prepare_images(dset.files, sc)
    ims_registered = motion_correction(ims, reg_path, overwrite=params['overwrite_registration'])
    ims_ds = ims_registered.map(lambda v: downscale_local_mean(v, params['spatial_downsampling']))
    ims_dff, dff_lim = apply_dff(ims_ds, dff_fun, params['out_dtype'])

    save_images(ims_dff, args.out, multifile=False, exp_name=dset.exp_name)

    metadata = params.copy()
    metadata['dff_lims'] = [float(dff_lim[0]), float(dff_lim[1])]
    metadata_fname = args.out + 'metadata.json'
    with open(metadata_fname, 'w') as fp:
        json.dump(metadata, fp)

if __name__ == '__main__':
    main()


