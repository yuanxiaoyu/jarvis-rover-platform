WEB_DIR := apps/web
API_DIR := services/api

.PHONY: web-install web-build api-install api-run docker-build docker-up

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
