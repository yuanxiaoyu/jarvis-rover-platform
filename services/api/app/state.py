from app.models.map import Coordinate2D, MapModel, Reconstructed3DLayer
from app.models.mission import MissionMode, MissionState
from app.models.task import Task
from app.models.voice import VoiceSessionState
from app.models.zone import Zone, ZoneType

MAP_STATE = MapModel(
    reconstruction_layers=[
        Reconstructed3DLayer(
            layer_id="base_occupancy_extrusion",
            method="extruded_occupancy",
            description="Extrusion of 2D occupancy cells for 3D visualization.",
            height_m=0.15,
        )
    ]
)
ZONE_STATE: list[Zone] = [
    Zone(
        zone_id="dock-west",
        name="西侧停靠区",
        type=ZoneType.SEMANTIC,
        semantic_label="dock",
        points=[
            Coordinate2D(x=0.0, y=0.0),
            Coordinate2D(x=3.6, y=0.0),
            Coordinate2D(x=3.6, y=2.4),
            Coordinate2D(x=0.0, y=2.4),
        ],
    ),
    Zone(
        zone_id="inspection-east",
        name="东侧巡检区",
        type=ZoneType.SEMANTIC,
        semantic_label="inspection",
        points=[
            Coordinate2D(x=8.6, y=2.4),
            Coordinate2D(x=16.0, y=2.4),
            Coordinate2D(x=16.0, y=8.5),
            Coordinate2D(x=8.6, y=8.5),
        ],
    ),
]
TASK_STATE: list[Task] = []
MISSION_STATE = MissionState(
    mode=MissionMode.AUTONOMY,
    objective="巡航主通道并检查东侧巡检区",
    status_line="任务状态正常",
    selected_zone_id="inspection-east",
)
VOICE_STATE = VoiceSessionState(listening=False, adapter="mock", transcript="语音待命中")
