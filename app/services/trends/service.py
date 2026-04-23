from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TrendSourceType
from app.core.ids import prefixed_id
from app.db.models import TrendSource
from app.schemas.trend import TrendSourceCreate, TrendSourceUpdate
from app.utils.storage import resolve_local_path, safe_slug, to_workspace_path, trend_upload_dir


class TrendSourceService:
    @staticmethod
    async def list(session: AsyncSession) -> list[TrendSource]:
        result = await session.execute(select(TrendSource).order_by(TrendSource.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get(session: AsyncSession, trend_id: str) -> TrendSource | None:
        return await session.get(TrendSource, trend_id)

    @staticmethod
    async def create(session: AsyncSession, payload: TrendSourceCreate) -> TrendSource:
        normalized_source_path = payload.source_path
        if payload.type.value == "video":
            path = resolve_local_path(payload.source_path)
            if not path.exists():
                raise FileNotFoundError(f"Trend source file not found: {path}")
            normalized_source_path = to_workspace_path(path)

        trend_source = TrendSource(
            type=payload.type,
            source_path=normalized_source_path,
            hook_description=payload.hook_description,
            structure_detected=payload.structure_detected,
            metadata_json=payload.metadata_json,
        )
        session.add(trend_source)
        await session.commit()
        await session.refresh(trend_source)
        return trend_source

    @staticmethod
    async def create_upload(
        session: AsyncSession,
        filename: str,
        content: bytes,
        hook_description: str | None = None,
    ) -> TrendSource:
        trend_id = prefixed_id("trend")
        upload_dir = trend_upload_dir(trend_id)
        original_name = Path(filename).name
        target_name = f"{safe_slug(Path(original_name).stem)}{Path(original_name).suffix or '.mp4'}"
        target_path = upload_dir / target_name
        target_path.write_bytes(content)

        trend_source = TrendSource(
            id=trend_id,
            source_path=to_workspace_path(target_path),
            hook_description=hook_description,
            metadata_json={"original_filename": original_name},
        )
        session.add(trend_source)
        await session.commit()
        await session.refresh(trend_source)
        return trend_source

    @staticmethod
    async def update(session: AsyncSession, trend_source: TrendSource, payload: TrendSourceUpdate) -> TrendSource:
        normalized_source_path = payload.source_path
        if payload.type.value == "video":
            path = resolve_local_path(payload.source_path)
            if not path.exists():
                raise FileNotFoundError(f"Trend source file not found: {path}")
            normalized_source_path = to_workspace_path(path)

        trend_source.type = payload.type
        trend_source.source_path = normalized_source_path
        trend_source.hook_description = payload.hook_description
        trend_source.structure_detected = payload.structure_detected
        trend_source.metadata_json = payload.metadata_json
        await session.commit()
        await session.refresh(trend_source)
        return trend_source

    @staticmethod
    async def replace_upload(
        session: AsyncSession,
        trend_source: TrendSource,
        filename: str,
        content: bytes,
        hook_description: str | None = None,
    ) -> TrendSource:
        upload_dir = trend_upload_dir(trend_source.id)
        for child in upload_dir.iterdir():
            if child.is_file():
                child.unlink()

        original_name = Path(filename).name
        target_name = f"{safe_slug(Path(original_name).stem)}{Path(original_name).suffix or '.mp4'}"
        target_path = upload_dir / target_name
        target_path.write_bytes(content)

        metadata_json = dict(trend_source.metadata_json or {})
        metadata_json["original_filename"] = original_name

        trend_source.type = TrendSourceType.VIDEO
        trend_source.source_path = to_workspace_path(target_path)
        trend_source.hook_description = hook_description if hook_description is not None else trend_source.hook_description
        trend_source.metadata_json = metadata_json
        await session.commit()
        await session.refresh(trend_source)
        return trend_source
