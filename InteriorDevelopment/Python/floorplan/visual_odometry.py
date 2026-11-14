"""How the camera moved between two consecutive photos, measured from the photos themselves.

Features (ORB) are matched between photo A and photo B. Photo A's depth gives each matched feature a 3D
position (in metres), and PnP finds the camera motion that explains where those features appear in photo B.
Because the depth is metric, the motion comes out in metres, with no scale ambiguity.
"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class RelativeMotion:
    rotation: np.ndarray   # 3x3, takes points from camera A's frame to camera B's frame (OpenCV convention)
    translation: np.ndarray  # (3,)
    inliers: int
    candidates: int = 0      # how many matched features were tried; inliers / candidates says how much to trust it


def _gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def relative_motion(
    image_a: np.ndarray, depth_a: np.ndarray, image_b: np.ndarray, camera_matrix: np.ndarray,
    min_inliers: int = 30, min_depth: float = 0.3, max_depth: float = 10.0,
) -> RelativeMotion | None:
    gray_a, gray_b = _gray(image_a), _gray(image_b)
    orb = cv2.ORB_create(nfeatures=2500, fastThreshold=8)
    keypoints_a, descriptors_a = orb.detectAndCompute(gray_a, None)
    keypoints_b, descriptors_b = orb.detectAndCompute(gray_b, None)
    if descriptors_a is None or descriptors_b is None or len(keypoints_a) < 12 or len(keypoints_b) < 12:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = []
    for pair in matcher.knnMatch(descriptors_a, descriptors_b, k=2):
        if len(pair) == 2 and pair[0].distance < 0.8 * pair[1].distance:
            good.append(pair[0])
    if len(good) < 12:
        return None

    focal, cx, cy = camera_matrix[0, 0], camera_matrix[0, 2], camera_matrix[1, 2]
    height, width = depth_a.shape
    object_points, image_points = [], []
    for match in good:
        ua, va = keypoints_a[match.queryIdx].pt
        iu, iv = int(round(ua)), int(round(va))
        if not (0 <= iu < width and 0 <= iv < height):
            continue
        z = float(depth_a[iv, iu])
        if not (np.isfinite(z) and min_depth < z < max_depth):
            continue
        object_points.append([z * (ua - cx) / focal, z * (va - cy) / focal, z])  # OpenCV frame: y down
        image_points.append(keypoints_b[match.trainIdx].pt)
    if len(object_points) < 12:
        return None

    object_points = np.array(object_points, dtype=np.float64)
    image_points = np.array(image_points, dtype=np.float64)
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        object_points, image_points, camera_matrix, None,
        iterationsCount=400, reprojectionError=3.0, confidence=0.995, flags=cv2.SOLVEPNP_EPNP,
    )
    if not ok or inliers is None or len(inliers) < min_inliers:
        return None
    inliers = inliers.ravel()
    rvec, tvec = cv2.solvePnPRefineLM(object_points[inliers], image_points[inliers], camera_matrix, None, rvec, tvec)
    rotation, _ = cv2.Rodrigues(rvec)
    return RelativeMotion(rotation=rotation, translation=tvec.ravel(), inliers=int(len(inliers)), candidates=len(object_points))
