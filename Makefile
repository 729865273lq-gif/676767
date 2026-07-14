.DEFAULT_GOAL := help

.PHONY: help up test-backend test-frontend lint

help:
	@echo "Targets: up, test-backend, test-frontend, lint"

up:
	docker compose up -d postgres redis minio

test-backend:
	cd backend && .venv/Scripts/python.exe -m pytest -q

test-frontend:
	cd frontend && npm.cmd run test:e2e

lint:
	cd backend && .venv/Scripts/ruff.exe check app tests
	cd frontend && npm.cmd run lint
