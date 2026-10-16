import math
import unittest

from terrain_coach.models import Point, Rider
from terrain_coach.physics import estimate_speed
from terrain_coach.route import calculate_grades, parse_route, resample


class GradeTests(unittest.TestCase):
    def test_constant_slope_and_descent(self):
        self.assertEqual(calculate_grades([0, 10, 20], [100, 101, 102]), [0.1] * 3)
        self.assertEqual(calculate_grades([0, 10, 20], [2, 1, 0]), [-0.1] * 3)

    def test_duplicate_distances_rejected(self):
        with self.assertRaises(ValueError):
            calculate_grades([0, 0], [1, 2])

    def test_resampling_smooths_noise_and_preserves_linear_grade(self):
        points = resample([Point(0, 0, 0), Point(0, 0.01, 55.59746)])
        self.assertAlmostEqual(points[1].distance, 10)
        self.assertAlmostEqual(points[-1].grade, 0.05, places=4)
        self.assertTrue(all(b.distance > a.distance for a, b in zip(points, points[1:])))

    def test_unsafe_or_incomplete_xml_rejected(self):
        for data in (
            b'<!DOCTYPE gpx [<!ENTITY x "bad">]><gpx/>',
            b'<gpx><trkpt lat="0" lon="0"/></gpx>',
            b'<gpx><trkpt lat="NaN" lon="0"><ele>1</ele></trkpt></gpx>',
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_route(data, "route.gpx")

    def test_gpx_and_tcx_namespaces(self):
        gpx = b'<gpx xmlns="urn:gpx"><rte><rtept lat="0" lon="0"><ele>0</ele></rtept><rtept lat="0" lon=".01"><ele>10</ele></rtept></rte></gpx>'
        tcx = b'<TrainingCenterDatabase xmlns="urn:tcx"><Courses><Course><Track><Trackpoint><Position><LatitudeDegrees>0</LatitudeDegrees><LongitudeDegrees>0</LongitudeDegrees></Position><AltitudeMeters>0</AltitudeMeters></Trackpoint><Trackpoint><Position><LatitudeDegrees>0</LatitudeDegrees><LongitudeDegrees>.01</LongitudeDegrees></Position><AltitudeMeters>10</AltitudeMeters></Trackpoint></Track></Course></Courses></TrainingCenterDatabase>'
        self.assertAlmostEqual(parse_route(gpx, "a.GPX")[-1].distance,
                               parse_route(tcx, "a.tcx")[-1].distance)


class SpeedTests(unittest.TestCase):
    def test_flat_power_balance(self):
        rider = Rider(surface="road")
        speed = estimate_speed(200, 0, rider)
        calculated_power = (rider.mass_kg * 9.80665 * 0.004 + 0.5 * 1.225 * 0.32 * speed**2) * speed
        self.assertAlmostEqual(calculated_power, 200 * 0.97, places=5)
        self.assertTrue(7 < speed < 11)

    def test_power_slope_surface_position_and_mass(self):
        rider = Rider()
        flat = estimate_speed(180, 0, rider)
        self.assertLess(estimate_speed(180, 0.05, rider), flat)
        self.assertGreater(estimate_speed(180, -0.05, rider), flat)
        self.assertGreater(estimate_speed(250, 0, rider), flat)
        self.assertGreater(estimate_speed(180, 0, Rider(surface="road")), flat)
        self.assertGreater(estimate_speed(180, 0, Rider(position="aero")), flat)
        self.assertLess(estimate_speed(180, 0.05, Rider(rider_weight_lb=240)),
                        estimate_speed(180, 0.05, rider))

    def test_coasting_downhill_and_invalid_power(self):
        self.assertGreater(estimate_speed(0, -0.05, Rider()), 0.1)
        for power in (-1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                estimate_speed(power, 0, Rider())
