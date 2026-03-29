from fastapi import APIRouter

from app.routers.garbage import router as garbage_router
from app.routers.map import router as map_router
from app.routers.missions import router as missions_router
from app.routers.sensors import router as sensors_router
from app.routers.system import router as system_router
from app.routers.tasks import router as tasks_router
from app.routers.voice import router as voice_router
from app.routers.zones import router as zones_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(map_router)
api_router.include_router(system_router)
api_router.include_router(zones_router)
api_router.include_router(tasks_router)
api_router.include_router(missions_router)
api_router.include_router(voice_router)
api_router.include_router(sensors_router)
api_router.include_router(garbage_router)
