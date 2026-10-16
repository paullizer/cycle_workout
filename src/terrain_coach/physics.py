import math

from terrain_coach.models import Point, Rider


def estimate_speed(power: float, grade: float, rider: Rider) -> float:
    """Steady-state ground speed (m/s), still air, 97% drivetrain efficiency."""
    if not math.isfinite(power) or power < 0 or not math.isfinite(grade):
        raise ValueError("Power must be nonnegative and grade must be finite.")
    angle = math.atan(grade)
    crr = {"road": 0.004, "gravel": 0.008}[rider.surface]
    cda = {"upright": 0.45, "hoods": 0.32, "drops": 0.28, "aero": 0.22}[rider.position]
    force = rider.mass_kg * 9.80665 * (math.sin(angle) + crr * math.cos(angle))
    lo, hi = 0.0, 25.0
    for _ in range(40):
        speed = (lo + hi) / 2
        watts = (force + 0.5 * 1.225 * cda * speed**2) * speed
        if watts < power * 0.97:
            lo = speed
        else:
            hi = speed
    return max(0.1, (lo + hi) / 2)


def segment_times(points: list[Point], powers: list[float], rider: Rider) -> list[float]:
    if len(powers) != len(points) - 1:
        raise ValueError("One power target is required per route segment.")
    cache = {}
    times = [0.0]
    for a, b, power in zip(points, points[1:], powers):
        key = (power, round(a.grade, 4))
        if key not in cache:
            cache[key] = estimate_speed(power, key[1], rider)
        times.append(times[-1] + (b.distance - a.distance) / cache[key])
    return times
