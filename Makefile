WEB_DIR := apps/web
API_DIR := services/api
ROS_DIR := ros2_ws

.PHONY: web-install web-build api-install api-run docker-build docker-up ros-graph-check ros-baseline runtime-test runtime-prerequisites runtime-install runtime-uninstall runtime-smoke

web-install:
	cd $(WEB_DIR) && npm install

web-build:
	cd $(WEB_DIR) && npm run build

api-install:
	cd $(API_DIR) && python3 -m pip install -e ".[dev]"

api-run:
	cd $(API_DIR) && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

docker-build:
	docker compose build

docker-up:
	docker compose up -d

ros-graph-check:
	bash scripts/verify_ros_graph.sh

ros-baseline:
	bash scripts/measure_ros_baseline.sh

runtime-test:
	cd $(API_DIR) && python3 -m pytest -q
	cd $(ROS_DIR) && python3 -m pytest src/rover_mapping/test src/rover_safety/test src/rover_bringup/test -q

runtime-prerequisites:
	bash scripts/check_runtime_prerequisites.sh

runtime-install:
	bash scripts/install_rover_runtime_service.sh

runtime-uninstall:
	bash scripts/uninstall_rover_runtime_service.sh

runtime-smoke:
	bash scripts/real_machine_smoke_test.sh
