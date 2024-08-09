# SpotFinder
#
# Centroidig code for analyzing FITS files. Code is derived from various code elemets used during
# assembly and testing of DESI fiber positioners at UM in 2016-2019.
#
# Authors:
#   M. Schubnell, University of Michigan
#   J. Silber, LBNL
#   K. Fanning, University of Michigan
# 
# 
# Application example:
# 
# $ python3 
# > import spotfinder; 
# > sf = spotfinder.SpotFinder('lbl_petal1.fits',nspots=450) # fits file and the number of expected spots (nspots) is required; 
#                                                            # this number can be larger than the true number of spots
# > sf.set_region_file('regions.reg')                        # specify a region file (optional)
# > sf.set_parameter('fitbox_size', int value)               # specify a box size which should be slightly larger than 
#                                                            # the spots (optional, defaults to 7)
# > sf.set_parameter('verbose',bool value)                   # specify verbose mode (True or False, optional, defaults to False)
# > centroids = sf.get_centroids()
#
#
#
#
# --------------------------------------------------------------------------------------------          
import os

import mahotas as mh
import numpy as np
from astropy.io import fits
from numpy import sqrt, exp, ravel, arange
from pylab import indices
from scipy import optimize
from scipy.ndimage import center_of_mass

# Version history
# 0.3  aug 06 2024  ms   made code executable; added command line parser
# 0.2  mar 26 2022  ms   minor bug fixes; added comments
# 0.1  mar 25 2022  ms   created spotfinder class and collected various files used during 
#                        UM xytest into a single file
#
VERSION = 0.3

# TODO: why are the centroids off center to the upper right? is it bc a single pixel is too high compared to the
# surrounding pixels? Could applying a gaussian blur filter first be a solution?


# function is never used?
def gauss(x, *p):
    A, mu, sigma = p
    return A * exp(-(x - mu) ** 2 / (2. * sigma ** 2))


def gaussian(bias, height, center_x, center_y, width_x, width_y):
    """Returns a gaussian function with the given parameters"""
    width_x = float(width_x)
    width_y = float(width_y)
    return lambda x, y: bias + height * exp(-(((center_x - x) / width_x) ** 2 + ((center_y - y) / width_y) ** 2) / 2)


def moments(data):
    # Returns (height, x, y, width_x, width_y) the gaussian parameters
    # of a 2D distribution by calculating its moments
    bias = np.min(data)
    data_this = data - bias
    total = data_this.sum()
    X, Y = indices(data.shape)
    x = (X * data_this).sum() / total
    y = (Y * data_this).sum() / total
    col = data_this[:, int(y)]
    width_x = sqrt(abs((arange(col.size) - y) ** 2 * col).sum() / col.sum())
    row = data_this[int(x), :]
    width_y = sqrt(abs((arange(row.size) - x) ** 2 * row).sum() / row.sum())
    height = data_this.max()
    return bias, height, x, y, width_x, width_y


def fitgaussian(data):
    """Returns (bias, height, x, y, width_x, width_y)
    the gaussian parameters of a 2D distribution found by a fit"""
    params = moments(data)
    errorfunction = lambda p: ravel(gaussian(*p)(*indices(data.shape)) - data)
    p, success = optimize.leastsq(errorfunction, params)
    return p


def remove_hot_pixels(image, nsigma=5):
    """
    Remove isolated hot pixels in the image. The mean value of the original image is
    calculated and a mean + nsigma threshold cut is applied. Hot pixels receive a new value of
    the average of their 4 next neighbors.
    """
    im_mean = np.mean(image)
    im_sig = np.std(image)
    hot_thresh = im_mean + nsigma * im_sig

    hp_img = np.copy(image)
    hp_img = hp_img.astype(np.uint32)
    low_values_indices = hp_img < hot_thresh  # Where values are low

    hp_img[low_values_indices] = 0
    ind = zip(*np.where(hp_img > hot_thresh))
    xlimit = len(hp_img[0])
    ylimit = len(hp_img)

    for i in ind:
        if i[0] == 0 or i[0] == ylimit - 1 or i[1] == 0 or i[1] == xlimit - 1:
            print('Edge hot spot')
            image[i[0], i[1]] = np.median(image)
        else:
            neighborsum = hp_img[i[0] + 1, i[1]] + hp_img[i[0] - 1, i[1]] + hp_img[i[0], i[1] - 1] + hp_img[
                i[0], i[1] + 1]
            if neighborsum == 0:
                image[i[0], i[1]] = (image[i[0] + 1, i[1]] + image[i[0] - 1, i[1]] + image[i[0], i[1] - 1] + image[
                    i[0], i[1] + 1]) / 4.
    del hp_img
    return image


def centroid(im, mask=None, w=None, x=None, y=None):
    """
    Compute the centroid of an image with a specified binary mask projected upon it.

    INPUT:
      im -- image array
      mask -- binary mask, 0 in ignored regions and 1 in desired regions
      w is typically 1.0/u**2, where u is the uncertainty on im
      x,y are those generated by meshgrid.

    OUTPUT:
      (x0,y0) tuple of centroid location
    """
    from numpy import ones, arange, meshgrid
    if mask is None:
        mask = ones(im.shape)
    if not (im.shape == mask.shape):
        print("Image, mask, and weights must have same shape! Exiting.")
        return -1
    if x == None or y == None:
        xx = arange(im.shape[1])
        yy = arange(im.shape[0])
        x, y = meshgrid(xx, yy)
    if w == None:
        zz = im * mask
    else:
        zz = im * mask * w
    z = zz.sum()
    x0 = (x * zz).sum() / z
    y0 = (y * zz).sum() / z
    return (x0, y0)


def mfind(array, label):
    a = np.where(array == label)
    return a


def sort(A):
    # definition of sort which sorts the column of a matrix
    # input : array like
    # output : [B,I] with B the sorted matrix and I the index matrix
    B = np.zeros(A.shape)
    I = np.zeros(A.shape)
    for i in range(0, A.shape[1]):
        B[:, i] = np.sort(A[:, i])
        I[:, i] = sorted(range(A.shape[0]), key=lambda v: A[v, i])
    return [B, I]


def im2bw(image, level):
    # M.Schubnell - faking the matlab im2bw function
    s = np.shape(image)
    bw = np.zeros(s, dtype=int)
    threshold_indices = image > level
    bw[threshold_indices] = 1
    return bw


def multiCens(img, n_centroids_to_keep=2, verbose=False, write_fits=True, no_otsu=True, save_dir='', size_fitbox=10):
    # Computes centroids by finding spots and then fitting 2d gaussian
    #
    # Input 
    #       img: image as numpy array
    #       V: verbose mode
    #       regarding size_fitbox: it's a gaussian fitter box, this value is 1/2 length of side in pixels,
    #                              i.e. the box dimensions are 2*size_fitbox X 2*size_fitbox
    #
    # Output:
    #       returning the centroids and FWHMs as lists (xcen,ycen,fwhm)

    img[img < 0] = 0

    img = remove_hot_pixels(img, 7)

    img = img.astype(np.uint16)
    # QUESTION: why 0.1? how does adjusting this value affect output?
    level_fraction_of_peak = 0.1
    level_frac = int(level_fraction_of_peak * np.max(np.max(img)))
    if no_otsu:
        level = level_frac
    else:
        level_otsu = mh.thresholding.otsu(img)
        level = max(level_otsu, level_frac)
    bw = im2bw(img, level)

    if write_fits:
        filename = save_dir + 'binary_image.FITS'
        try:
            os.remove(filename)
        except:
            pass
        hdu = fits.PrimaryHDU(bw)
        hdu.writeto(filename)
    else:
        filename = []
    labeled, nr_objects = mh.label(bw)
    sizes = mh.labeled.labeled_size(
        labeled)  # size[0] is the background size, sizes[1 and greater] are number of pixels in each region
    sorted_sizes_indexes = np.argsort(sizes)[::-1]  # return in descending order
    print(sorted_sizes_indexes)
    good_spot_indexes = sorted_sizes_indexes[
                        1:n_centroids_to_keep + 1]  # avoiding the background regions entry at the beginning

    # In rare cases of having many bright spots and just a small # of dimmer (but still
    # usable) spots, then the otsu level is too high. In that case, we can retry, forcing
    # the more simplistic level_frac.
    if len(good_spot_indexes) < n_centroids_to_keep and not (no_otsu):
        print('Retrying centroiding using fractional level (' + str(
            level_fraction_of_peak) + ' * peak) instead of otsu method')
        return multiCens(img, n_centroids_to_keep, verbose, write_fits, no_otsu=True)

    # now loop over the found spots and calculate rough centroids        
    FWHMSub = []
    xCenSub = []
    yCenSub = []
    peaks = []
    max_sample_files_to_save = 20

    centers = center_of_mass(labeled, labels=labeled, index=[good_spot_indexes])
    print('centers', centers)
    nbox = size_fitbox
    for i, x in enumerate(centers):
        x = x[0]
        px = int(round(x[1]))
        py = int(round(x[0]))
        data = img[py - nbox:py + nbox, px - nbox:px + nbox]
        params = fitgaussian(data)
        fwhm = abs(2.355 * max(params[4], params[5]))
        # QUESTION: why threshold of .5?
        if fwhm < .5:
            print(" fit failed - trying again with smaller fitbox")
            sbox = nbox - 1
            data = img[py - sbox:py + sbox, px - sbox:px + sbox]
            params = fitgaussian(data)
            fwhm = abs(2.355 * max(params[4], params[5]))
        # xCenSub.append(float(px) - float(nbox) + params[3])
        # yCenSub.append(float(py) - float(nbox) + params[2])
        # px, py has already been truncated, use original float values from x instead
        xCenSub.append(x[1] - float(nbox) + params[3])
        yCenSub.append(x[0] - float(nbox) + params[2])
        FWHMSub.append(fwhm)

        peak = params[1]
        peaks.append(peak)
        # should_save_sample_image = False
        if peak < 0 or peak > 2 ** 16 - 1:
            print('peak = ' + str(peak) + ' brightness appears out of expected range')
        #    should_save_sample_image = True
        # QUESTION: why threshold of 1?
        if FWHMSub[-1] < 1:
            print('fwhm = ' + str(FWHMSub[-1]) + ' appears invalid, check if fitbox size (' + str(
                size_fitbox) + ') is appropriate and dots are sufficiently illuminated')

    return xCenSub, yCenSub, peaks, FWHMSub


def magnitude(p, b):
    m = 25.0 - 2.5 * np.log10(p - b)
    return m


# Function to check the distance between two points
def is_too_close(point1, point2, threshold):
    return abs(point1[0] - point2[0]) < threshold and abs(point1[1] - point2[1]) < threshold


# Function to filter points
def filter_points(points, threshold):
    filtered_points = []
    for point in points:
        too_close = any(is_too_close(point, fp, threshold) for fp in filtered_points)
        # TODO: if too_close, try with smaller fitbox
        if not too_close:
            filtered_points.append(point)
    return filtered_points


class SpotFinder():
    def __init__(self, fits_file=None, nspots=1, verbose=False):
        self.version = 0.3
        self.verbose = verbose
        self.nspots = nspots
        self.max_counts = 2 ** 16 - 1  # SBIC camera ADU max
        self.min_energy = 0.3 * 1.0  # this is the minimum allowed value for the product peak*fwhm for any given dot
        self.fboxsize = 7
        self.fits_name = fits_file
        self.region_file = None
        self.img = None
        if fits_file:
            fits_file = fits.open(fits_file)
            self.img = fits_file[0].data

    def set_parameter(self, parameter, value):
        try:
            parameter = str(parameter).lower()
            print('paramater', parameter)
            if parameter not in ['max_counts', 'min_energy', 'fitbox_size', 'verbose']:
                return 'ERROR: not a valid parameter'
            if parameter in ['max_counts']:
                self.max_counts = value
            if parameter in ['min_energy']:
                self.min_energy = value
            if parameter in ['fitbox_size']:
                self.fboxsize = int(value)
            if parameter in ['verbose']:
                self.verbose = value
            return 'SUCCESS'
        except:
            return 'FAILED'

    def set_region_file(self, region_file='regions.reg'):
        print(region_file)
        self.region_file = region_file
        return 'SUCCESS'

    def set_fits_file(self, fits_file=None):
        if not fits_file:
            return 'FAILED: fits file is required'
        f = fits.open(fits_file)
        self.img = f[0].data
        return 'SUCCESS: new fits file ' + str(fits_file)

    def get_centroids(self, print_summary=False):
        if isinstance(self.img, bool):
            if not self.img:
                return 'FAILED: fits file required'

        self.print_summary = print_summary
        # if not isinstance(region_file, bool):
        #    self.region_file = region_file
        try:
            xCenSub, yCenSub, peaks, FWHMSub = multiCens(self.img, n_centroids_to_keep=self.nspots,
                                                         verbose=self.verbose, write_fits=False, no_otsu=True,
                                                         size_fitbox=self.fboxsize)
            # we are calculating the quantity 'FWHM*peak' with peak normalized to the maximum peak level. 
            # This is esentially a linear light density. We will call this quantity 'energy' to match 
            # Joe's naming in fvchandler.
            # We verified that the linear light density is insensitive to spot position whereas the 
            # measured peak is not.
            energy = [FWHMSub[i] * (peaks[i] / self.max_counts) for i in range(len(peaks))]

            sindex = sorted(range(len(peaks)), key=lambda k: -peaks[k])
            peaks_sorted = [peaks[i] for i in sindex]
            x_sorted = [xCenSub[i] for i in sindex]
            y_sorted = [yCenSub[i] for i in sindex]
            fwhm_sorted = [FWHMSub[i] for i in sindex]
            energy_sorted = [energy[i] for i in sindex]

            centroids = {'peaks': peaks_sorted, 'x': x_sorted, 'y': y_sorted, 'fwhm': fwhm_sorted,
                         'energy': energy_sorted}
        except:
            centroids = None
        finally:

            # filter 
            points = []
            for i, x in enumerate(x_sorted):
                points.append((x + 1, y_sorted[i] + 1, fwhm_sorted[i], peaks_sorted[i], energy_sorted[i], i))
            filtered_points = filter_points(points, self.fboxsize)

            if self.print_summary:
                print(" File: " + str(self.fits_name))
                print(" Number of centroids requested: " + str(self.nspots))
                print(" Fitboxsize: " + str(self.fboxsize))
                print(" Centroid list:")
                print(" Spot  x          y         FWHM    Peak         LD  ")
                # for i, x in enumerate(x_sorted):
                #        use = True
                #        line=("{:5d} {:9.3f} {:9.3f} {:6.2f}  {:7.0f} {:7.2f} ".format(i, x+1, y_sorted[i]+1, 
                #                                fwhm_sorted[i], peaks_sorted[i], energy_sorted[i]))
                #        # don't use centroids with energy below threshold
                #        if energy_sorted[i] < self.min_energy:
                #                line=line+'*'
                #        use=

                if self.region_file:
                    with open(self.region_file, 'w') as fpointer:
                        fpointer.write('global color=magenta font="helvetica 13 normal"\n')

                i = 0
                for fp in filtered_points:
                    # QUESTION: why fwhm threshold of 1?
                    # if fp[2] > 1.:
                    if True:
                        print(f"{i:<5} {fp[0]:<10.3f} {fp[1]:<10.3f} {fp[2]:<5.2f} {fp[3]:<7} {fp[4]:<4.2f}")

                        if self.region_file:
                            with open(self.region_file, 'a') as fpointer:
                                fpointer.write(
                                    'circle ' + "{:9.3f} {:9.3f} {:7.3f} \n".format(fp[0] + 1, fp[1] + 1, fp[2] / 2.))
                                text = '"' + str(i) + '"'
                                fpointer.write('text ' + "{:9.3f} {:9.3f} {:s} \n".format(fp[0] + 6, fp[1] + 6, text))
                        i += 1

                print("\n Min peak   : {:8.2f} ".format(min(peaks_sorted)))
                print(" Max peak   : {:8.2f} ".format(max(peaks_sorted)))
                print(" Mean peak  : {:8.2f} ".format(np.mean(peaks_sorted)))
                print(" Sigma peak : {:8.2f} ".format(np.std(peaks_sorted)))

            # if self.region_file:
            #    with open(self.region_file,'w') as fp:
            #        fp.write('global color=magenta font="helvetica 13 normal"\n')
            #        for i, x in enumerate(x_sorted):
            #            r = fwhm_sorted[i]/2.
            #            fp.write('circle '+ "{:9.3f} {:9.3f} {:7.3f} \n".format(x+1, y_sorted[i]+1, r))
            #            text='"'+str(i)+'"'
            #            fp.write('text '+ "{:9.3f} {:9.3f} {:s} \n".format(x+6, y_sorted[i]+6, text))
        return centroids


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    # Add arguments
    parser.add_argument('--ncentroids', '-n', type=int, nargs='?', default=1,
                        help='Number of centroids expected (default: 1)')
    parser.add_argument('--fitsfile', '-f', type=str, nargs='?', required=True,
                        help='FITS filename (default: sbig_image.fits)')
    parser.add_argument('--fitbox_size', '-fs', type=int, nargs='?', default=7, help='Fitbox size (default: 7)')

    # Parse arguments
    args = parser.parse_args()

    # Retrieve values from args
    nspots = args.ncentroids
    fname = args.fitsfile
    fboxsize = args.fitbox_size
    sf = SpotFinder(fits_file=fname, nspots=nspots, verbose=False)
    sf.set_region_file(os.path.splitext(fname)[0]+'.reg')
    sf.set_parameter('fitbox_size', fboxsize)

    sf.get_centroids(print_summary=True)
