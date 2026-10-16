import secrets
import time
from collections import defaultdict

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.course_message import CourseMessage
from fit_tool.profile.messages.course_point_message import CoursePointMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    CoursePoint, Event, EventType, FileType, Intensity, Manufacturer, Sport,
    WorkoutStepDuration, WorkoutStepTarget,
)

from terrain_coach.models import Plan


def _builder(file_type: FileType, timestamp: int) -> FitFileBuilder:
    builder = FitFileBuilder(auto_define=True, strict=True)
    file_id = FileIdMessage()
    file_id.type = file_type
    file_id.manufacturer = Manufacturer.DEVELOPMENT
    file_id.product = 0
    file_id.serial_number = secrets.randbelow(2**32 - 1)
    file_id.time_created = timestamp
    builder.add(file_id)
    return builder


def _event(builder: FitFileBuilder, timestamp: int, event_type: EventType):
    event = EventMessage()
    event.timestamp = timestamp
    event.event = Event.TIMER
    event.event_type = event_type
    builder.add(event)


def course_fit(plan: Plan) -> bytes:
    timestamp = int(time.time()) * 1000
    builder = _builder(FileType.COURSE, timestamp)
    course = CourseMessage()
    course.course_name = "Terrain Coach"
    course.sport = Sport.CYCLING
    builder.add(course)
    lap = LapMessage()
    lap.message_index = 0
    lap.timestamp = timestamp + round(plan.duration) * 1000
    lap.start_time = timestamp
    lap.total_elapsed_time = plan.duration
    lap.total_timer_time = plan.duration
    lap.total_distance = plan.points[-1].distance
    lap.start_position_lat = plan.points[0].lat
    lap.start_position_long = plan.points[0].lon
    lap.end_position_lat = plan.points[-1].lat
    lap.end_position_long = plan.points[-1].lon
    builder.add(lap)
    _event(builder, timestamp, EventType.START)
    cues = defaultdict(list)
    for cue in plan.cues:
        cues[cue.index].append(cue)
    interval_starts = {s.start: s for s in plan.steps if s.kind == "interval"}
    interval_ends = {s.end: s for s in plan.steps if s.kind == "interval"}
    cue_index = 0
    for index, point in enumerate(plan.points):
        record = RecordMessage()
        record.timestamp = timestamp + round(plan.times[index]) * 1000
        record.position_lat = point.lat
        record.position_long = point.lon
        record.altitude = point.elevation
        record.distance = point.distance
        builder.add(record)
        for cue in cues[index]:
            course_point = CoursePointMessage()
            course_point.message_index = cue_index
            course_point.timestamp = record.timestamp
            course_point.position_lat = point.lat
            course_point.position_long = point.lon
            course_point.distance = point.distance
            course_point.type = CoursePoint.GENERIC
            name = cue.text
            if cue.kind == "interval":
                step = interval_starts[index]
                name = f"{step.low}-{step.high}W start"
            elif cue.kind == "interval_end":
                step = interval_ends[index]
                name = f"End {step.low}-{step.high}W"
            elif cue.kind == "turnaround":
                name = "TURN AROUND"
                course_point.type = CoursePoint.U_TURN
            elif cue.kind == "shift":
                name = cue.text.replace("Shift down, ", "Down ").replace("Shift up, ", "Up ").replace(" ramp", "")
            course_point.course_point_name = name
            builder.add(course_point)
            cue_index += 1
    _event(builder, timestamp + round(plan.duration) * 1000, EventType.STOP_ALL)
    return builder.build().to_bytes()


def workout_fit(plan: Plan) -> bytes:
    builder = _builder(FileType.WORKOUT, int(time.time()) * 1000)
    workout = WorkoutMessage()
    workout.workout_name = "Terrain Coach"
    workout.sport = Sport.CYCLING
    workout.num_valid_steps = len(plan.steps)
    builder.add(workout)
    for index, planned in enumerate(plan.steps):
        step = WorkoutStepMessage()
        step.message_index = index
        step.workout_step_name = f"{planned.low}-{planned.high}W {planned.kind}"
        step.notes = planned.label + ("; partial terrain/duration match" if planned.partial else "")
        step.intensity = Intensity.RECOVERY if planned.kind == "recovery" else Intensity.ACTIVE
        step.duration_type = WorkoutStepDuration.DISTANCE
        step.duration_distance = (
            round(plan.points[planned.end].distance * 100) - round(plan.points[planned.start].distance * 100)
        ) / 100
        step.target_type = WorkoutStepTarget.POWER
        step.target_power_zone = 0
        # FIT distinguishes absolute watts from % FTP by adding 1000.
        step.custom_target_power_low = 1000 + planned.low
        step.custom_target_power_high = 1000 + planned.high
        builder.add(step)
    return builder.build().to_bytes()
