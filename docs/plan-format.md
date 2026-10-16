# Terrain Coach course-point format

Course FIT `course_point_name` values use this ASCII convention (watts are
absolute, distances in FIT and Connect IQ are metres):

| Name | Meaning |
| --- | --- |
| `S 210-230` | Interval start, inclusive target 210–230 W |
| `E 210-230` | Interval end, repeating the interval target |
| `Down 6%` / `Up -3%` | Shift down/up suggestion |
| `TURN AROUND` | Turnaround, not an interval boundary |

Bounds are integers from 1 through 2000, low <= high. No suffix is allowed on
S/E names. Short names keep the important information before device truncation.
The data field also accepts the original planner names `210-230W start` and
`End 210-230W`. Other names, including truncated/malformed bounds, are ignored.
Shift grade text is informational; only the `Down ` / `Up ` prefix is parsed.

S/E markers refer to **course distance**, not elapsed workout time. The field
observes the next point and distance exposed by `Activity.Info`; it cannot scan
ahead through the entire course. A start is applied when its distance reaches
zero, or when the next point changes after ridden distance passes its previously
observed position. An end clears the target by the same rule. Unknown points do
not themselves change interval state. Losing navigation data clears the state.
Starting mid-interval or missing a boundary cannot reliably reconstruct state;
restart navigation from before a start to resynchronize.

The start countdown is distance / current speed (an estimate, not the planner's
predicted ride clock), and is only available while the **next point** is S.
An intervening shift/turn point hides a later start. Shift suggestions are shown
when the next point is a shift and its distance is <= 300 m. Firmware may skip
points, replace them with navigation instructions, or report no point.
The field is advisory, not a replacement for the distance-based FIT workout.
