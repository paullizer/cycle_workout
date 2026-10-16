import bisect
import math
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.record_message import RecordMessage

from terrain_coach.models import Point

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_POINTS = 50001


def haversine(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, h)))


def calculate_grades(distances: list[float], elevations: list[float]) -> list[float]:
    """Centered rise/run; grade is a fraction, not a percentage."""
    if len(distances) != len(elevations) or len(distances) < 2:
        raise ValueError("Grade calculation needs at least two matching points.")
    if any(b <= a for a, b in zip(distances, distances[1:])):
        raise ValueError("Distances must increase strictly.")
    result = []
    for i in range(len(distances)):
        lo, hi = max(0, i - 2), min(len(distances) - 1, i + 2)
        result.append((elevations[hi] - elevations[lo]) / (distances[hi] - distances[lo]))
    return result


def smooth_elevation(points: list[Point], radius: int = 3) -> list[float]:
    # Local linear regression smooths noise without flattening endpoint slopes.
    sums = [[0.0] for _ in range(4)]
    for p in points:
        for values, value in zip(sums, (p.distance, p.elevation, p.distance**2, p.distance * p.elevation)):
            values.append(values[-1] + value)
    result = []
    for i, p in enumerate(points):
        lo, hi = max(0, i - radius), min(len(points), i + radius + 1)
        n = hi - lo
        x, y, xx, xy = (values[hi] - values[lo] for values in sums)
        denominator = xx - x * x / n
        slope = (xy - x * y / n) / denominator if denominator > 1e-9 else 0
        result.append(y / n + slope * (p.distance - x / n))
    return result


def assign_grades(points: list[Point]) -> list[Point]:
    grades = calculate_grades([p.distance for p in points], [p.elevation for p in points])
    for p, grade in zip(points, grades):
        p.grade = grade
    return points


def interpolate(a: Point, b: Point, distance: float) -> Point:
    fraction = (distance - a.distance) / (b.distance - a.distance)
    # Take the short arc when crossing the antimeridian.
    dlon = (b.lon - a.lon + 180) % 360 - 180
    return Point(
        a.lat + fraction * (b.lat - a.lat),
        (a.lon + fraction * dlon + 180) % 360 - 180,
        a.elevation + fraction * (b.elevation - a.elevation),
        distance,
    )


def resample(raw: list[Point], spacing: float = 10) -> list[Point]:
    if spacing <= 0:
        raise ValueError("Spacing must be positive.")
    points = []
    for p in raw:
        if not all(math.isfinite(v) for v in (p.lat, p.lon, p.elevation)):
            raise ValueError("Route coordinates and elevation must be finite.")
        if not (-90 <= p.lat <= 90 and -180 <= p.lon <= 180 and -500 <= p.elevation <= 9000):
            raise ValueError("Route coordinates or elevation are out of range.")
        if not points:
            points.append(Point(p.lat, p.lon, p.elevation))
        else:
            delta = haversine(points[-1], p)
            if delta > 0.1:
                points.append(Point(p.lat, p.lon, p.elevation, points[-1].distance + delta))
    if len(points) < 2 or points[-1].distance < 30:
        raise ValueError("Route must contain at least 30 m of valid GPS points with elevation.")
    length = points[-1].distance
    if length > 500000 or length / spacing > MAX_POINTS - 1:
        raise ValueError("Route exceeds the 500 km / 50,001 resampled point limit.")
    sampled = []
    index = 0
    distances = [i * spacing for i in range(math.ceil(length / spacing))]
    distances.append(length)
    for distance in distances:
        while index < len(points) - 2 and points[index + 1].distance < distance:
            index += 1
        sampled.append(interpolate(points[index], points[index + 1], distance))
    for p, elevation in zip(sampled, smooth_elevation(sampled)):
        p.elevation = elevation
    return assign_grades(sampled)


def parse_route(data: bytes, filename: str) -> list[Point]:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload a nonempty route file no larger than 10 MiB.")
    extension = filename.rsplit(".", 1)[-1].lower()
    raw = []
    try:
        if extension == "fit":
            fit = FitFile.from_bytes(data, check_crc=True)
            for record in fit.records:
                message = record.message
                if isinstance(message, RecordMessage):
                    if message.position_lat is None or message.position_long is None:
                        continue
                    elevation = message.enhanced_altitude
                    if elevation is None:
                        elevation = message.altitude
                    if elevation is None:
                        raise ValueError("FIT GPS records need elevation.")
                    raw.append(Point(message.position_lat, message.position_long, elevation))
        elif extension in ("gpx", "tcx"):
            root = ElementTree.fromstring(data, forbid_dtd=True)
            if extension == "gpx":
                if root.tag.split("}")[-1] != "gpx":
                    raise ValueError("Expected a GPX document.")
                nodes = root.findall(".//{*}trkpt") or root.findall(".//{*}rtept")
                for node in nodes:
                    raw.append(Point(float(node.attrib["lat"]), float(node.attrib["lon"]),
                                     float(node.findtext("{*}ele"))))
            else:
                if root.tag.split("}")[-1] != "TrainingCenterDatabase":
                    raise ValueError("Expected a TCX document.")
                for node in root.findall(".//{*}Trackpoint"):
                    position = node.find("{*}Position")
                    if position is not None:
                        raw.append(Point(float(position.findtext("{*}LatitudeDegrees")),
                                         float(position.findtext("{*}LongitudeDegrees")),
                                         float(node.findtext("{*}AltitudeMeters"))))
        else:
            raise ValueError("Supported route files are GPX, TCX, and FIT.")
    except (ParseError, DefusedXmlException, TypeError, KeyError, OverflowError) as exc:
        raise ValueError("Invalid route: GPS coordinates and elevation are required; XML entities are forbidden.") from exc
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Unable to decode route file.") from exc
    if len(raw) > 200000:
        raise ValueError("Route contains too many input points (maximum 200,000).")
    return resample(raw)


def cut_route(points: list[Point], distance: float, out_and_back: bool = False) -> tuple[list[Point], int | None]:
    distance = min(points[-1].distance, max(10, distance))
    distances = [p.distance for p in points]
    end = bisect.bisect_left(distances, distance)
    outbound = [Point(p.lat, p.lon, p.elevation, p.distance) for p in points[:end]]
    outbound.append(interpolate(points[end - 1], points[end], distance))
    turnaround = None
    if out_and_back:
        turnaround = len(outbound) - 1
        outbound += [
            Point(p.lat, p.lon, p.elevation, 2 * distance - p.distance)
            for p in reversed(outbound[:-1])
        ]
    return assign_grades(outbound), turnaround
