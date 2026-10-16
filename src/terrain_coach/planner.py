import bisect
import math
from collections import deque

from terrain_coach.models import Cue, Plan, Point, Rider, Step, WorkoutSpec
from terrain_coach.physics import segment_times
from terrain_coach.route import cut_route


def endurance_targets(points: list[Point], rider: Rider, spec: WorkoutSpec) -> list[float]:
    low, high = spec.endurance_watts(rider)
    midpoint = (low + high) / 2
    adjustments = [max(-1, min(1, p.grade / 0.05)) * (high - low) / 2 for p in points[:-1]]
    reference_times = segment_times(points, [midpoint] * (len(points) - 1), rider)
    durations = [b - a for a, b in zip(reference_times, reference_times[1:])]
    work_seconds = sum(s.count * (s.duration_seconds + s.recovery_seconds) for s in spec.intervals)
    work_energy = sum(s.count * (
        s.duration_seconds * (s.power_low + s.power_high) / 2
        + s.recovery_seconds * round(rider.ftp * 0.55)
    ) for s in spec.intervals)
    session_time = min(reference_times[-1], (spec.duration_min_seconds + spec.duration_max_seconds) / 2)
    endurance_time = max(1, session_time - work_seconds)
    desired = max(low, min(high, (midpoint * session_time - work_energy) / endurance_time))
    lo, hi = -(high - low), high - low
    for _ in range(16):
        offset = (lo + hi) / 2
        targets = [max(low, min(high, midpoint + a + offset)) for a in adjustments]
        average = sum(p * dt for p, dt in zip(targets, durations)) / reference_times[-1]
        if average < desired:
            lo = offset
        else:
            hi = offset
    return targets


def steady_ends(points: list[Point], tolerance: float) -> list[int]:
    """Longest climb/false-flat window starting at each segment, in O(n)."""
    n = len(points) - 1
    minimum, maximum = deque(), deque()
    ends = []
    end = 0
    for start in range(n):
        while end < n:
            grade = points[end].grade
            if not -0.005 <= grade <= 0.15:
                break
            low = min(grade, points[minimum[0]].grade) if minimum else grade
            high = max(grade, points[maximum[0]].grade) if maximum else grade
            if high - low > tolerance:
                break
            while minimum and points[minimum[-1]].grade >= grade:
                minimum.pop()
            while maximum and points[maximum[-1]].grade <= grade:
                maximum.pop()
            minimum.append(end)
            maximum.append(end)
            end += 1
        ends.append(end)
        if minimum and minimum[0] == start:
            minimum.popleft()
        if maximum and maximum[0] == start:
            maximum.popleft()
        end = max(end, start + 1)
    return ends


def find_interval(
    points: list[Point], times: list[float], rider: Rider, power: float,
    seconds: float, earliest: int, ideal_time: float, tolerance: float,
    turnaround: int | None,
) -> tuple[int, int, bool] | None:
    n = len(points) - 1
    if earliest >= n:
        return None
    power_times = segment_times(points, [power] * n, rider)
    ends = steady_ends(points, tolerance)
    sums, squares = [0.0], [0.0]
    for point in points[:-1]:
        sums.append(sums[-1] + point.grade)
        squares.append(squares[-1] + point.grade**2)
    best = None
    best_score = -math.inf
    for start in range(earliest, n):
        desired = bisect.bisect_left(power_times, power_times[start] + seconds)
        limit = turnaround if turnaround is not None and start < turnaround else n
        steady_end = min(ends[start], limit)
        end = min(desired, steady_end)
        steady = end > start
        if not steady:
            end = min(desired, limit)
        if end <= start:
            continue
        actual = power_times[end] - power_times[start]
        fraction = min(1, actual / seconds)
        if actual < min(10, seconds):
            continue
        count = end - start
        mean = (sums[end] - sums[start]) / count
        variance = max(0, (squares[end] - squares[start]) / count - mean**2)
        score = (
            100 * fraction + (25 if steady else 0) - 1000 * math.sqrt(variance)
            - 15 * abs(times[start] - ideal_time) / max(1, times[-1])
            - 5 * abs(actual - seconds) / seconds
        )
        if score > best_score:
            best_score = score
            best = (start, end, not steady or fraction < 0.98)
    return best


def _plan_path(points: list[Point], turnaround: int | None, rider: Rider, spec: WorkoutSpec) -> Plan:
    powers = endurance_targets(points, rider, spec)
    distances = [p.distance for p in points]
    chunk_length = max(1000, distances[-1] / 100)
    base_times = segment_times(points, powers, rider)
    start = 0
    while start < len(powers):
        stop = min(len(powers), bisect.bisect_left(distances, distances[start] + chunk_length))
        elapsed = base_times[stop] - base_times[start]
        target = round(sum(
            powers[i] * (base_times[i + 1] - base_times[i]) for i in range(start, stop)
        ) / elapsed)
        powers[start:stop] = [target] * (stop - start)
        start = stop
    base_powers = powers[:]
    n = len(powers)
    occupied = []
    warnings = []
    cursor = 0
    total = sum(s.count for s in spec.intervals)
    number = 0
    for set_number, interval_set in enumerate(spec.intervals, 1):
        for repetition in range(interval_set.count):
            number += 1
            times = segment_times(points, powers, rider)
            after = interval_set.after_seconds
            if repetition == interval_set.count - 1:
                after = max(after, interval_set.last_after_seconds)
            earliest = max(cursor, bisect.bisect_left(times, after))
            ideal = max(after, times[-1] * number / (total + 1))
            candidate = find_interval(
                points, times, rider, (interval_set.power_low + interval_set.power_high) / 2,
                interval_set.duration_seconds, earliest, ideal, spec.grade_tolerance, turnaround,
            )
            label = f"Set {set_number}, interval {repetition + 1}"
            if candidate is None:
                warnings.append(f"{label}: cannot fit after its timing/recovery constraints; omitted.")
                continue
            start, end, partial = candidate
            step = Step(start, end, "interval", interval_set.power_low, interval_set.power_high,
                        label, interval_set.duration_seconds, partial)
            occupied.append(step)
            powers[start:end] = [step.power] * (end - start)
            if partial:
                warnings.append(f"{label}: best partial terrain/duration match; inspect the cue sheet.")
            cursor = end
            if interval_set.recovery_seconds:
                recovery_power = max(1, round(rider.ftp * 0.55))
                recovery_times = segment_times(points, [recovery_power] * n, rider)
                recovery_end = min(n, bisect.bisect_left(
                    recovery_times, recovery_times[end] + interval_set.recovery_seconds,
                ))
                if recovery_end > end:
                    recovery = Step(end, recovery_end, "recovery", recovery_power, recovery_power,
                                    "Recovery", interval_set.recovery_seconds)
                    occupied.append(recovery)
                    powers[end:recovery_end] = [recovery_power] * (recovery_end - end)
                if recovery_times[-1] - recovery_times[end] < interval_set.recovery_seconds:
                    warnings.append(f"{label}: final recovery shortened by the course end.")
                cursor = recovery_end

    steps = []
    cursor = 0

    def endurance(start, end):
        while start < end:
            target = base_powers[start]
            stop = start + 1
            while stop < end and base_powers[stop] == target:
                stop += 1
            steps.append(Step(start, stop, "endurance", target, target, "Endurance"))
            start = stop

    for step in occupied:
        endurance(cursor, step.start)
        steps.append(step)
        cursor = step.end
    endurance(cursor, n)
    times = segment_times(points, powers, rider)

    plan = Plan(points, steps, times, powers, warnings, turnaround=turnaround)
    if len(steps) > 200:
        plan.warnings.append("More than 200 workout steps: check your Edge's workout step limit.")
    return plan


def plan_workout(points: list[Point], rider: Rider, spec: WorkoutSpec) -> Plan:
    out_and_back = spec.route_mode == "out-and-back"
    full_distance = points[-1].distance
    path, turnaround = cut_route(points, full_distance, out_and_back)
    plan = _plan_path(path, turnaround, rider, spec)
    target = (spec.duration_min_seconds + spec.duration_max_seconds) / 2
    if plan.duration > spec.duration_max_seconds:
        lo, hi = 10.0, full_distance
        closest = plan
        for _ in range(16):
            distance = (lo + hi) / 2
            path, turnaround = cut_route(points, distance, out_and_back)
            candidate = _plan_path(path, turnaround, rider, spec)
            if abs(candidate.duration - target) < abs(closest.duration - target):
                closest = candidate
            if candidate.duration > target:
                hi = distance
            else:
                lo = distance
            if abs(candidate.duration - target) < 2:
                break
        plan = closest
    if plan.duration < spec.duration_min_seconds or plan.duration > spec.duration_max_seconds:
        plan.warnings.append("Estimated duration is outside the requested range; route length or interval rules prevent an exact match.")
    if plan.turnaround is not None:
        plan.cues.append(Cue(plan.turnaround, "Turn around — return along the course", "turnaround"))
    elif plan.points[-1].distance < full_distance - 1:
        plan.cues.append(Cue(len(plan.points) - 1, "Truncation / workout finish", "finish"))
    for step in plan.steps:
        if step.kind == "interval":
            target_text = f"{step.low}-{step.high} W"
            plan.cues.append(Cue(step.start, f"{step.label}: {target_text}", "interval"))
            plan.cues.append(Cue(step.end, f"Interval end: {target_text}", "interval_end"))
    distances = [p.distance for p in plan.points]
    last_cue = -1000.0
    for i, point in enumerate(plan.points[:-1]):
        ahead = bisect.bisect_left(distances, point.distance + 200)
        if ahead >= len(plan.points):
            break
        change = plan.points[ahead].grade - point.grade
        if abs(change) >= 0.03 and point.distance - last_cue >= 400:
            direction = "down" if change > 0 else "up"
            plan.cues.append(Cue(i, f"Shift {direction}, {plan.points[ahead].grade:.0%} ramp in 200 m", "shift"))
            last_cue = point.distance
    plan.cues.sort(key=lambda cue: cue.index)
    low, high = spec.endurance_watts(rider)
    if not low <= plan.average_power <= high:
        plan.warnings.append(
            "Whole-session average is outside the endurance band because interval/recovery targets take priority; "
            "endurance-only steps stay inside the band."
        )
    return plan
