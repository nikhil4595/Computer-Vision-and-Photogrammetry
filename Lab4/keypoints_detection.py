import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndim
import imageio
import matplotlib.pyplot as plt
import time
import skimage.feature

def find_local_maxima(points, cornerness):
    # t1 = time.time()
    footprint = np.ones((3,3))
    footprint[1,1] = 0
    maxima_around = ndim.maximum_filter(cornerness, footprint=footprint)
    mask = cornerness > maxima_around
    # t2 = time.time()
    # print('simple filtering: {} seconds.'.format(t2-t1))    
    return points[mask[points[:,0], points[:,1]]]

def adaptive_non_maximal_suppression(points, cornerness, number_of_output_points, coeff):
    points = find_local_maxima(points, cornerness)
    # t1 = time.time()
    points_values = cornerness[points[:,0], points[:,1]]
    points_sorted = points[np.argsort(points_values)[::-1],:]
    points_values.sort()
    points_values = points_values[::-1]
    points_dists = np.sqrt(np.sum((points_sorted[:, np.newaxis, :] - points_sorted[np.newaxis, :, :]) ** 2, axis=-1))
    mask = points_values[:,np.newaxis] < coeff * points_values[np.newaxis,:]
    np.fill_diagonal(mask, False)
    points_dists[~mask] = np.inf
    points_radiuses = np.min(points_dists, axis=1)
    points_radiuses[points_radiuses == np.inf] = 0.
    keypoints = points_sorted[np.argsort(points_radiuses)[::-1],:]
    points_radiuses.sort()
    number_of_output_points = np.min([len(points_radiuses), number_of_output_points])
    print('Minimal radius: {}'.format(points_radiuses[-number_of_output_points]))
    # t2 = time.time()
    # print('ANMS: {} seconds.'.format(t2-t1))
    return keypoints[:number_of_output_points, :]

def draw_image_with_points(filename, points, fill, new_filename):
    im = Image.open(filename)
    draw = ImageDraw.Draw(im)
    width = 2
    for point in points:
        x = point[0]
        y = point[1]
        draw.ellipse((x - width, y - width, x + width, y + width), fill=fill)
        draw.point(point, fill=fill)
    im.save(new_filename, 'JPEG')

def harris_corner_detector(image, threshold, σ_I=5., s=0.7, α=0.05):
    σ_D = s * σ_I
    im_x = np.zeros(image.shape)
    im_y = np.zeros(image.shape)
    ndim.gaussian_filter1d(image, sigma=σ_D, order=1, axis=0, output=im_x)
    ndim.gaussian_filter1d(image, sigma=σ_D, order=1, axis=1, output=im_y)
    gaussian_I_x_2 = np.zeros(image.shape)
    gaussian_I_y_2 = np.zeros(image.shape)
    gaussian_I_x_y = np.zeros(image.shape)
    ndim.gaussian_filter(im_x ** 2, sigma=σ_I, output=gaussian_I_x_2)
    ndim.gaussian_filter(im_y ** 2, sigma=σ_I, output=gaussian_I_y_2)
    ndim.gaussian_filter(im_x * im_y, sigma=σ_I, output=gaussian_I_x_y)
    cornerness = gaussian_I_x_2 * gaussian_I_x_2 - gaussian_I_x_y ** 2 - α * (gaussian_I_x_2 + gaussian_I_y_2) ** 2
    print('Maximal and minimal cornerness values: ', cornerness.max(), cornerness.min())
    points_over_threshold = np.argwhere(cornerness > threshold)
    print('Points over threshold shape: ', points_over_threshold.shape)
    return points_over_threshold, cornerness

def harris_corner_with_simple_filtering(image, threshold=1e2):
    '''Detecting interesting points with Harris corner detector
       using easy local maxima requirement'''
    points, cornerness = harris_corner_detector(image, threshold)
    return find_local_maxima(points, cornerness)

def harris_corner_with_ANMS(image, number_of_output_points, threshold=1e2, coeff=0.9):
    '''Detecting interesting points with Harris corner detector
       using adaptive non-maximal suppression'''
    points, cornerness = harris_corner_detector(image, threshold)
    return adaptive_non_maximal_suppression(points, cornerness, number_of_output_points, coeff)

def harris_laplace(image, laplace_threshold, harris_threshold, σ_init, σs_num, σ_step):
    keypoints_candidates = []

    # find local maxima of harris function
    for i in range(σs_num):
        points_over_threshold, cornerness = harris_corner_detector(image, harris_threshold, σ_init * σ_step ** i)
        keypoints_candidates.append(find_local_maxima(points_over_threshold, cornerness))
    
    # compute laplace function for each scale
    laplace = np.zeros((σs_num, image.shape[0], image.shape[1]))
    for i in range(σs_num):
        ndim.gaussian_laplace(image, σ_init * σ_step ** i, output=laplace[i,:,:])
        print(laplace[i].min(), laplace[i].max())
    
    # find local extremas over scales of laplace function
    for i in range(1, σs_num-1):
        kp = keypoints_candidates[i]
        kp = kp[np.abs(laplace[i,kp[:,0],kp[:,1]]) > laplace_threshold]
        # print(kp.shape)
        keypoints_candidates[i] = kp[(((laplace[i] - laplace[i-1])[kp[:,0],kp[:,1]] < 0) & ((laplace[i] - laplace[i+1])[kp[:,0],kp[:,1]] < 0)) |
                                     (((laplace[i] - laplace[i-1])[kp[:,0],kp[:,1]] > 0) & ((laplace[i] - laplace[i+1])[kp[:,0],kp[:,1]] > 0))]
        print(keypoints_candidates[i].shape)

    return keypoints_candidates[1:-1]

def draw_points_with_scale_markers(filename, points, fill, new_filename, scale_init, scale_step):
    im = Image.open(filename)
    draw = ImageDraw.Draw(im)
    width = scale_init * 3
    for scale in range(len(points)):
        for point in points[scale]:
            y = point[0]
            x = point[1]
            draw.ellipse((x - width, y - width, x + width, y + width), fill=None, outline=fill)
            draw.point(point, fill=fill)
        width *= scale_step
    im.save(new_filename, 'JPEG')

def difference_of_gaussians(image, octaves_num=4, σ=1.6, scales_num=3):
    differences = []
    # computing all differences
    for oct in range(octaves_num):
        image_zoomed = ndim.zoom(image, 0.5 ** oct)
        differences.append(difference_of_gaussians_one_octave(image_zoomed, σ, scales_num))
        # find keypoints
        # image_zoomed = ndim.zoom(image_zoomed, 0.5)

    # computing maximal values in 3x3 windows from every difference
    footprint = np.ones((3,3,3))
    footprint[1,1,1] = 0
    keypoints_for_octaves = []
    for oct in range(octaves_num):
        diff = differences[oct]
        # computing indices of maximas
        maxima_around = ndim.maximum_filter(diff, footprint=footprint)[1:4]
        minima_around = ndim.minimum_filter(diff, footprint=footprint)[1:4]
        maxima_mask = diff[1:4] > maxima_around
        minima_mask = diff[1:4] < minima_around
        keypoints_candidates = np.argwhere(maxima_mask | minima_mask)
        draw_image_with_points('data/Episcopal_Gaudi/EG_2.jpg', np.fliplr(keypoints_candidates[:,1:]), (255,0,0), 'temp.jpg')

        # filter keypoints with low contrast
        keypoints = []
        for s in range(scales_num):
            keypoints_after_filtering = filter_low_contrast_keypoints(keypoints_candidates[keypoints_candidates[:,0] == s][:,1:], differences[oct][s:s+3,:,:])
            keypoints.append(keypoints_after_filtering)

        keypoints_for_octaves.append(np.concatenate(keypoints, axis=0))

    return keypoints_for_octaves

def difference_of_gaussians_one_octave(image, σ, scales_num):
    gaussian_images = []
    k = 2**(1/scales_num)
    # ks = np.cumprod(np.ones(scales_num+2) * 2**(1/scales_num))
    gaussian_images = np.zeros((scales_num+3, image.shape[0], image.shape[1]))
    # gaussian_images.append(ndim.gaussian_filter(image, σ, order=(0,0)))
    # ndim.gaussian_filter(image, σ, order=(0,0), output=gaussian_images[0,:,:])
    for i in range(scales_num+3):
        # gaussian_images.append(ndim.gaussian_filter(image, k**(i+1) *σ, order=(0,0)))
        ndim.gaussian_filter(image, k**i *σ, order=(0,0), output=gaussian_images[i,:,:])
    # gaussian_images = np.stack(gaussian_images, axis=0)
    differences = gaussian_images[1:,:,:] - gaussian_images[:-1,:,:]
    # for i in range(scales_num+2):
    #     imageio.imsave('temp' + str(i) + '.jpg', differences[i])
    return differences

def filter_low_contrast_keypoints(keypoints, diff, threshold=7.65, eigenvals_ratio=10.):
    grad = np.stack(np.gradient(diff), axis=-1)
    # print(diff.shape)
    h11, h12, h13, h22, h23, h33 = skimage.feature.hessian_matrix(diff, order='rc')
    # print(h11.shape)
    hess = np.stack((np.stack((h11,h12,h13),axis=-1), np.stack((h12,h22,h23),axis=-1), np.stack((h13,h23,h33),axis=-1)),axis=-1)
    # print(hess.shape)
    hess_det = np.linalg.det(hess[1,keypoints[:,0], keypoints[:,1]])
    # print(hess_det.shape, keypoints.shape)
    keypoints_not_singular = keypoints[hess_det != 0.,:]
    keypoints_grad = grad[1,keypoints_not_singular[:,0], keypoints_not_singular[:,1],:]
    keypoint_hess = hess[1,keypoints_not_singular[:,0],keypoints_not_singular[:,1]]
    hess_inv = np.linalg.inv(keypoint_hess)
    # print(keypoints_grad.shape, hess_inv.shape)
    extr_locations = -1 * np.sum(keypoints_grad[:,np.newaxis,:] * hess_inv, axis=-1)
    # print(np.sum(np.sum(np.abs(extr_locations[:,:]),axis=1) == 0.))
    # -keypoints_grad.dot(hess_inv)
    # print(extr_locations.shape)
    extr_values = diff[1,keypoints_not_singular[:,0], keypoints_not_singular[:,1]] + np.sum(extr_locations * keypoints_grad, axis=-1) / 2.
    # print(extr_values.shape)
    # print(keypoints_not_singular[np.abs(extr_values) > threshold,:].shape)
    keypoints_after_thresholding = keypoints_not_singular[np.abs(extr_values) > threshold,:]
    # hessian_trace_square_2x2 = (ndim.laplace(diff[1,:,:]) ** 2)[keypoints_after_thresholding[:,0], keypoints_after_thresholding[:,1]]
    # hessian_det_2x2 = skimage.feature.hessian_matrix_det(diff[1,:,:])[keypoints_after_thresholding[:,0], keypoints_after_thresholding[:,1]]
    # return keypoints_after_thresholding[(hessian_det_2x2 != 0) & (hessian_trace_square_2x2 / hessian_det_2x2 < eigenvals_ratio)]

    hess_after_thresholding = keypoint_hess[np.abs(extr_values) > threshold,:,:]
    hess_det_after_thresholding = hess_det[hess_det != 0][np.abs(extr_values) > threshold]
    # print(keypoints_after_thresholding.shape, hess_after_thresholding.shape, hess_det_after_thresholding.shape)
    hess_trace_square_after_thresholding = np.trace(hess_after_thresholding, axis1=1, axis2=2) ** 2
    return keypoints_after_thresholding[hess_trace_square_after_thresholding / hess_det_after_thresholding < (eigenvals_ratio+1)**2 / eigenvals_ratio,:]

def compute_keypoints_original_coordinates(keypoints_for_octaves):
    '''Scaling keypoints coordinates back to original image'''
    keypoints_original_coordinates = []
    for s in range(len(keypoints_for_octaves)):
        keypoints_original_coordinates.append(keypoints_for_octaves[s] * 2**s)
    return np.concatenate(keypoints_original_coordinates, axis=0)

def detect_on_examples_with_simple_harris_corner():
    print('Harris corner detector')
    image = imageio.imread('data/Episcopal_Gaudi/EG_1_gray.jpg')
    keypoints = harris_corner_with_simple_filtering(image, threshold=1e2)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Episcopal_Gaudi/EG_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Episcopal_Gaudi/simple_harris1.jpg')

    print('Harris corner detector')
    image = imageio.imread('data/Episcopal_Gaudi/EG_2_gray.jpg')
    keypoints = harris_corner_with_simple_filtering(image, threshold=5e1)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Episcopal_Gaudi/EG_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Episcopal_Gaudi/simple_harris2.jpg')

    print('Harris corner detector')
    image = imageio.imread('data/Mount_Rushmore/MR_1_gray.jpg')
    keypoints = harris_corner_with_simple_filtering(image)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Mount_Rushmore/MR_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Mount_Rushmore/simple_harris1.jpg')

    print('Harris corner detector')
    image = imageio.imread('data/Mount_Rushmore/MR_2_gray.jpg')
    keypoints = harris_corner_with_simple_filtering(image)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Mount_Rushmore/MR_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Mount_Rushmore/simple_harris2.jpg')

    print('Harris corner detector')
    image = imageio.imread('data/Notre_Dame/ND_1_gray.jpg')
    keypoints = harris_corner_with_simple_filtering(image)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Notre_Dame/ND_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Notre_Dame/simple_harris1.jpg')

    print('Harris corner detector')
    image = imageio.imread('data/Notre_Dame/ND_2_gray.jpg')
    keypoints = harris_corner_with_simple_filtering(image)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Notre_Dame/ND_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Notre_Dame/simple_harris2.jpg')

def detect_on_examples_with_harris_corner_and_ANMS():
    print('Harris corner detector with ANMS')
    image = imageio.imread('data/Episcopal_Gaudi/EG_1_gray.jpg')
    keypoints = harris_corner_with_ANMS(image, 1500, threshold=5e1)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Episcopal_Gaudi/EG_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Episcopal_Gaudi/ANMS_harris1.jpg')

    print('Harris corner detector with ANMS')
    image = imageio.imread('data/Episcopal_Gaudi/EG_2_gray.jpg')
    keypoints = harris_corner_with_ANMS(image, 1500, threshold=5e1)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Episcopal_Gaudi/EG_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Episcopal_Gaudi/ANMS_harris2.jpg')

    print('Harris corner detector with ANMS')
    image = imageio.imread('data/Mount_Rushmore/MR_1_gray.jpg')
    keypoints = harris_corner_with_ANMS(image, 1500)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Mount_Rushmore/MR_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Mount_Rushmore/ANMS_harris1.jpg')

    print('Harris corner detector with ANMS')
    image = imageio.imread('data/Mount_Rushmore/MR_2_gray.jpg')
    keypoints = harris_corner_with_ANMS(image, 1500)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Mount_Rushmore/MR_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Mount_Rushmore/ANMS_harris2.jpg')

    print('Harris corner detector with ANMS')
    image = imageio.imread('data/Notre_Dame/ND_1_gray.jpg')
    keypoints = harris_corner_with_ANMS(image, 1500)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Notre_Dame/ND_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Notre_Dame/ANMS_harris1.jpg')

    print('Harris corner detector with ANMS')
    image = imageio.imread('data/Notre_Dame/ND_2_gray.jpg')
    keypoints = harris_corner_with_ANMS(image, 1500)
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Notre_Dame/ND_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Notre_Dame/ANMS_harris2.jpg')


# detect_on_examples_with_simple_harris_corner()
# detect_on_examples_with_harris_corner_and_ANMS()

def detect_with_DoG():
    print('Difference of Gaussians')
    image = imageio.imread('data/Episcopal_Gaudi/EG_1_gray.jpg')
    keypoints = compute_keypoints_original_coordinates(difference_of_gaussians(image))
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Episcopal_Gaudi/EG_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Episcopal_Gaudi/DoG1.jpg')

    print('Difference of Gaussians')
    image = imageio.imread('data/Episcopal_Gaudi/EG_2_gray.jpg')
    keypoints = compute_keypoints_original_coordinates(difference_of_gaussians(image))
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Episcopal_Gaudi/EG_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Episcopal_Gaudi/DoG2.jpg')

    print('Difference of Gaussians')
    image = imageio.imread('data/Mount_Rushmore/MR_1_gray.jpg')
    keypoints = compute_keypoints_original_coordinates(difference_of_gaussians(image))
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Mount_Rushmore/MR_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Mount_Rushmore/DoG1.jpg')

    print('Difference of Gaussians')
    image = imageio.imread('data/Mount_Rushmore/MR_2_gray.jpg')
    keypoints = compute_keypoints_original_coordinates(difference_of_gaussians(image))
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Mount_Rushmore/MR_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Mount_Rushmore/DoG2.jpg')

    print('Difference of Gaussians')
    image = imageio.imread('data/Notre_Dame/ND_1_gray.jpg')
    keypoints = compute_keypoints_original_coordinates(difference_of_gaussians(image))
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Notre_Dame/ND_1.jpg', np.fliplr(keypoints), (255,0,0), 'data/Notre_Dame/DoG1.jpg')

    print('Difference of Gaussians')
    image = imageio.imread('data/Notre_Dame/ND_2_gray.jpg')
    keypoints = compute_keypoints_original_coordinates(difference_of_gaussians(image))
    print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_image_with_points('data/Notre_Dame/ND_2.jpg', np.fliplr(keypoints), (255,0,0), 'data/Notre_Dame/DoG2.jpg')

# detect_with_DoG()

def detect_with_harris_laplace():
    print('Harris-Laplace')
    image = imageio.imread('data/Episcopal_Gaudi/EG_1_gray.jpg')
    keypoints = harris_laplace(image, 1., 1e2, 1.5, 13, 1.2)
    # print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_points_with_scale_markers('data/Episcopal_Gaudi/EG_1.jpg', keypoints, (255,0,0), 'data/Episcopal_Gaudi/Harris-Laplace1.jpg', 1.5, 1.2)


    print('Harris-Laplace')
    image = imageio.imread('data/Episcopal_Gaudi/EG_2_gray.jpg')
    keypoints = harris_laplace(image, 1., 1e2, 1.5, 13, 1.2)
    # print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_points_with_scale_markers('data/Episcopal_Gaudi/EG_2.jpg', keypoints, (255,0,0), 'data/Episcopal_Gaudi/Harris-Laplace2.jpg', 1.5, 1.2)


    print('Harris-Laplace')
    image = imageio.imread('data/Mount_Rushmore/MR_1_gray.jpg')
    keypoints = harris_laplace(image, 1., 1e2, 1.5, 13, 1.2)
    # print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_points_with_scale_markers('data/Mount_Rushmore/MR_1.jpg', keypoints, (255,0,0), 'data/Mount_Rushmore/Harris-Laplace1.jpg', 1.5, 1.2)


    print('Harris-Laplace')
    image = imageio.imread('data/Mount_Rushmore/MR_2_gray.jpg')
    keypoints = harris_laplace(image, 1., 1e2, 1.5, 13, 1.2)
    # print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_points_with_scale_markers('data/Mount_Rushmore/MR_2.jpg', keypoints, (255,0,0), 'data/Mount_Rushmore/Harris-Laplace2.jpg', 1.5, 1.2)


    print('Harris-Laplace')
    image = imageio.imread('data/Notre_Dame/ND_1_gray.jpg')
    keypoints = harris_laplace(image, 1., 1e2, 1.5, 13, 1.2)
    # print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_points_with_scale_markers('data/Notre_Dame/ND_1.jpg', keypoints, (255,0,0), 'data/Notre_Dame/Harris-Laplace1.jpg', 1.5, 1.2)


    print('Harris-Laplace')
    image = imageio.imread('data/Notre_Dame/ND_2_gray.jpg')
    keypoints = harris_laplace(image, 1., 1e2, 1.5, 13, 1.2)
    # print('Found keypoints shape: ', keypoints.shape, '\n\n\n')
    draw_points_with_scale_markers('data/Notre_Dame/ND_2.jpg', keypoints, (255,0,0), 'data/Notre_Dame/Harris-Laplace2.jpg', 1.5, 1.2)

detect_with_harris_laplace( )
# image = np.array(Image.open('/home/dominik/Dokumenty/Studia/CVandPhotogrammetry/piesek/IMG_0161.JPG', 'r').convert('L'))
# keypoints = harris_corner_with_ANMS(image, 1500, threshold=5e1)
# print(keypoints.shape)
# draw_image_with_points('/home/dominik/Dokumenty/Studia/CVandPhotogrammetry/piesek/IMG_0161.JPG', np.fliplr(keypoints), (255,0,0), '/home/dominik/Dokumenty/Studia/CVandPhotogrammetry/piesek/features/IMG_0161.JPG')