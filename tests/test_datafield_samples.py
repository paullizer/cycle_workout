from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.course_point_message import CoursePointMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.profile_type import FileType


ROOT = Path(__file__).resolve().parents[1]


def read_messages(name, kind):
    fit = FitFile.from_bytes((ROOT / "samples" / name).read_bytes())
    return [record.message for record in fit.records
            if not record.is_definition and isinstance(record.message, kind)]


class DataFieldSamplesTests(unittest.TestCase):
    def test_course_cue_schedule(self):
        self.assertEqual(read_messages("terrain-course.fit", FileIdMessage)[0].type,
                         FileType.COURSE.value)
        cues = read_messages("terrain-course.fit", CoursePointMessage)
        self.assertEqual([(cue.distance, cue.course_point_name) for cue in cues], [
            (500, "S 210-230"), (700, "Down 6%"), (1000, "E 210-230"),
            (1200, "S 210-"), (1400, "S 210-230"), (1600, "Up -3%"),
            (1800, "E 210-230"),
        ])

    def test_activity_matches_course_and_has_power_samples(self):
        self.assertEqual(read_messages("terrain-activity.fit", FileIdMessage)[0].type,
                         FileType.ACTIVITY.value)
        course = read_messages("terrain-course.fit", RecordMessage)
        activity = read_messages("terrain-activity.fit", RecordMessage)
        self.assertEqual(len(activity), 201)
        self.assertEqual(len(course), len(activity))
        for index, (expected, actual) in enumerate(zip(course, activity)):
            self.assertEqual(actual.timestamp, expected.timestamp)
            self.assertEqual(actual.position_lat, expected.position_lat)
            self.assertEqual(actual.position_long, expected.position_long)
            self.assertEqual(actual.distance, index * 10)
            self.assertEqual(actual.speed, 10)
            self.assertEqual(actual.power, 0 if 190 <= index < 200
                             else [180, 220, 260][index // 10 % 3])

    def test_manifest_devices_and_resources(self):
        ns = {"iq": "http://www.garmin.com/xml/connectiq"}
        manifest = ET.parse(ROOT / "datafield" / "manifest.xml")
        self.assertEqual({product.attrib["id"] for product in
                          manifest.findall(".//iq:product", ns)},
                         {"edge540", "edge840", "edge1040", "edge1050"})
        self.assertEqual(manifest.find("iq:application", ns).attrib["type"], "datafield")
        for path in (ROOT / "datafield" / "resources").rglob("*.xml"):
            ET.parse(path)


if __name__ == "__main__":
    unittest.main()
