from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.models.map import Coordinate2D
from app.models.mission import PathPlanRequest, PathPlanResponse
from app.services.grid_planner import OccupancyGridPlanner, PathPlanningError
from app.services.zone_store import ZoneStore

router = APIRouter(prefix="/navigation", tags=["navigation"])


def _planner(request: Request) -> tuple[OccupancyGridPlanner, Coordinate2D]:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="ROS runtime is unavailable")
    pose = runtime.robot_pose()
    if not pose.available or pose.x is None or pose.y is None:
        raise HTTPException(status_code=409, detail=pose.error or "map-frame robot pose is unavailable")
    store = getattr(request.app.state, "zone_store", None)
    if store is None:
        store = ZoneStore(f"{settings.mapping_session_dir}/zones.json")
        request.app.state.zone_store = store
    try:
        planner = OccupancyGridPlanner(runtime.map_snapshot(), store.list())
    except PathPlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return planner, Coordinate2D(x=pose.x, y=pose.y)


def _response(path, message: str = "") -> PathPlanResponse:
    return PathPlanResponse(
        waypoints=path.waypoints,
        length_m=path.length_m,
        explored_cells=path.explored_cells,
        goal_reached=path.goal_reached,
        message=message,
    )


@router.post("/plan", response_model=PathPlanResponse)
def plan_path(request: Request, payload: PathPlanRequest) -> PathPlanResponse:
    planner, start = _planner(request)
    goal = payload.goal
    if payload.zone_id is not None:
        store = getattr(request.app.state, "zone_store")
        zone = store.get(payload.zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail="zone not found")
        if zone.type.value in {"keepout", "virtual_wall"}:
            raise HTTPException(status_code=409, detail="cannot navigate to a restricted zone or virtual wall")
        goal = Coordinate2D(
            x=sum(point.x for point in zone.points) / len(zone.points),
            y=sum(point.y for point in zone.points) / len(zone.points),
        )
    if goal is None:
        raise HTTPException(status_code=422, detail="path goal is required")
    try:
        return _response(planner.plan(start, goal), "路径由真实占据栅格计算，仅作预览")
    except PathPlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/exploration/next", response_model=PathPlanResponse)
def plan_next_frontier(request: Request) -> PathPlanResponse:
    planner, start = _planner(request)
    try:
        return _response(planner.next_frontier(start), "已找到最近可达未知边界；未连接 Nav2 安全执行器，当前为路径预览")
    except PathPlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
