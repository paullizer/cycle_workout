using Toybox.Graphics;
using Toybox.WatchUi;

class TerrainCoachField extends WatchUi.DataField {
    var model;
    var _running = true;

    function initialize() {
        DataField.initialize();
        model = new CoachModel();
    }

    function compute(info) {
        if (_running) { model.updatePower(info.currentPower, info.timerTime); }
        if (info has :nameOfNextPoint && info has :distanceToNextPoint) {
            model.updateCourse(info.nameOfNextPoint, info.distanceToNextPoint,
                info.elapsedDistance, info.currentSpeed);
        } else {
            model.resetCourse();
        }
    }

    function onTimerReset() {
        model.resetCourse();
        model.resetPower();
    }

    function onTimerStop() {
        _running = false;
        model.resetPower();
    }

    function onTimerStart() {
        _running = true;
        model.resetPower();
    }

    function onTimerPause() {
        onTimerStop();
    }

    function onTimerResume() {
        onTimerStart();
    }

    function line(dc, text, y, color, height) {
        var font = Graphics.FONT_SMALL;
        if (dc.getFontHeight(font) > height ||
            dc.getTextWidthInPixels(text, font) > dc.getWidth() - 8) {
            font = Graphics.FONT_TINY;
        }
        while (text.length() > 0 && dc.getTextWidthInPixels(text, font) > dc.getWidth() - 8) {
            text = text.substring(0, text.length() - 1);
        }
        dc.setColor(color, Graphics.COLOR_BLACK);
        dc.drawText(dc.getWidth() / 2, y, font, text, Graphics.TEXT_JUSTIFY_CENTER);
    }

    function onUpdate(dc) {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();
        var zone = model.zone();
        var color = Graphics.COLOR_WHITE;
        if (zone.equals("UNDER")) { color = Graphics.COLOR_BLUE; }
        if (zone.equals("IN")) { color = Graphics.COLOR_GREEN; }
        if (zone.equals("OVER")) { color = Graphics.COLOR_RED; }
        var watts = model.power == null ? "--" : model.power.format("%d");
        var target = model.active ? model.low.format("%d") + "-" + model.high.format("%d") + "W" : "No interval";
        var cue = "No course / cue";
        if (model.navigating) {
            cue = model.next == null ? "Unknown course cue" : "Next " + model.nextDistance.format("%.0f") + "m";
        }
        if (model.countdown != null) {
            cue = "Start " + (model.countdown / 60).toNumber().format("%d") + ":" +
                (model.countdown % 60).format("%02d");
        } else if (model.next != null && model.next[0].equals("S") && !model.active) {
            cue = "Start " + model.nextDistance.format("%.0f") + "m";
        }
        if (model.shift != null) {
            cue = "Shift " + model.shift + " " + model.nextDistance.format("%.0f") + "m";
        }
        var height = dc.getHeight() / 3;
        line(dc, "3s " + watts + "W " + zone, 0, color, height);
        line(dc, target, height, Graphics.COLOR_WHITE, height);
        line(dc, cue, height * 2, Graphics.COLOR_WHITE, height);
    }
}
