# 🚀 Portal API - Task Manager Backend

This repository contains the full Backend, DB and Message Broker source code for the Task Manager AI system.

## 🛠️ Tech Stack
- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic
- **Database:** PostgreSQL 15
- **Cache / PubSub:** Redis 7
- **Message Broker:** RabbitMQ 3
- **Task Queue:** Celery + RabbitMQ
- **Reverse Proxy:** Nginx

## ⚡ Quick Start (Local Development)

### 1. Configure the environment
```bash
cp .env.example .env
# Edit .env if needed
```

### 2. Start the supporting services (DB, Redis, MQ)
```bash
make up
```

### 3. Run Database Migrations
```bash
make migrate
```

### 4. Create the default Admin account
```bash
make create-admin
```

### 5. Run the Backend (Live Reload)
```bash
make dev-backend
```

Once running, the API docs are served at `http://localhost:8000/docs`.

## 🚀 CI/CD
CI/CD is defined in `.gitlab-ci.yml` on the GitLab mirror: it tests, builds the Docker image and deploys to the VPS.
