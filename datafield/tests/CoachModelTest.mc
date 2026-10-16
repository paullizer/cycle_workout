using Toybox.Test;

(:test)
function testCueParsing(logger) {
    var m = new CoachModel();
    Test.assert(m.parse("S 210-230")[1] == 210);
    Test.assert(m.parse("E 210-230")[0].equals("E"));
    Test.assert(m.parse("210-230W start")[0].equals("S"));
    Test.assert(m.parse("End 210-230W")[2] == 230);
    Test.assert(m.parse("Down 6%")[0].equals("DOWN"));
    Test.assert(m.parse("Up -3%")[0].equals("UP"));
    var invalid = ["S 0-230", "S 240-230", "S 20x-230", "S 210-",
        "S 210-230W", "S 210-2001", "E 210-230 extra", "", "Turn left", null];
    for (var i = 0; i < invalid.size(); i += 1) {
        Test.assert(m.parse(invalid[i]) == null);
    }
    return true;
}

(:test)
function testIntervalTransitions(logger) {
    var m = new CoachModel();
    m.updateCourse("S 210-230", 100, 0, 10);
    Test.assert(!m.active && m.countdown == 10);
    m.updateCourse("S 210-230", 0, 100, 10);
    Test.assert(m.active && m.low == 210 && m.high == 230);
    m.updateCourse("Turn left", 100, 100, 10);
    Test.assert(m.active && m.next == null);
    m.updateCourse("E 210-230", 50, 200, 10);
    Test.assert(m.active);
    m.updateCourse("E 210-230", 0, 250, 10);
    Test.assert(!m.active);
    m.updateCourse(null, null, 250, null);
    Test.assert(!m.active && !m.navigating);
    return true;
}

(:test)
function testSkippedZeroAndRepeatedNames(logger) {
    var m = new CoachModel();
    m.updateCourse("S 210-230", 10, 90, 10);
    m.updateCourse("Down 6%", 290, 110, 10);
    Test.assert(m.active && m.shift.equals("DOWN"));
    m.updateCourse("E 210-230", 10, 490, 10);
    m.updateCourse("S 210-230", 200, 510, 10);
    Test.assert(!m.active);
    m.updateCourse("S 210-230", 200, 720, 10);
    Test.assert(m.active);
    m.updateCourse("Up -3%", 301, 730, 10);
    Test.assert(m.shift == null);
    m.updateCourse("Up -3%", 300, 731, 10);
    Test.assert(m.shift.equals("UP"));
    m.updateCourse("Up -3%", 100, 0, 0);
    Test.assert(!m.active);
    return true;
}

(:test)
function testPowerWindowAndZones(logger) {
    var m = new CoachModel();
    m.updatePower(0, 0);
    m.updatePower(210, 1000);
    m.updatePower(240, 2000);
    Test.assert(m.power == 150);
    m.updatePower(210, 3000);
    Test.assert(m.power == 220);
    m.updatePower(900, 3000);
    Test.assert(m.power == 220);
    m.updateCourse("S 210-230", 0, 0, 10);
    Test.assert(m.zone().equals("IN"));
    m.updatePower(600, 4000);
    Test.assert(m.zone().equals("OVER"));
    m.updatePower(100, 8000);
    Test.assert(m.zone().equals("UNDER"));
    m.updatePower(null, 9000);
    Test.assert(m.power == null && m.zone().equals(""));
    m.updatePower(210, 10000);
    Test.assert(m.zone().equals("IN"));
    m.updatePower(230, 0);
    Test.assert(m.power == 230 && m.zone().equals("IN"));
    return true;
}

(:test)
function testStoppedAndMissingNavigation(logger) {
    var m = new CoachModel();
    m.updateCourse("S 210-230", 300, 0, 0);
    Test.assert(m.countdown == null);
    m.updateCourse("S 210-230", 0, 300, 10);
    Test.assert(m.active);
    m.updateCourse("?", null, 300, 10);
    Test.assert(!m.active && m.low == null);
    m.updateCourse("E 210-230", 100, 400, 10);
    Test.assert(!m.active);
    return true;
}
