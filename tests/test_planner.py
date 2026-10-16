import unittest

from terrain_coach.models import IntervalSet, Point, Rider, WorkoutSpec
from terrain_coach.physics import segment_times
from terrain_coach.planner import find_interval, plan_workout
from terrain_coach.route import assign_grades


def flat_route(length=20000):
    return assign_grades([Point(0, i * 10 / 111195, 100, i * 10) for i in range(length // 10 + 1)])


class PlacementTests(unittest.TestCase):
    def test_intervals_recoveries_and_last_after_rule(self):
        rider = Rider()
        spec = WorkoutSpec(
            duration_min_seconds=60, duration_max_seconds=7200,
            intervals=[IntervalSet(count=3, duration_seconds=120, recovery_seconds=60,
                                   last_after_seconds=1800)],
        )
        plan = plan_workout(flat_route(), rider, spec)
        intervals = [s for s in plan.steps if s.kind == "interval"]
        recoveries = [s for s in plan.steps if s.kind == "recovery"]
        self.assertEqual(len(intervals), 3)
        self.assertEqual(len(recoveries), 3)
        self.assertGreaterEqual(plan.times[intervals[-1].start], 1800)
        for step in intervals:
            self.assertGreaterEqual(plan.times[step.end] - plan.times[step.start], 120)
            self.assertFalse(step.partial)
        for step in recoveries:
            self.assertGreaterEqual(plan.times[step.end] - plan.times[step.start], 60)
        for a, b in zip(plan.steps, plan.steps[1:]):
            self.assertEqual(a.end, b.start)
        self.assertEqual(plan.steps[0].start, 0)
        self.assertEqual(plan.steps[-1].end, len(plan.points) - 1)
        for step in plan.steps:
            self.assertTrue(all(p == step.power for p in plan.powers[step.start:step.end]))

    def test_multiple_sets_with_identical_settings_have_unique_labels(self):
        interval = IntervalSet(count=1, duration_seconds=60, recovery_seconds=0)
        plan = plan_workout(flat_route(), Rider(), WorkoutSpec(
            duration_min_seconds=60, duration_max_seconds=7200, intervals=[interval, interval],
        ))
        self.assertEqual([s.label for s in plan.steps if s.kind == "interval"],
                         ["Set 1, interval 1", "Set 2, interval 1"])

    def test_impossible_rule_is_reported_not_violated(self):
        plan = plan_workout(flat_route(2000), Rider(), WorkoutSpec(
            duration_min_seconds=60, duration_max_seconds=7200,
            intervals=[IntervalSet(count=1, last_after_seconds=7200)],
        ))
        self.assertFalse(any(s.kind == "interval" for s in plan.steps))
        self.assertTrue(any("omitted" in w for w in plan.warnings))

    def test_partial_match_on_short_route(self):
        plan = plan_workout(flat_route(500), Rider(), WorkoutSpec(
            duration_min_seconds=60, duration_max_seconds=7200,
            intervals=[IntervalSet(count=1, duration_seconds=600, recovery_seconds=0)],
        ))
        intervals = [s for s in plan.steps if s.kind == "interval"]
        self.assertEqual(len(intervals), 1)
        self.assertTrue(intervals[0].partial)
        self.assertTrue(any("partial" in w for w in plan.warnings))

    def test_steady_climb_preferred_and_turnaround_not_crossed(self):
        points = flat_route(6000)
        for i, point in enumerate(points):
            point.grade = (0.03 if 200 <= i < 400 else (0.02 if i % 2 else 0.12))
        times = segment_times(points, [160] * (len(points) - 1), Rider())
        candidate = find_interval(points, times, Rider(), 220, 120, 0, times[-1] / 2, 0.015, 350)
        self.assertIsNotNone(candidate)
        start, end, partial = candidate
        self.assertGreaterEqual(start, 200)
        self.assertLessEqual(end, 350)
        self.assertFalse(partial)

    def test_truncation_and_out_and_back_hit_duration(self):
        for mode in ("truncate", "out-and-back"):
            with self.subTest(mode=mode):
                spec = WorkoutSpec(duration_min_seconds=590, duration_max_seconds=610, route_mode=mode)
                plan = plan_workout(flat_route(), Rider(), spec)
                self.assertTrue(590 <= plan.duration <= 610)
                if mode == "out-and-back":
                    self.assertIsNotNone(plan.turnaround)
                    self.assertAlmostEqual(plan.points[0].lon, plan.points[-1].lon)
                    self.assertTrue(any(c.kind == "turnaround" for c in plan.cues))
                else:
                    self.assertLess(plan.points[-1].distance, 20000)
                    self.assertTrue(any(c.kind == "finish" for c in plan.cues))

    def test_endurance_band_and_infeasible_session_average(self):
        rider = Rider()
        spec = WorkoutSpec(duration_min_seconds=60, duration_max_seconds=7200)
        plan = plan_workout(flat_route(1000), rider, spec)
        low, high = spec.endurance_watts(rider)
        self.assertTrue(low <= plan.average_power <= high)
        spec.intervals = [IntervalSet(count=1, duration_seconds=300, power_low=500, power_high=600,
                                      recovery_seconds=0)]
        plan = plan_workout(flat_route(1000), rider, spec)
        self.assertTrue(any("Whole-session average" in w for w in plan.warnings))
