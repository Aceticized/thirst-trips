from math import radians, sin, cos, asin, sqrt

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth's radius in meters

    lat1, lon1, lat2, lon2 = map(
        radians, [lat1, lon1, lat2, lon2]
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    return 2 * R * asin(sqrt(a))
