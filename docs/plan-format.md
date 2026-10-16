# Terrain Coach course-point format

Every generated course-point name is ASCII and no longer than 16 characters,
matching the limit confirmed on the rider's Edge. FIT and Connect IQ distances
are metres; target powers are absolute watts.

| Name pattern | Meaning |
| --- | --- |
| `INT2 GO 205-219W` | Start interval 2 at 205–219 W |
| `INT2 END` | End interval 2 |
| `TURN PRESS LAP` | Turnaround |
| `SHIFT EASY 5%` / `SHIFT HARD -3%` | Shift cue at the indicated grade |
| `COURSE END` | Truncated course/workout finish |

Interval numbers count planned intervals in course order. If a start name with
four-digit watt bounds would exceed 16 characters, it uses the compact
`I2 GO 2000-2000` form instead. Long shift grades use `SHIFT E <grade>%` or
`SHIFT H <grade>%` to remain within the same limit. Interval bounds are integers
from 1 through 2000, with low <= high. A turnaround uses the FIT U-turn point
type; other names use generic points.

`plan.json` includes a `course_points` array with one entry for each FIT course
point. Each entry has `distance_m`, semantic `type`, `target_watts` (an object
with `low` and `high` for interval boundaries, otherwise `null`), `name`,
`fit_type`, and the source `point_index`.

The data field also accepts the older `S low-high` / `E low-high`,
`Down ...` / `Up ...`, `low-highW start`, and `End low-highW` names used by
existing courses. S/E markers refer to **course distance**, not elapsed workout
time. The field observes the next
point and distance exposed by `Activity.Info`; it cannot scan ahead through the
entire course. A start is applied when its distance reaches zero, or when the
next point changes after ridden distance passes its previously observed
position. An end clears the target by the same rule. Unknown points do not
themselves change interval state. Losing navigation data clears the state.
Starting mid-interval or missing a boundary cannot reliably reconstruct state;
restart navigation from before a start to resynchronize.

The start countdown is distance / current speed (an estimate, not the planner's
predicted ride clock), and is only available while the **next point** is an
interval start. An intervening shift/turn point hides a later start. Shift
suggestions are shown when the next point is a shift and its distance is <=
300 m. Firmware may skip points, replace them with navigation instructions, or
report no point. The field is advisory, not a replacement for the distance-based
FIT workout.
