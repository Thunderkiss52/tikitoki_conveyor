from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    @staticmethod
    async def list(session: AsyncSession) -> list[Project]:
        result = await session.execute(select(Project).order_by(Project.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get(session: AsyncSession, project_id: str) -> Project | None:
        return await session.get(Project, project_id)

    @staticmethod
    async def get_by_name(session: AsyncSession, name: str) -> Project | None:
        result = await session.execute(select(Project).where(Project.name == name))
        return result.scalar_one_or_none()

    @staticmethod
    async def create(session: AsyncSession, payload: ProjectCreate) -> Project:
        project = Project(
            name=payload.name,
            config_json=payload.config.as_db_config(),
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project

    @staticmethod
    async def update(session: AsyncSession, project: Project, payload: ProjectUpdate) -> Project:
        project.name = payload.name
        project.config_json = payload.config.as_db_config()
        await session.commit()
        await session.refresh(project)
        return project
