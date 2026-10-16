import bisect
import html
import math
from dataclasses import asdict

from terrain_coach.models import Plan, Rider, WorkoutSpec

MILE = 1609.344

TRANSFER_INSTRUCTIONS = """Garmin Edge transfer
1. Unzip the download. Connect the Edge by USB using a data-capable cable.
2. Copy terrain_course.fit and terrain_workout.fit into Garmin/NewFiles on the
   device (not on a memory card unless your model supports that location).
3. Safely eject and restart/disconnect the Edge so it imports both files.
4. In the cycling activity, load the course under Navigation/Courses, then load
   the workout under Training/Workouts. Start both from the same course start,
   with the workout at step 1. Menu names vary by Edge model.
5. Enable course-point alerts. Test a short course/workout before a long ride.

Garmin Connect alternative: use the website's Training & Planning > Courses >
Import for the course FIT if supported by your version, then Send to Device /
sync with Garmin Express or the official Garmin Connect app. Course import
support varies; USB is the reliable offline path. Garmin Connect does not
generally import arbitrary workout FIT files; transfer that file over USB.

Distance steps follow recorded wheel/GPS distance, not map position. Detours,
auto-pause, GPS drift, or starting away from the course start can desynchronize
the two. Rejoin and manually advance steps if necessary. Device firmware may
truncate cue text or impose workout-step limits. Terrain Coach does not upload
anything or log into Garmin Connect.
"""


def clock(seconds: float) -> str:
    value = round(seconds)
    return f"{value // 3600}:{value // 60 % 60:02d}:{value % 60:02d}"


def plan_summary(plan: Plan, rider: Rider, spec: WorkoutSpec) -> dict:
    return {
        "distance_m": plan.points[-1].distance,
        "estimated_seconds": plan.duration,
        "average_watts": plan.average_power,
        "rider": rider.model_dump(),
        "spec": spec.model_dump(),
        "warnings": plan.warnings,
        "turnaround_distance_m": plan.points[plan.turnaround].distance if plan.turnaround is not None else None,
        "steps": [
            {
                **asdict(step),
                "start_distance_m": plan.points[step.start].distance,
                "end_distance_m": plan.points[step.end].distance,
                "start_seconds": plan.times[step.start],
                "estimated_seconds": plan.times[step.end] - plan.times[step.start],
            } for step in plan.steps
        ],
        "cues": [
            {**asdict(cue), "distance_m": plan.points[cue.index].distance,
             "estimated_seconds": plan.times[cue.index]} for cue in plan.cues
        ],
    }


def cue_sheet(plan: Plan, rider: Rider, spec: WorkoutSpec) -> str:
    escape = html.escape
    length = plan.points[-1].distance
    elevations = [p.elevation for p in plan.points]
    bottom, top = min(elevations) - 5, max(elevations) + 5

    def x(distance):
        return 40 + distance / length * 920

    def y(elevation):
        return 220 - (elevation - bottom) / (top - bottom) * 190

    stride = max(1, len(plan.points) // 1200)
    sampled = plan.points[::stride]
    if sampled[-1] is not plan.points[-1]:
        sampled.append(plan.points[-1])
    profile = " ".join(f"{x(p.distance):.1f},{y(p.elevation):.1f}" for p in sampled)
    shading, intervals = [], []
    for step in plan.steps:
        if step.kind != "interval":
            continue
        start, end = plan.points[step.start], plan.points[step.end]
        shading.append(
            f'<rect x="{x(start.distance):.1f}" y="20" width="{x(end.distance)-x(start.distance):.1f}" '
            f'height="210" fill="#ed974c" opacity=".35"><title>{escape(step.label)}</title></rect>'
        )
        grades = [p.grade for p in plan.points[step.start:step.end]]
        intervals.append(
            f"<tr><td>{escape(step.label)}{' (partial match)' if step.partial else ''}</td>"
            f"<td>{start.distance / MILE:.2f}–{end.distance / MILE:.2f}</td>"
            f"<td>{clock(plan.times[step.start])}</td>"
            f"<td>{clock(plan.times[step.end] - plan.times[step.start])} / {clock(step.requested_seconds)}</td>"
            f"<td>{step.low}–{step.high}</td><td>{min(grades):.1%} to {max(grades):.1%}</td></tr>"
        )
    distances = [p.distance for p in plan.points]
    energy = [0.0]
    for power, start, end in zip(plan.powers, plan.times, plan.times[1:]):
        energy.append(energy[-1] + power * (end - start))

    def sample(distance):
        i = min(len(distances) - 2, max(0, bisect.bisect_right(distances, distance) - 1))
        fraction = (distance - distances[i]) / (distances[i + 1] - distances[i])
        return (
            elevations[i] + fraction * (elevations[i + 1] - elevations[i]),
            plan.times[i] + fraction * (plan.times[i + 1] - plan.times[i]),
            energy[i] + fraction * (energy[i + 1] - energy[i]),
        )

    splits = []
    for mile in range(math.ceil(length / MILE)):
        start, end = mile * MILE, min(length, (mile + 1) * MILE)
        elevation_a, time_a, energy_a = sample(start)
        elevation_b, time_b, energy_b = sample(end)
        splits.append(
            f"<tr><td>{start / MILE:.2f}–{end / MILE:.2f}</td>"
            f"<td>{(elevation_b-elevation_a)/(end-start):.1%}</td>"
            f"<td>{(energy_b-energy_a)/(time_b-time_a):.0f}</td>"
            f"<td>{clock(time_b-time_a)}</td><td>{clock(time_b)}</td></tr>"
        )
    fueling = "".join(
        f"<tr><td>{clock(seconds)}</td><td>6 US fl oz (177 mL)</td><td>14–18 g carbs</td></tr>"
        for seconds in range(1200, math.floor(plan.duration) + 1, 1200)
    )
    cues = "".join(
        f"<tr><td>{plan.points[cue.index].distance / MILE:.2f}</td>"
        f"<td>{clock(plan.times[cue.index])}</td><td>{escape(cue.text)}</td></tr>" for cue in plan.cues
    )
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in plan.warnings)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Terrain Coach cue sheet</title><style>
body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#183c36}}
table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}th,td{{padding:.5rem;text-align:left;border-bottom:1px solid #ccc}}
svg{{width:100%;height:auto}}pre{{white-space:pre-wrap}}.warnings{{background:#fff2d9;padding:1rem 2rem}}
@media print{{body{{margin:0}}tr{{break-inside:avoid}}}}
</style></head><body><h1>Terrain Coach</h1>
<p>{length / MILE:.1f} miles · estimated {clock(plan.duration)} · time-weighted average {plan.average_power:.0f} W.
FTP {rider.ftp:g} W · {rider.surface} · {rider.position} · {spec.route_mode}.</p>
<p>Orange shading marks intervals. Grades use smoothed elevation; times assume still air, no stops,
constant power and no braking (speed capped at 90 km/h). Verify road access and safe turnaround locations.
This is a planning estimate, not a safety or navigation guarantee.</p>
{'<ul class="warnings">' + warnings + '</ul>' if warnings else ''}
<svg viewBox="0 0 1000 260" role="img" aria-label="Elevation profile with shaded intervals">
{''.join(shading)}<polyline points="{profile}" fill="none" stroke="#176554" stroke-width="2"/>
<text x="40" y="252">0 mi</text><text x="870" y="252">{length / MILE:.1f} mi</text>
<text x="40" y="15">Elevation {min(elevations):.0f}–{max(elevations):.0f} m</text></svg>
<h2>Intervals</h2><table><thead><tr><th>Interval</th><th>Mile</th><th>Start</th><th>Estimated / requested</th><th>Target W</th><th>Grade range</th></tr></thead><tbody>{''.join(intervals)}</tbody></table>
<h2>Mile splits</h2><table><thead><tr><th>Mile</th><th>Mean grade</th><th>Target W (time-weighted)</th><th>Split time</th><th>Elapsed</th></tr></thead><tbody>{''.join(splits)}</tbody></table>
<h2>Course cues</h2><table><thead><tr><th>Mile</th><th>Elapsed</th><th>Cue</th></tr></thead><tbody>{cues}</tbody></table>
<h2>Fueling timeline</h2><p>Example only: every 20 minutes, 6 oz fluid and 14–18 g carbohydrates.
Adjust for heat, sweat rate, tolerance and your nutrition needs. Start fueled and hydrated.</p>
<table><thead><tr><th>Elapsed</th><th>Fluid</th><th>Carbohydrate</th></tr></thead><tbody>{fueling}</tbody></table>
<h2>Load on your Edge</h2><pre>{escape(TRANSFER_INSTRUCTIONS)}</pre></body></html>"""
