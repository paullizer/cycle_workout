using Toybox.Application;

class TerrainCoachApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() {
        return [new TerrainCoachField()];
    }
}
