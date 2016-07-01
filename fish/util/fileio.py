def dirNest(path):
    """
    :param path: string, path to some directory
    :return: dn: list of 2-tuples of strings, the result of recursively splitting the directory structure in path
    """
    from os.path import split, sep
    dn = []
    while path is not sep:
        tmp = split(path)
        path = tmp[0]
        dn.append(tmp)
    return dn[-1::-1]


def dirStructure(rawDir, outDirName='proc'):
    """
    :param rawDir: string, path to raw data
    :param outDirName: string, name of home dir for output
    :return: regDir, serDir, matDir: strings, paths for saved data
    """
    from os.path import join
    dn = dirNest(rawDir)

    expName = dn[-2][1]

    # Check whether this is a multicolor experiment
    if expName[0:2] == 'CH':
        expName = dn[-3][1]
        expDir = dn[-4][1]
        chDir = dn[-2][1]
        baseDir = dn[-5][0]

        outDir = join(baseDir, outDirName, expDir, expName, chDir, '')

    else:
        expDir = dn[-3][1]
        baseDir = dn[-4][0]
        outDir = join(baseDir, outDirName, expDir, expName, '')

    return outDir


def image_conversion(source_path, dest_fmt, wipe=False):
    """
    Convert uint16 image from .stack or .tif format to .klb/hdf5 format, optionally erasing the source image

    image_path : string
        Path to image to be converted.
    wipe : bool
        If True, delete the source image after successful conversion

    """

    from numpy import array_equal
    from os import remove

    source_name = source_path.split('.')[0]
    source_fmt = source_path.split('.')[-1]
    dest_path = source_name + '.' + dest_fmt

    def stack_loader(stack_path):
        import fish.image.vol as volt
        from numpy import fromfile
        from os.path import sep, split
        dims = volt.getStackDims(split(stack_path)[0] + sep)
        im = fromfile(stack_path, dtype='int16')
        im = im.reshape(dims[-1::-1])
        return im

    def tif_loader(tif_path):
        from skimage.io import imread
        return imread(tif_path)

    def klb_writer(data, klb_path):
        from pyklb import writefull
        writefull(data, klb_path)

    def klb_reader(klb_path):
        from pyklb import readfull
        return readfull(klb_path)

    def h5_writer(data, h5_path):
        from h5py import File
        from os.path import exists

        if exists(h5_path):
            remove(h5_path)

        f = File(h5_path, 'w')
        f.create_dataset('default', data=data, compression='gzip', chunks=True, shuffle=True)
        f.close()

    def h5_reader(h5_path):
        from h5py import File
        f = File(h5_path, 'r')
        return f['default'].value

    if source_fmt == 'stack':
        source_loader = stack_loader

    elif source_fmt == 'tif':
        source_loader = tif_loader

    if dest_fmt == 'klb':
        dest_writer = klb_writer
        dest_reader = klb_reader

    elif dest_fmt == 'h5':
        dest_writer = h5_writer
        dest_reader = h5_reader

    source_image = source_loader(source_path)
    dest_writer(source_image, dest_path)

    if wipe:
        check_image = dest_reader(dest_path)
        if array_equal(check_image, source_image):
            remove(source_path)
        else:
            print('{0} and {1} differ... something went wrong!'.format(source_path, dest_path))