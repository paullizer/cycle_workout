using Toybox.Math;

class CoachModel {
    var active = false;
    var low = null;
    var high = null;
    var power = null;
    var next = null;
    var nextDistance = null;
    var countdown = null;
    var shift = null;
    var navigating = false;
    var _name = null;
    var _position = null;
    var _cue = null;
    var _applied = false;
    var _lastDistance = null;
    var _samples;
    var _times;
    var _slot = 0;
    var _lastTime = null;

    function initialize() {
        resetPower();
    }

    function resetPower() {
        _samples = [null, null, null];
        _times = [null, null, null];
        _slot = 0;
        _lastTime = null;
        power = null;
    }

    function resetCourse() {
        active = false;
        low = null;
        high = null;
        next = null;
        nextDistance = null;
        countdown = null;
        shift = null;
        navigating = false;
        _name = null;
        _position = null;
        _cue = null;
        _applied = false;
        _lastDistance = null;
    }

    function digits(text) {
        if (text.length() == 0 || text.length() > 4) { return null; }
        for (var i = 0; i < text.length(); i += 1) {
            var c = text.substring(i, i + 1);
            if ("0123456789".find(c) == null) { return null; }
        }
        return text.toNumber();
    }

    function bounds(kind, text) {
        var dash = text.find("-");
        if (dash == null) { return null; }
        var a = digits(text.substring(0, dash));
        var b = digits(text.substring(dash + 1, text.length()));
        if (a == null || b == null || a < 1 || b > 2000 || a > b) { return null; }
        return [kind, a, b];
    }

    function parse(name) {
        if (name == null || name.length() < 3) { return null; }
        if (name.substring(0, 2).equals("S ") || name.substring(0, 2).equals("E ")) {
            return bounds(name.substring(0, 1), name.substring(2, name.length()));
        }
        if (name.length() > 7 && name.substring(name.length() - 7, name.length()).equals("W start")) {
            return bounds("S", name.substring(0, name.length() - 7));
        }
        if (name.length() > 5 && name.substring(0, 4).equals("End ") &&
            name.substring(name.length() - 1, name.length()).equals("W")) {
            return bounds("E", name.substring(4, name.length() - 1));
        }
        if (name.length() > 5 && name.substring(0, 5).equals("Down ")) { return ["DOWN", null, null]; }
        if (name.length() > 3 && name.substring(0, 3).equals("Up ")) { return ["UP", null, null]; }
        return null;
    }

    function updatePower(watts, time) {
        if (watts == null || time == null || watts < 0) {
            resetPower();
            return;
        }
        if (_lastTime != null && (time < _lastTime || time - _lastTime > 3000)) {
            resetPower();
        }
        if (_lastTime == null || time - _lastTime >= 1000) {
            _samples[_slot] = watts;
            _times[_slot] = time;
            _slot = (_slot + 1) % 3;
            _lastTime = time;
        }
        var total = 0.0;
        var count = 0;
        for (var i = 0; i < 3; i += 1) {
            if (_times[i] != null && time - _times[i] < 3000) {
                total += _samples[i];
                count += 1;
            }
        }
        power = count == 0 ? null : Math.round(total / count).toNumber();
    }

    function applyCue() {
        if (_applied || _cue == null) { return; }
        _applied = true;
        if (_cue[0].equals("S")) {
            active = true;
            low = _cue[1];
            high = _cue[2];
        } else if (_cue[0].equals("E")) {
            active = false;
            low = null;
            high = null;
        }
    }

    function updateCourse(name, distance, travelled, speed) {
        if (name == null || name.length() == 0 || distance == null || distance < 0 || travelled == null) {
            resetCourse();
            return;
        }
        if (_lastDistance != null && travelled < _lastDistance) { resetCourse(); }
        navigating = true;
        _lastDistance = travelled;
        // Cache the observed absolute position, so advancing to a new next point
        // does not lose a boundary whose zero-distance sample was skipped.
        var position = travelled + distance;
        var changed = _name == null || !name.equals(_name) ||
            (_position != null && position - _position > 30);
        if (changed) {
            if (_position != null && travelled >= _position) { applyCue(); }
            _name = name;
            _position = position;
            _cue = parse(name);
            _applied = false;
        }
        if (distance == 0) { applyCue(); }
        next = _cue;
        nextDistance = distance;
        countdown = null;
        shift = null;
        if (next != null) {
            if (next[0].equals("S") && !_applied && speed != null && speed > 0) {
                countdown = Math.ceil(distance / speed).toNumber();
            }
            if (distance <= 300 && (next[0].equals("DOWN") || next[0].equals("UP"))) {
                shift = next[0];
            }
        }
    }

    function zone() {
        if (!active || power == null) { return ""; }
        if (power < low) { return "UNDER"; }
        if (power > high) { return "OVER"; }
        return "IN";
    }
}
