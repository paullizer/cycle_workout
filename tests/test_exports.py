import io
import json
import unittest
import zipfile

from fastapi.testclient import TestClient
from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.course_point_message import CoursePointMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import CoursePoint, FileType, WorkoutStepDuration, WorkoutStepTarget

from terrain_coach.app import app
from terrain_coach.fit_export import course_fit, workout_fit
from terrain_coach.models import IntervalSet, Rider, WorkoutSpec
from terrain_coach.planner import plan_workout
from terrain_coach.report import cue_sheet, plan_summary
from terrain_coach.route import MAX_UPLOAD_BYTES, parse_route


GPX = b"""<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="40" lon="-105"><ele>1500</ele></trkpt>
<trkpt lat="40.05" lon="-105"><ele>1600</ele></trkpt>
</trkseg></trk></gpx>"""


def messages(data, message_type):
    return [r.message for r in FitFile.from_bytes(data).records
            if not r.is_definition and isinstance(r.message, message_type)]


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rider = Rider()
        cls.spec = WorkoutSpec(
            route_mode="out-and-back", duration_min_seconds=60, duration_max_seconds=7200,
            intervals=[IntervalSet(count=2, duration_seconds=60, recovery_seconds=60)],
        )
        cls.plan = plan_workout(parse_route(GPX, "route.gpx"), cls.rider, cls.spec)
        cls.course = course_fit(cls.plan)
        cls.workout = workout_fit(cls.plan)

    def test_fit_types_crc_and_route_round_trip(self):
        self.assertEqual(messages(self.course, FileIdMessage)[0].type, FileType.COURSE.value)
        self.assertEqual(messages(self.workout, FileIdMessage)[0].type, FileType.WORKOUT.value)
        records = messages(self.course, RecordMessage)
        self.assertEqual(len(records), len(self.plan.points))
        self.assertAlmostEqual(records[0].position_lat, 40, places=5)
        self.assertAlmostEqual(records[-1].distance, self.plan.points[-1].distance, places=2)
        parsed = parse_route(self.course, "route.fit")
        self.assertAlmostEqual(parsed[-1].distance, self.plan.points[-1].distance, delta=1)
        corrupt = bytearray(self.course)
        corrupt[-1] ^= 1
        with self.assertRaises(ValueError):
            parse_route(bytes(corrupt), "corrupt.fit")

    def test_workout_distance_and_absolute_power_match_course(self):
        steps = messages(self.workout, WorkoutStepMessage)
        self.assertEqual(len(steps), len(self.plan.steps))
        distance = 0
        for index, (step, planned) in enumerate(zip(steps, self.plan.steps)):
            self.assertEqual(step.message_index, index)
            self.assertEqual(step.duration_type, WorkoutStepDuration.DISTANCE.value)
            self.assertEqual(step.target_type, WorkoutStepTarget.POWER.value)
            self.assertEqual(step.target_power_zone, 0)
            self.assertEqual(step.custom_target_power_low, 1000 + planned.low)
            self.assertEqual(step.custom_target_power_high, 1000 + planned.high)
            self.assertAlmostEqual(distance, self.plan.points[planned.start].distance, delta=0.011)
            distance += step.duration_distance
            self.assertAlmostEqual(distance, self.plan.points[planned.end].distance, delta=0.011)
        self.assertAlmostEqual(distance, messages(self.course, RecordMessage)[-1].distance, places=2)

    def test_course_points_have_turnaround_and_watt_targets(self):
        cues = messages(self.course, CoursePointMessage)
        self.assertTrue(any(c.type == CoursePoint.U_TURN.value for c in cues))
        self.assertEqual(sum("S 210-230" == c.course_point_name for c in cues), 2)
        self.assertEqual(sum("E 210-230" == c.course_point_name for c in cues), 2)
        starts = [c.distance for c in cues if c.course_point_name == "S 210-230"]
        expected = [self.plan.points[s.start].distance for s in self.plan.steps if s.kind == "interval"]
        for actual, desired in zip(starts, expected):
            self.assertAlmostEqual(actual, desired, places=2)

    def test_cue_sheet_and_machine_summary(self):
        sheet = cue_sheet(self.plan, self.rider, self.spec)
        for text in ("<svg", "<rect", "Mile splits", "Fueling timeline", "14–18 g", "6 US fl oz",
                     "0:20:00", "Garmin/NewFiles", "210–230"):
            self.assertIn(text, sheet)
        self.assertNotIn("https://", sheet)
        summary = plan_summary(self.plan, self.rider, self.spec)
        self.assertEqual(summary["estimated_seconds"], self.plan.duration)
        self.assertTrue(summary["steps"])

    def test_report_escapes_warning_text(self):
        self.plan.warnings.append("<script>alert(1)</script>")
        try:
            sheet = cue_sheet(self.plan, self.rider, self.spec)
            self.assertIn("&lt;script&gt;", sheet)
            self.assertNotIn("<script>", sheet)
        finally:
            self.plan.warnings.pop()


class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://localhost")

    def test_local_ui_and_offline_help(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Terrain Coach", response.text)
        self.assertNotIn("https://", response.text)
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/", headers={"host": "attacker.example"}).status_code, 400)

    def test_download_bundle(self):
        response = self.client.post(
            "/plan", files={"route": ("route.gpx", GPX)},
            data={"rider": "{}", "spec": json.dumps({"duration_min_seconds": 590, "duration_max_seconds": 610})},
        )
        self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else "")
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(set(archive.namelist()), {
                "terrain_course.fit", "terrain_workout.fit", "cue_sheet.html", "plan.json", "EDGE_TRANSFER.txt",
            })
            self.assertTrue(messages(archive.read("terrain_workout.fit"), WorkoutStepMessage))
            summary = json.loads(archive.read("plan.json"))
            self.assertTrue(590 <= summary["estimated_seconds"] <= 610)

    def test_bad_upload_and_invalid_profiles(self):
        for filename, content, rider, spec in (
            ("route.txt", GPX, "{}", "{}"),
            ("route.gpx", b"<bad", "{}", "{}"),
            ("route.fit", b"bad fit", "{}", "{}"),
            ("route.gpx", GPX, '{"ftp":-10}', "{}"),
            ("route.gpx", GPX, '{"ftp":NaN}', "{}"),
            ("route.gpx", GPX, "{}", '{"endurance_low":80,"endurance_high":60}'),
            ("route.gpx", GPX, "{}", '{"duration_min_seconds":900,"duration_max_seconds":600}'),
        ):
            with self.subTest(filename=filename, rider=rider, spec=spec):
                response = self.client.post("/plan", files={"route": (filename, content)},
                                            data={"rider": rider, "spec": spec})
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/plan").status_code, 422)

    def test_upload_limit_and_cross_origin(self):
        response = self.client.post("/plan", files={"route": ("route.gpx", b"x" * (MAX_UPLOAD_BYTES + 1))})
        self.assertEqual(response.status_code, 413)
        response = self.client.post("/plan", headers={"origin": "https://attacker.example"},
                                    files={"route": ("route.gpx", GPX)})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/plan", headers={"origin": "http://localhost"},
                                    files={"route": ("route.gpx", GPX)})
        self.assertEqual(response.status_code, 200)
