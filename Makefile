.PHONY: backend frontend dev stop

backend:
	cd backend && /usr/bin/python3 main.py

frontend:
	cd frontend && npm run dev

dev:
	@echo "Starting backend and frontend..."
	@cd backend && nohup /usr/bin/python3 main.py > /dev/null 2>&1 &
	@sleep 1
	@echo "Backend running on http://localhost:8000"
	cd frontend && npm run dev

stop:
	@lsof -ti:8000 | xargs kill 2>/dev/null || true
	@lsof -ti:5173 | xargs kill 2>/dev/null || true
	@echo "Stopped."
