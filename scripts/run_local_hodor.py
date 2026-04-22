from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def generate_demo_trend_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x1c2438:s=1080x1920:d=4:r=30",
        "-vf",
        "drawtext=text='TREND REF':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the HODOR local video pipeline.")
    parser.add_argument("--provider", choices=["stub", "comfyui"], default="comfyui")
    parser.add_argument("--topic", default="proxy for telegram")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--duration-sec", type=int, default=8)
    parser.add_argument("--scene-count", type=int, default=3)
    parser.add_argument("--trend-video", default=str(root / "storage" / "input" / "demo" / "hodor_trend.mp4"))
    parser.add_argument("--hook-description", default="person fails, cat succeeds")
    parser.add_argument("--logo-path", default=str(root / "HODOR.jpg"))
    parser.add_argument("--workflow-path", default=None)
    parser.add_argument("--workflow-mapping-path", default=str(root / "app" / "templates" / "comfyui" / "workflow_mapping.example.json"))
    parser.add_argument("--comfyui-base-url", default="http://127.0.0.1:8188")
    parser.add_argument("--db-path", default=str(root / "storage" / "local_hodor.sqlite3"))
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--skip-demo-trend", action="store_true")
    parser.add_argument("--output-prefix", default="hodor_local")
    return parser.parse_args()


def configure_environment(args: argparse.Namespace) -> Path:
    root = Path(__file__).resolve().parents[1]
    db_path = Path(args.db_path).resolve()
    if db_path.exists() and not args.keep_db:
        db_path.unlink()

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["STORAGE_BASE_PATH"] = str(root / "storage")
    os.environ["COMFYUI_BASE_URL"] = args.comfyui_base_url
    os.environ.setdefault("DEBUG", "false")
    return root


def load_workflow_mapping(path_str: str | None) -> dict[str, Any] | None:
    if not path_str:
        return None
    path = Path(path_str).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Workflow mapping file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_job_config(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    provider_settings = {
        "resolution": "512x768",
        "frames": 24,
        "steps": 24,
        "cfg": 7,
        "fps": 8,
    }
    if args.provider == "comfyui":
        if not args.workflow_path:
            raise ValueError("--workflow-path is required when --provider comfyui")
        provider_settings["workflow_path"] = str(Path(args.workflow_path).resolve())
        workflow_mapping = load_workflow_mapping(args.workflow_mapping_path)
        if workflow_mapping:
            provider_settings["workflow_mapping"] = workflow_mapping

    negative_prompt = (
        "low quality, blurry, bad anatomy, distorted face, glitch, artifacts, "
        "watermark, text errors, deformed hands, extra limbs"
    )

    base_shot_settings = {
        "provider_settings": provider_settings,
        "negative_prompt": negative_prompt,
    }

    return {
        "title_override": "HODOR Telegram Hook",
        "voiceover_lines": [
            "Telegram снова не работает?",
            "Есть способ проще.",
            "HODOR.",
        ],
        "overlay_lines": [
            "Когда Telegram не пускает",
            "А решение уже есть",
            "HODOR",
        ],
        "shot_overrides": [
            {
                "type": "hook",
                "prompt": "a frustrated man trying to open a locked door, dark room, cinematic lighting, neon blue tones, close-up, emotional tension, realistic, slight camera shake, dramatic atmosphere, ultra detailed, 9:16 vertical video",
                "overlay": "Когда Telegram не пускает",
                "camera": "close-up",
                "motion": "slight camera shake",
                **base_shot_settings,
            },
            {
                "type": "contrast",
                "prompt": "a small cat calmly walking through a tiny opening in the same locked door, funny contrast, cinematic lighting, same dark environment, smooth motion, slight slow motion, high detail, 9:16 vertical video",
                "overlay": "А решение уже есть",
                "camera": "medium shot",
                "motion": "slight slow motion",
                **base_shot_settings,
            },
            {
                "type": "brand",
                "prompt": "close-up of the door with a glowing logo HODOR above it, dark cinematic style, neon blue light, mysterious atmosphere, minimalistic, high contrast, slow zoom in, 9:16 vertical video",
                "overlay": "HODOR",
                "camera": "close-up",
                "motion": "slow zoom in",
                **base_shot_settings,
            },
        ],
        "video_provider": args.provider,
        "allow_synthetic_video": args.provider == "stub",
        "tts_provider": "stub",
        "music_provider": "library",
        "brand_overlay": True,
        "subtitles": True,
        "template": "dark_cinematic",
    }


async def run_pipeline(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal, init_db
    from app.schemas.job import JobCreate
    from app.schemas.project import ProjectCreate
    from app.schemas.trend import TrendSourceCreate
    from app.services.jobs import JobService, run_job_pipeline
    from app.services.projects.service import ProjectService
    from app.services.trends.service import TrendSourceService
    from app.utils.storage import ensure_base_storage

    ensure_base_storage()
    await init_db()

    trend_video_path = Path(args.trend_video).resolve()
    if not trend_video_path.exists():
        if args.skip_demo_trend:
            raise FileNotFoundError(f"Trend video not found: {trend_video_path}")
        generate_demo_trend_video(trend_video_path)

    logo_path = Path(args.logo_path).resolve()
    if not logo_path.exists():
        raise FileNotFoundError(f"Logo file not found: {logo_path}")

    job_config = build_job_config(args, root)

    async with AsyncSessionLocal() as session:
        project = await ProjectService.create(
            session,
            ProjectCreate(
                name=f"HODOR_LOCAL_{args.provider.upper()}",
                config={
                    "logo_path": str(logo_path),
                    "brand_colors": ["#0A1633", "#132A63"],
                    "voice_style": "calm_dark_male",
                    "music_style": "dark cyber tension",
                    "default_aspect": "9:16",
                },
            ),
        )

        trend = await TrendSourceService.create(
            session,
            TrendSourceCreate(
                type="video",
                source_path=str(trend_video_path),
                hook_description=args.hook_description,
            ),
        )

        job = await JobService.create(
            session,
            JobCreate(
                project_id=project.id,
                trend_source_id=trend.id,
                topic=args.topic,
                language=args.language,
                duration_sec=args.duration_sec,
                scene_count=args.scene_count,
                config_json=job_config,
            ),
        )

    result = await run_job_pipeline(job.id)

    async with AsyncSessionLocal() as session:
        detail = await JobService.get_detail(session, job.id)
        if detail is None:
            raise RuntimeError(f"Job detail not found after run: {job.id}")

    outputs = detail.result_json
    final_video = root / outputs["final_video"]
    preview_image = root / outputs["preview_image"]
    subtitles = root / outputs["subtitles"]
    metadata_json = root / outputs["metadata_json"]

    export_dir = root / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_video = export_dir / f"{args.output_prefix}_{args.provider}.mp4"
    export_preview = export_dir / f"{args.output_prefix}_{args.provider}.jpg"
    export_subtitles = export_dir / f"{args.output_prefix}_{args.provider}.srt"
    export_metadata = export_dir / f"{args.output_prefix}_{args.provider}.json"

    shutil.copy2(final_video, export_video)
    shutil.copy2(preview_image, export_preview)
    shutil.copy2(subtitles, export_subtitles)
    shutil.copy2(metadata_json, export_metadata)

    return {
        "job_id": detail.id,
        "status": detail.status.value,
        "provider": args.provider,
        "final_video": str(export_video),
        "preview_image": str(export_preview),
        "subtitles": str(export_subtitles),
        "metadata_json": str(export_metadata),
        "storage_job_output": str(final_video.parent),
        "pipeline_state_path": outputs.get("pipeline_state_path"),
        "workflow_path": str(Path(args.workflow_path).resolve()) if args.workflow_path else None,
    }


def main() -> None:
    args = parse_args()
    root = configure_environment(args)
    result = asyncio.run(run_pipeline(args, root))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
