# Gemini Project Plan: Tikitoki Conveyor

This document tracks the technical progress and provides instructions for the Gemini agent.

## 📌 Current Status
- [x] Initial README.md created with architecture overview.
- [ ] Stage 1: Skeleton & Orchestration (In Progress)

## 🛠 Active Tasks
- [x] Setup project structure.
- [x] Initialize FastAPI app.
- [x] Create Job/Project models.
- [x] Setup Docker environment.
- [ ] Configure PostgreSQL with SQLAlchemy/Alembic.
- [ ] Setup Redis and Task Queue (RQ).

## 📖 Architectural Decisions
- **Monolith Modular:** Keep everything in one repo but strictly separate services and providers.
- **Async First:** Use FastAPI and async DB drivers where possible.
- **Job-based:** Every video generation is a `Job` with granular status updates.

## 📝 Notes
- Store all assets in `storage/jobs/{job_id}/`.
- Use FFmpeg for final assembly.
- Keep AI providers behind abstract interfaces.
