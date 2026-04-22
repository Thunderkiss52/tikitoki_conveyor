from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


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


def assert_file(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"Expected file was not created: {path}")
    if path.stat().st_size == 0:
        raise AssertionError(f"Created file is empty: {path}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    smoke_db = root / "storage" / "smoke_test.sqlite3"
    if smoke_db.exists():
        smoke_db.unlink()

    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{smoke_db}")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("STORAGE_BASE_PATH", str(root / "storage"))

    trend_video_path = root / "storage" / "input" / "demo" / "smoke_trend.mp4"
    logo_path = root / "HODOR.jpg"
    generate_demo_trend_video(trend_video_path)

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        project_response = client.post(
            "/api/v1/projects",
            json={
                "name": "SMOKE_HODOR",
                "config": {
                    "logo_path": str(logo_path),
                    "brand_colors": ["#0A1633", "#132A63"],
                    "voice_style": "calm_dark_male",
                    "music_style": "dark cyber tension",
                    "default_aspect": "9:16",
                },
            },
        )
        project_response.raise_for_status()
        project = project_response.json()

        trend_response = client.post(
            "/api/v1/trends",
            json={
                "type": "video",
                "source_path": str(trend_video_path),
                "hook_description": "person fails, cat succeeds",
            },
        )
        trend_response.raise_for_status()
        trend = trend_response.json()

        job_response = client.post(
            "/api/v1/jobs",
            json={
                "project_id": project["id"],
                "trend_source_id": trend["id"],
                "topic": "proxy for telegram",
                "language": "ru",
                "duration_sec": 8,
                "scene_count": 3,
                "run_now": True,
                "config_json": {
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
                            "provider_settings": {
                                "resolution": "512x768",
                                "frames": "16-24",
                                "steps": "20-25",
                                "cfg": "6-8",
                            },
                            "negative_prompt": "low quality, blurry, bad anatomy, distorted face, glitch, artifacts, watermark, text errors, deformed hands, extra limbs",
                        },
                        {
                            "type": "contrast",
                            "prompt": "a small cat calmly walking through a tiny opening in the same locked door, funny contrast, cinematic lighting, same dark environment, smooth motion, slight slow motion, high detail, 9:16 vertical video",
                            "overlay": "А решение уже есть",
                            "camera": "medium shot",
                            "motion": "slight slow motion",
                            "provider_settings": {
                                "resolution": "512x768",
                                "frames": "16-24",
                                "steps": "20-25",
                                "cfg": "6-8",
                            },
                            "negative_prompt": "low quality, blurry, bad anatomy, distorted face, glitch, artifacts, watermark, text errors, deformed hands, extra limbs",
                        },
                        {
                            "type": "brand",
                            "prompt": "close-up of the door with a glowing logo HODOR above it, dark cinematic style, neon blue light, mysterious atmosphere, minimalistic, high contrast, slow zoom in, 9:16 vertical video",
                            "overlay": "HODOR",
                            "camera": "close-up",
                            "motion": "slow zoom in",
                            "provider_settings": {
                                "resolution": "512x768",
                                "frames": "16-24",
                                "steps": "20-25",
                                "cfg": "6-8",
                            },
                            "negative_prompt": "low quality, blurry, bad anatomy, distorted face, glitch, artifacts, watermark, text errors, deformed hands, extra limbs",
                        },
                    ],
                    "video_provider": "stub",
                    "allow_synthetic_video": True,
                    "tts_provider": "stub",
                    "music_provider": "library",
                    "brand_overlay": True,
                    "subtitles": True,
                },
            },
        )
        job_response.raise_for_status()
        job = job_response.json()

        detail_response = client.get(f"/api/v1/jobs/{job['id']}")
        detail_response.raise_for_status()
        detail = detail_response.json()

    if detail["status"] != "done":
        raise AssertionError(f"Expected job to finish with done, got: {detail['status']}")

    outputs = detail["result_json"]
    final_video = root / outputs["final_video"]
    subtitles = root / outputs["subtitles"]
    metadata = root / outputs["metadata_json"]
    preview = root / outputs["preview_image"]

    assert_file(final_video)
    assert_file(subtitles)
    assert_file(metadata)
    assert_file(preview)

    payload = json.loads(metadata.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "job_id": detail["id"],
                "status": detail["status"],
                "final_video": str(final_video),
                "subtitles": str(subtitles),
                "preview_image": str(preview),
                "metadata_json": str(metadata),
                "script_template": payload["script"]["template"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
