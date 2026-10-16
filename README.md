# Terrain Coach

A local FastAPI web app that turns a GPX, TCX, or FIT route into a terrain-aware
cycling course and distance-based Garmin Edge workout. No accounts, cloud calls,
maps API, or Garmin Connect scraping. Route files and generated files are
processed in memory and are not retained by the app.

## Run locally

Requires Python 3.12 or newer. From your checkout:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/terrain-coach
```

Open **http://127.0.0.1:8000**. On Windows, use `.venv\Scripts\python.exe` and
`.venv\Scripts\terrain-coach.exe` instead. Dependencies need internet access at
installation time; the installed app and its UI work offline. The server binds
only to loopback; do not expose it to a public network.

1. Export a route with GPS coordinates **and elevation** from Ride with GPS,
   Garmin Connect, Strava, Komoot, or another route planner.
2. Select a GPX, TCX, or FIT file (maximum 10 MiB, 500 km before any return leg).
   FIT courses and recorded activities with GPS records are supported.
3. Enter your FTP, rider/bike weights, surface, and riding position. Defaults:
   **238 W FTP, 184.8 lb rider, 20 lb bike + gear, gravel, hoods**.
4. Set the duration range (for example **2:30–2:45**) and endurance band in
   **% FTP or watts**. Add interval sets with count, duration, watt range,
   recovery, and earliest placement times. For example: 3 × 10 minutes at
   210–230 W, 5-minute recoveries, last interval after **2:00**.
5. Choose **truncate** to follow the supplied route until the target duration,
   or **out-and-back** to treat it as the outbound leg and return along it.
   Out-and-back always includes the return, even when the uploaded path is short.
   Truncation does **not** plan a ride home.
6. Download and unzip the bundle; open `cue_sheet.html` locally and inspect
   warnings, partial matches, and turnaround safety before riding.

## Output bundle

- `terrain_course.fit`: GPS/elevation course with predicted timestamps and
  course points for interval starts/ends (including watt targets), turnaround
  or truncation, and advance shift cues.
- `terrain_workout.fit`: cycling workout with distance-based steps and absolute
  power ranges, using exactly the same distance boundaries as the course.
- `cue_sheet.html`: self-contained elevation chart with shaded intervals,
  interval details, mile/grade/target-power/time splits, course cues, fueling
  timeline, and transfer instructions. Print it from your browser if desired.
- `plan.json`: inputs, estimated distance/duration/average power, step boundaries,
  cues, and warnings for inspection or further local processing.
- `EDGE_TRANSFER.txt`: offline device-loading instructions.

The fueling example is **6 US fl oz (177 mL) fluid and 14–18 g carbs every
20 minutes**. Adjust to your conditions and needs; it is not personalized
nutrition advice.

## Planning model and limitations

- Coordinates are resampled about every 10 m using horizontal great-circle
  distance. Local linear regression smooths elevation over about 60 m;
  centered rise/run estimates grade. Missing elevation is rejected rather than
  silently assumed flat. GPS/elevation quality still matters.
- Speed balances gravity, rolling resistance, and aerodynamic drag at 97%
  drivetrain efficiency, air density 1.225 kg/m³, and no wind. Rolling resistance
  coefficients: road 0.004, gravel 0.008. CdA: upright 0.45, hoods 0.32,
  drops 0.28, aero 0.22 m². Speed is capped at 25 m/s (90 km/h).
  Stops, intersections, acceleration, braking, technical terrain, and weather
  are not modeled. Estimated durations are not promises.
- Long routes are searched for a duration-matching truncation or turnaround,
  including the speed effects of work intervals and recoveries. A route too
  short is not padded with invented loops; the cue sheet warns instead.
- Candidates favor climbs/false flats (−0.5% to 15%) whose grade range stays
  inside the selected variation band (default 1.5 percentage points). Scoring
  considers steadiness, interval length match, and spacing. Intervals never
  cross the turnaround. Placement is a greedy heuristic, not a global optimizer.
  When necessary, shorter steady segments or less steady full segments are
  explicitly marked as partial matches. Impossible timing rules omit that
  interval with a warning; later intervals still remain eligible.
- Recoveries use 55% FTP. “After” times are earliest **interval start times**
  on the estimated ride clock; “last after” applies to the last repetition of
  that set. Distance steps mean actual interval time varies with real speed.
- Endurance targets rise on climbs and ease on descents, grouped into practical
  distance steps. They remain in the requested band and are adjusted to budget
  for work/recovery power. Explicit interval/recovery targets take priority;
  when the whole-session time-weighted average falls outside the band, the
  cue sheet warns. Not every interval prescription can have an endurance-band
  session average.
- Shift cues look 200 m ahead for a grade change of at least 3 percentage
  points, with 400 m spacing to avoid repeated alerts. They are suggestions,
  not knowledge of your gearing.
- An out-and-back is a geometric reversal, **not** a check for one-way streets,
  legal access, trail direction, or safe turning locations. Check the route.

## Load onto a Garmin Edge

1. Connect the Edge by USB with a data-capable cable.
2. Copy both `.fit` files into **Garmin/NewFiles** on the device.
3. Safely eject and disconnect/restart it to import the files.
4. In the cycling activity, load the course through **Navigation → Courses**
   and the workout through **Training → Workouts**. Menus differ by model.
5. Begin the course and workout together at the course start, with workout step
   1 selected. Enable course-point alerts. Test a short workout first.

Distance-based workouts advance on accumulated device distance, not geographic
position. Starting elsewhere, detouring, GPS drift, or auto-pause can misalign
the workout and course; rejoin and manually advance steps when needed. Edge
firmware may shorten cue text or limit workout steps; plans over 200 steps
include a warning. Both files use the official FIT profile via `fit-tool`;
device behavior still needs verification on your particular Edge.

**Garmin Connect alternative:** on the official website, use
**Training & Planning → Courses → Import** for the course FIT if supported,
then **Send to Device** and sync through the official app or Garmin Express.
Course-import formats vary; USB works offline. Connect generally does not
import arbitrary workout FIT files, so use USB for the workout.

## Local API

`POST /plan` accepts multipart fields `route` (file), `rider` (JSON), and `spec`
(JSON) and returns the same ZIP. Omit the JSON fields for defaults (endurance
only). Durations/offsets are seconds, weights pounds, powers watts, grade a
fraction. `/docs` provides offline API help.

Example spec:

```json
{
  "duration_min_seconds": 9000,
  "duration_max_seconds": 9900,
  "endurance_low": 60,
  "endurance_high": 72,
  "endurance_unit": "percent",
  "route_mode": "out-and-back",
  "grade_tolerance": 0.015,
  "intervals": [
    {
      "count": 3,
      "duration_seconds": 600,
      "power_low": 210,
      "power_high": 230,
      "recovery_seconds": 300,
      "after_seconds": 0,
      "last_after_seconds": 7200
    }
  ]
}
```

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover grade calculation, speed/power balance, route parsing, placement
rules/recoveries/partial matches, duration handling, FIT round trips and
course/workout distance alignment, cue-sheet content, and local HTTP validation.