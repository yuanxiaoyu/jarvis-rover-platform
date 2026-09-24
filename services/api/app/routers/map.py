import zlib

from fastapi import APIRouter, HTTPException, Request, Response

from app.models.map import MapModel

router = APIRouter(prefix="/map", tags=["map"])


@router.get("", response_model=MapModel)
def get_map(request: Request) -> MapModel:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        return MapModel()
    return runtime.map_snapshot(include_data=False)


@router.get("/grid")
def get_map_grid(request: Request) -> Response:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="ROS map source is unavailable")
    grid = runtime.map_snapshot()
    data = grid.occupancy.data
    if not grid.available or data is None:
        raise HTTPException(status_code=503, detail="SLAM OccupancyGrid is unavailable")
    etag = f'"{grid.updated_at.isoformat()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    compressed = zlib.compress(bytes(value & 0xFF for value in data), level=3)
    return Response(
        content=compressed,
        media_type="application/vnd.jarvis.occupancy-grid+deflate",
        headers={
            "Cache-Control": "no-cache",
            "ETag": etag,
            "X-Grid-Width": str(grid.occupancy.width_cells),
            "X-Grid-Height": str(grid.occupancy.height_cells),
        },
    )
