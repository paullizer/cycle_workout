import copy
import io
import json
import re
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
        self.assertEqual(sum(c.course_point_name in ("INT1 GO 210-230W", "INT2 GO 210-230W")
                             for c in cues), 2)
        self.assertEqual(sum(c.course_point_name in ("INT1 END", "INT2 END") for c in cues), 2)
        starts = [c.distance for c in cues if c.course_point_name in ("INT1 GO 210-230W", "INT2 GO 210-230W")]
        expected = [self.plan.points[s.start].distance for s in self.plan.steps if s.kind == "interval"]
        for actual, desired in zip(starts, expected):
            self.assertAlmostEqual(actual, desired, places=2)

    def test_every_course_point_name_matches_documented_pattern(self):
        patterns = (
            r"INT\d+ GO \d{1,4}-\d{1,4}W",
            r"I\d+ GO \d{1,4}-\d{1,4}",
            r"INT\d+ END",
            r"TURN PRESS LAP",
            r"SHIFT (?:EASY|HARD) -?\d+%",
            r"SHIFT [EH] -?\d+%",
            r"COURSE END",
        )
        for cue in messages(self.course, CoursePointMessage):
            name = cue.course_point_name
            self.assertLessEqual(len(name), 16)
            self.assertTrue(any(re.fullmatch(pattern, name) for pattern in patterns), name)

    def test_compact_interval_and_finish_names_stay_within_limit(self):
        extreme = copy.deepcopy(self.plan)
        interval_steps = [step for step in extreme.steps if step.kind == "interval"]
        interval_steps[1].low, interval_steps[1].high = 205, 219
        names = [cue.course_point_name for cue in messages(course_fit(extreme), CoursePointMessage)]
        self.assertIn("INT2 GO 205-219W", names)
        self.assertIn("INT2 END", names)

        extreme = copy.deepcopy(self.plan)
        for step in extreme.steps:
            if step.kind == "interval":
                step.low = step.high = 2000
        names = [cue.course_point_name for cue in messages(course_fit(extreme), CoursePointMessage)]
        self.assertIn("I1 GO 2000-2000", names)
        self.assertTrue(all(len(name) <= 16 for name in names))

        short_spec = WorkoutSpec(
            route_mode="truncate", duration_min_seconds=60, duration_max_seconds=120,
        )
        short_plan = plan_workout(parse_route(GPX, "route.gpx"), self.rider, short_spec)
        short_names = [cue.course_point_name for cue in messages(course_fit(short_plan), CoursePointMessage)]
        self.assertIn("COURSE END", short_names)
        self.assertTrue(all(len(name) <= 16 for name in short_names))

    def test_cue_sheet_and_machine_summary(self):
        sheet = cue_sheet(self.plan, self.rider, self.spec)
        for text in ("<svg", "<rect", "Mile splits", "Fueling timeline", "14–18 g", "6 US fl oz",
                     "0:20:00", "Garmin/NewFiles", "210–230"):
            self.assertIn(text, sheet)
        self.assertNotIn("https://", sheet)
        summary = plan_summary(self.plan, self.rider, self.spec)
        self.assertEqual(summary["estimated_seconds"], self.plan.duration)
        self.assertTrue(summary["steps"])
        fit_points = messages(self.course, CoursePointMessage)
        self.assertEqual(len(summary["course_points"]), len(fit_points))
        for detail, fit_point in zip(summary["course_points"], fit_points):
            self.assertAlmostEqual(detail["distance_m"], fit_point.distance, places=2)
            self.assertEqual(detail["name"], fit_point.course_point_name)
            self.assertIn(detail["type"], ("interval", "interval_end", "turnaround", "shift", "finish"))
            if detail["type"] in ("interval", "interval_end"):
                self.assertEqual(set(detail["target_watts"]), {"low", "high"})
            else:
                self.assertIsNone(detail["target_watts"])

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
            fit_points = messages(archive.read("terrain_course.fit"), CoursePointMessage)
            self.assertEqual(
                [point["name"] for point in summary["course_points"]],
                [point.course_point_name for point in fit_points],
            )

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
