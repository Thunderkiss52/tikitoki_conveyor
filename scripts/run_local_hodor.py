from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


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
    parser = argparse.ArgumentParser(description="Run the HODOR local video factory with ComfyUI presets.")
    parser.add_argument("--scenario", default="default")
    parser.add_argument("--provider", choices=["reference", "stub", "comfyui"], default="reference")
    parser.add_argument("--mode", default="video_to_video")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--project-name", default="HODOR")
    parser.add_argument("--topic", default="proxy for telegram")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--duration-sec", type=int, default=8)
    parser.add_argument("--scene-count", type=int, default=3)
    parser.add_argument("--trend-video", default=str(root / "storage" / "input" / "demo" / "hodor_trend.mp4"))
    parser.add_argument("--reference-video", default=None)
    parser.add_argument("--reference-image", default=None)
    parser.add_argument("--trend-blueprint", default=None)
    parser.add_argument("--hook-description", default="person fails, cat succeeds")
    parser.add_argument("--logo-path", default=str(root / "HODOR.jpg"))
    parser.add_argument("--workflow-path", default=None)
    parser.add_argument("--workflow-mapping-path", default=None)
    parser.add_argument("--comfyui-base-url", default="http://127.0.0.1:8188")
    parser.add_argument("--comfyui-device-mode", choices=["gpu", "cpu", "auto"], default="gpu")
    parser.add_argument("--comfyui-start-timeout", type=int, default=180)
    parser.add_argument("--resolution", default=None)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--cfg", type=float, default=None)
    parser.add_argument("--fps", type=float, default=None)
    parser.add_argument("--denoise", type=float, default=None)
    parser.add_argument("--tts-provider", default="piper")
    parser.add_argument("--music-provider", default="hybrid")
    parser.add_argument("--db-path", default=str(root / "storage" / "local_hodor.sqlite3"))
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--skip-demo-trend", action="store_true")
    parser.add_argument("--allow-demo-trend", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--output-prefix", default="hodor_factory")
    parser.add_argument("--auto-start-comfyui", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prepare-workflows", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--sync-workflows-to-comfyui-user", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def configure_environment(args: argparse.Namespace) -> Path:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    db_path = Path(args.db_path).resolve()
    if db_path.exists() and not args.keep_db:
        db_path.unlink()

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["STORAGE_BASE_PATH"] = str(root / "storage")
    os.environ["COMFYUI_BASE_URL"] = args.comfyui_base_url
    os.environ["COMFYUI_INPUT_DIR"] = str(root / "third_party" / "ComfyUI" / "input")
    if Path("/usr/lib/wsl/lib").exists():
        os.environ["PATH"] = f"/usr/lib/wsl/lib:{os.environ.get('PATH', '')}".rstrip(":")
        existing_ld_library = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = (
            f"/usr/lib/wsl/lib:{existing_ld_library}".rstrip(":")
            if existing_ld_library
            else "/usr/lib/wsl/lib"
        )
    os.environ.setdefault("DEBUG", "false")
    return root


def load_workflow_mapping(path_str: str | None) -> dict[str, Any] | None:
    if not path_str:
        return None
    path = Path(path_str).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Workflow mapping file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_trend_blueprint(path_str: str | None) -> dict[str, Any] | None:
    if not path_str:
        return None
    path = Path(path_str).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Trend blueprint file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Trend blueprint must be a JSON object.")
    return payload


def comfyui_available(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url.rstrip('/')}/system_stats", timeout=5) as response:
            return response.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def prepare_workflows(root: Path, args: argparse.Namespace) -> None:
    if args.provider != "comfyui" or not args.prepare_workflows:
        return

    image_source = Path(args.reference_image or args.logo_path).resolve()
    video_source = Path(args.reference_video or args.trend_video).resolve()
    if not image_source.exists():
        raise FileNotFoundError(f"Workflow preparation image source not found: {image_source}")
    if not video_source.exists():
        if args.skip_demo_trend:
            raise FileNotFoundError(f"Workflow preparation video source not found: {video_source}")
        generate_demo_trend_video(video_source)

    command = [
        sys.executable,
        str(root / "scripts" / "prepare_helper_workflows.py"),
        "--image-source",
        str(image_source),
        "--video-source",
        str(video_source),
    ]
    if args.sync_workflows_to_comfyui_user:
        command.append("--sync-to-comfyui-user")
    subprocess.run(command, cwd=root, check=True)


def _comfyui_log_tail(log_path: Path, max_lines: int = 40) -> str:
    if not log_path.exists():
        return ""
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def ensure_comfyui_running(root: Path, args: argparse.Namespace) -> tuple[Path | None, subprocess.Popen[str] | None]:
    if args.provider != "comfyui":
        return None, None
    if comfyui_available(args.comfyui_base_url):
        return None, None
    if not args.auto_start_comfyui:
        raise RuntimeError(
            f"ComfyUI is not reachable at {args.comfyui_base_url}. "
            "Start it manually or pass --auto-start-comfyui."
        )

    parsed = urlparse(args.comfyui_base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 8188)
    log_dir = root / "storage" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "comfyui.log"
    pid_path = log_dir / "comfyui.pid"

    env = os.environ.copy()
    env["COMFYUI_HOST"] = host
    env["COMFYUI_PORT"] = port
    env["COMFYUI_DEVICE_MODE"] = args.comfyui_device_mode
    if Path("/usr/lib/wsl/lib").exists():
        env["PATH"] = f"/usr/lib/wsl/lib:{env.get('PATH', '')}".rstrip(":")
        existing_ld_library = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"/usr/lib/wsl/lib:{existing_ld_library}".rstrip(":")
            if existing_ld_library
            else "/usr/lib/wsl/lib"
        )

    command = (
        f"cd {shlex.quote(str(root))} "
        f"&& COMFYUI_HOST={shlex.quote(host)} "
        f"COMFYUI_PORT={shlex.quote(port)} "
        f"COMFYUI_DEVICE_MODE={shlex.quote(args.comfyui_device_mode)} "
        f"{shlex.quote(str(root / 'scripts' / 'start_comfyui.sh'))} "
        f">> {shlex.quote(str(log_path))} 2>&1"
    )
    process = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")

    deadline = time.time() + args.comfyui_start_timeout
    while time.time() < deadline:
        if comfyui_available(args.comfyui_base_url):
            return log_path, process
        if process.poll() is not None:
            raise RuntimeError(
                "ComfyUI exited before becoming ready.\n"
                f"Log tail:\n{_comfyui_log_tail(log_path)}"
            )
        time.sleep(2)

    raise TimeoutError(
        f"Timed out waiting for ComfyUI at {args.comfyui_base_url}.\n"
        f"Log tail:\n{_comfyui_log_tail(log_path)}"
    )


def stop_started_comfyui(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def build_job_config(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    from app.core.render_presets import build_comfyui_provider_settings, normalize_generation_mode, normalize_quality_preset

    mode = normalize_generation_mode(args.mode)
    quality = normalize_quality_preset(args.quality)
    logo_path = Path(args.logo_path).resolve()
    reference_image = Path(args.reference_image or args.logo_path).resolve()
    reference_video = Path(args.reference_video or args.trend_video).resolve()

    provider_settings: dict[str, Any] = {}
    if args.provider == "comfyui":
        overrides: dict[str, Any] = {
            "workflow_path": str(Path(args.workflow_path).resolve()) if args.workflow_path else None,
            "brand_image_path": str(logo_path),
            "resolution": args.resolution,
            "frames": args.frames,
            "steps": args.steps,
            "cfg": args.cfg,
            "fps": args.fps,
            "denoise": args.denoise,
        }
        if mode == "image_to_video":
            overrides["reference_image_path"] = str(reference_image)
        if mode == "video_to_video":
            overrides["reference_video_path"] = str(reference_video)

        provider_settings = build_comfyui_provider_settings(mode=mode, quality=quality, overrides=overrides)
        workflow_mapping = load_workflow_mapping(args.workflow_mapping_path)
        if workflow_mapping:
            provider_settings["workflow_mapping"] = workflow_mapping
    else:
        provider_settings = {
            "generation_mode": mode,
            "quality_preset": quality,
            "resolution": args.resolution or "576x1024",
            "frames": args.frames or 16,
            "steps": args.steps or 24,
            "cfg": args.cfg or 7.0,
            "fps": args.fps or 8.0,
        }

    negative_prompt = (
        "low quality, blurry, bad anatomy, distorted face, glitch, artifacts, "
        "watermark, text errors, deformed hands, extra limbs"
    )
    trend_blueprint = load_trend_blueprint(args.trend_blueprint)

    if str(args.scenario).lower() in {"closed_door", "telegram_door", "hodor_closed_door"}:
        return _apply_trend_blueprint(
            _build_closed_door_scenario(
                args=args,
                mode=mode,
                quality=quality,
                logo_path=logo_path,
                reference_image=reference_image,
                reference_video=reference_video,
                negative_prompt=negative_prompt,
            ),
            trend_blueprint,
        )

    if str(args.scenario).lower() in {"hodor_breaks_block", "break_block", "block_breaker", "telegram_block"}:
        return _build_hodor_breaks_block_scenario(
            args=args,
            quality=quality,
            reference_image=reference_image,
        )

    if trend_blueprint and args.provider == "reference":
        return _build_reference_blueprint_config(
            args=args,
            quality=quality,
            trend_blueprint=trend_blueprint,
            reference_video=reference_video,
            reference_image=reference_image,
        )

    base_shot_settings = {
        "provider_settings": provider_settings,
        "negative_prompt": negative_prompt,
    }

    return _apply_trend_blueprint({
        "title_override": "HODOR Telegram Hook",
        "generation_mode": mode,
        "quality_preset": quality,
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
        "tts_provider": args.tts_provider,
        "music_provider": args.music_provider,
        "brand_overlay": True,
        "subtitles": True,
        "template": "dark_cinematic",
        "max_parallel_video_shots": 1,
    }, trend_blueprint)


def _apply_trend_blueprint(config: dict[str, Any], blueprint: dict[str, Any] | None) -> dict[str, Any]:
    if not blueprint:
        return config

    merged = dict(config)
    analysis = blueprint.get("analysis")
    if isinstance(analysis, dict):
        merged["trend_analysis_override"] = analysis

    template = blueprint.get("template")
    if template:
        merged["template"] = str(template)

    scene_count = blueprint.get("scene_count")
    if scene_count:
        merged["scene_count_override"] = int(scene_count)

    title = blueprint.get("title")
    if title:
        merged["title_override"] = str(title)

    return merged


def _build_reference_blueprint_config(
    args: argparse.Namespace,
    quality: str,
    trend_blueprint: dict[str, Any],
    reference_video: Path,
    reference_image: Path,
) -> dict[str, Any]:
    analysis = dict(trend_blueprint.get("analysis") or {})
    references = dict(analysis.get("references") or {})
    segments = list(references.get("segments") or [])
    beats = list(analysis.get("beats") or [])
    render_resolution = args.resolution or "720x1280"
    fps = args.fps or 30.0
    shot_overrides: list[dict[str, Any]] = []

    for index, segment in enumerate(segments, start=1):
        start_sec = float(segment.get("start_sec") or 0.0)
        end_sec = float(segment.get("end_sec") or start_sec + 2.0)
        duration_sec = max(0.6, round(end_sec - start_sec, 2))
        beat = beats[index - 1] if index - 1 < len(beats) else f"scene_{index}"
        label = str(segment.get("label") or beat)
        purpose = str(segment.get("purpose") or "")
        is_brandish = "brand" in label or "brand" in purpose
        shot_overrides.append(
            {
                "type": beat,
                "duration_sec": duration_sec,
                "prompt": f"{label}: {purpose}".strip(": "),
                "camera": "close-up" if beat in {"hook_closeup", "reveal", "brand_punchline"} else "medium shot",
                "motion": "quick punch-in" if beat == "hook_closeup" else "fast reveal" if beat == "reveal" else "lo-fi handheld",
                "transition": "cut",
                "provider_settings": {
                    "source_kind": "image" if is_brandish else "video",
                    "source_path": str(reference_image if is_brandish else reference_video),
                    "resolution": render_resolution,
                    "source_start_sec": start_sec,
                    "source_duration_sec": duration_sec * (1.05 if beat == "hook_closeup" else 1.0),
                    "speed": 1.05 if beat == "hook_closeup" else 0.98 if beat == "contrast" else 1.0,
                    "punch_in": 1.06 if beat == "hook_closeup" else 1.03 if beat == "reveal" else 1.01,
                    "brightness": 0.02 if beat in {"contrast", "reveal"} else 0.0,
                    "contrast": 1.08 if beat in {"hook_closeup", "reveal"} else 1.03,
                    "saturation": 1.04 if beat in {"reveal", "brand_punchline"} else 1.0,
                    "sharpen": 0.35 if beat in {"hook_closeup", "reveal"} else 0.18,
                    "fps": fps,
                    "fade_in_sec": 0.15 if beat == "reveal" else 0.0,
                },
            }
        )

    return {
        "title_override": str(trend_blueprint.get("title") or "Trend Blueprint Remix"),
        "generation_mode": "reference_blueprint",
        "quality_preset": quality,
        "trend_analysis_override": analysis,
        "shot_overrides": shot_overrides,
        "video_provider": "reference",
        "allow_synthetic_video": False,
        "tts_provider": args.tts_provider,
        "music_provider": args.music_provider,
        "brand_overlay": False,
        "subtitles": True,
        "template": str(trend_blueprint.get("template") or "meme_problem_solution"),
        "scene_count_override": int(trend_blueprint.get("scene_count") or max(len(shot_overrides), args.scene_count)),
        "max_parallel_video_shots": 1,
        "music_mode": "library",
        "export_resolution": render_resolution,
    }


def _build_closed_door_scenario(
    args: argparse.Namespace,
    mode: str,
    quality: str,
    logo_path: Path,
    reference_image: Path,
    reference_video: Path,
    negative_prompt: str,
) -> dict[str, Any]:
    from app.core.render_presets import build_comfyui_provider_settings

    render_resolution = args.resolution or "720x1280"
    output_resolution = "720x1280"

    if args.provider == "comfyui":
        shared_overrides = {
            "brand_image_path": str(logo_path),
            "resolution": render_resolution,
            "frames": args.frames,
            "steps": args.steps,
            "cfg": args.cfg,
            "fps": args.fps,
            "denoise": args.denoise,
        }

        hook_provider_settings = build_comfyui_provider_settings(
            mode="text_to_video",
            quality=quality,
            overrides=shared_overrides,
        )
        contrast_provider_settings = build_comfyui_provider_settings(
            mode="text_to_video",
            quality=quality,
            overrides=shared_overrides,
        )
        brand_provider_settings = build_comfyui_provider_settings(
            mode="image_to_video",
            quality=quality,
            overrides={
                **shared_overrides,
                "reference_image_path": str(reference_image),
            },
        )

        if args.workflow_mapping_path:
            workflow_mapping = load_workflow_mapping(args.workflow_mapping_path)
            if workflow_mapping:
                hook_provider_settings["workflow_mapping"] = workflow_mapping
                contrast_provider_settings["workflow_mapping"] = workflow_mapping
                brand_provider_settings["workflow_mapping"] = workflow_mapping
    else:
        fps = args.fps or 30.0
        hook_provider_settings = {
            "source_kind": "video",
            "source_path": str(reference_video),
            "resolution": render_resolution,
            "source_start_sec": 0.0,
            "speed": 1.12,
            "source_duration_sec": 2.24,
            "punch_in": 1.05,
            "brightness": 0.0,
            "contrast": 1.07,
            "saturation": 1.02,
            "sharpen": 0.35,
            "fps": fps,
        }
        contrast_provider_settings = {
            "source_kind": "video",
            "source_path": str(reference_video),
            "resolution": render_resolution,
            "source_start_sec": 2.0,
            "speed": 0.95,
            "source_duration_sec": 1.9,
            "punch_in": 1.03,
            "brightness": 0.05,
            "contrast": 1.10,
            "saturation": 1.10,
            "sharpen": 0.45,
            "fps": fps,
        }
        brand_provider_settings = {
            "source_kind": "image",
            "source_path": str(reference_image),
            "resolution": render_resolution,
            "fps": fps,
            "fade_in_sec": 0.35,
            "background_blur": 30,
            "background_brightness": -0.05,
            "background_saturation": 0.82,
            "image_scale": 0.68,
            "zoom_end": 1.08,
        }

    return {
        "title_override": "Закрытая дверь",
        "generation_mode": "reference_remix" if args.provider != "comfyui" else "mixed_story",
        "quality_preset": quality,
        "voiceover_lines": [
            "Telegram не работает?",
            "Но есть способ проще.",
            "HODOR.",
        ],
        "overlay_lines": [
            "Когда Telegram не пускает",
            "А кто-то уже внутри",
            "HODOR\nРаботает прямо в Telegram",
        ],
        "trend_analysis_override": {
            "hook": "человек застрял у двери, контрастный проход и затем бренд-решение",
            "beats": ["problem", "contrast", "brand_reveal"],
            "estimated_scene_count": 3,
            "pace": "fast",
            "camera_style": "real trend clip remix + deterministic brand reveal",
            "mood": "dark ambient cinematic pulse minimal beat",
            "references": {
                "reference_video": str(reference_video),
                "reference_image": str(reference_image),
            },
        },
        "shot_overrides": [
            {
                "type": "problem",
                "duration_sec": 2.0,
                "prompt": "a frustrated man trying to open a locked door, dark room, cinematic lighting, neon blue tones, close-up, emotional tension, realistic, slight camera shake, dramatic atmosphere, ultra detailed, 9:16 vertical video",
                "overlay": "Когда Telegram не пускает",
                "camera": "close-up",
                "motion": "fast punch-in",
                "transition": "cut",
                "negative_prompt": negative_prompt,
                "provider_settings": hook_provider_settings,
            },
            {
                "type": "contrast",
                "duration_sec": 2.0,
                "prompt": "a small cat calmly walking through a tiny opening in the same locked door, funny contrast, cinematic lighting, same dark environment, smooth motion, slight slow motion, high detail, 9:16 vertical video",
                "overlay": "А кто-то уже внутри",
                "camera": "medium shot",
                "motion": "contrast slowdown",
                "transition": "cut",
                "negative_prompt": negative_prompt,
                "provider_settings": contrast_provider_settings,
            },
            {
                "type": "brand_reveal",
                "duration_sec": 3.0,
                "prompt": 'close-up of the door with a glowing logo "HODOR" above it, dark cinematic style, neon blue light, mysterious atmosphere, minimalistic, high contrast, slow zoom in, 9:16 vertical video',
                "overlay": "HODOR\nРаботает прямо в Telegram",
                "camera": "close-up",
                "motion": "slow zoom in",
                "transition": "fade",
                "negative_prompt": negative_prompt,
                "provider_settings": brand_provider_settings,
            },
        ],
        "video_provider": args.provider,
        "allow_synthetic_video": False,
        "tts_provider": args.tts_provider,
        "music_provider": args.music_provider,
        "brand_overlay": False,
        "subtitles": True,
        "template": "dark_cinematic",
        "max_parallel_video_shots": 1,
        "music_mode": "library",
        "export_resolution": output_resolution,
    }


def _build_hodor_breaks_block_scenario(
    args: argparse.Namespace,
    quality: str,
    reference_image: Path,
) -> dict[str, Any]:
    render_resolution = args.resolution or "720x1280"
    fps = args.fps or 30.0

    def ui(kind: str) -> dict[str, Any]:
        return {
            "source_kind": kind,
            "resolution": render_resolution,
            "fps": fps,
        }

    def hodor(kind: str, **extra: Any) -> dict[str, Any]:
        return {
            "source_kind": kind,
            "source_path": str(reference_image),
            "resolution": render_resolution,
            "fps": fps,
            **extra,
        }

    return {
        "title_override": "HODOR выбрасывает блокировку",
        "generation_mode": "reference_action",
        "quality_preset": quality,
        "duration_sec_override": 7,
        "voiceover_lines": [
            "Telegram не открывается.",
            "Снова блок.",
            "HODOR.",
            "Выбрасывает блокировку.",
            "Работает.",
            "HODOR. Прямо в Telegram.",
        ],
        "overlay_lines": [
            "Когда Telegram не открывается",
            "Снова блок",
            "HODOR",
            "Выбрасывает блок",
            "Работает",
            "HODOR\nРаботает прямо в Telegram",
        ],
        "trend_analysis_override": {
            "hook": "phone access fails, block appears, HODOR spins up and destroys it",
            "beats": ["problem", "block", "hodor", "impact", "result", "brand_reveal"],
            "estimated_scene_count": 6,
            "pace": "fast",
            "camera_style": "deterministic UI motion + logo impact",
            "mood": "impact build-up drop neon cyber",
            "references": {
                "reference_image": str(reference_image),
                "assembly_mode": "deterministic_effects_only",
            },
        },
        "shot_overrides": [
            {
                "type": "problem",
                "duration_sec": 1.4,
                "prompt": "phone frustration ui clip",
                "overlay": "Когда Telegram не открывается",
                "camera": "close-up",
                "motion": "subtle shake",
                "transition": "cut",
                "provider_settings": ui("ui_problem"),
            },
            {
                "type": "block",
                "duration_sec": 1.0,
                "prompt": "access denied barrier clip",
                "overlay": "Снова блок",
                "camera": "close-up",
                "motion": "barrier pulse",
                "transition": "cut",
                "provider_settings": ui("ui_block"),
            },
            {
                "type": "hodor_spin",
                "duration_sec": 1.0,
                "prompt": "hodor spins up",
                "overlay": "HODOR",
                "camera": "center frame",
                "motion": "rotation build-up",
                "transition": "cut",
                "provider_settings": hodor("hodor_spin"),
            },
            {
                "type": "impact",
                "duration_sec": 1.0,
                "prompt": "hodor impact destroys block",
                "overlay": "Выбрасывает блок",
                "camera": "center frame",
                "motion": "impact flash",
                "transition": "cut",
                "provider_settings": hodor("hodor_impact"),
            },
            {
                "type": "result",
                "duration_sec": 0.9,
                "prompt": "access restored ui clip",
                "overlay": "Работает",
                "camera": "close-up",
                "motion": "clean reveal",
                "transition": "cut",
                "provider_settings": ui("ui_clear"),
            },
            {
                "type": "brand_reveal",
                "duration_sec": 1.7,
                "prompt": "final neon hodor reveal",
                "overlay": "HODOR\nРаботает прямо в Telegram",
                "camera": "close-up",
                "motion": "slow neon resolve",
                "transition": "fade",
                "provider_settings": hodor(
                    "hodor_final",
                    background_blur=36,
                    background_brightness=-0.10,
                    background_saturation=0.70,
                    image_scale=0.58,
                    zoom_end=1.12,
                ),
            },
        ],
        "video_provider": "reference",
        "allow_synthetic_video": False,
        "tts_provider": args.tts_provider,
        "music_provider": args.music_provider,
        "brand_overlay": False,
        "subtitles": True,
        "template": "dark_cinematic",
        "max_parallel_video_shots": 1,
        "music_mode": "library",
        "export_resolution": render_resolution,
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
    default_demo_trend_path = (root / "storage" / "input" / "demo" / "hodor_trend.mp4").resolve()
    if not trend_video_path.exists():
        if args.skip_demo_trend:
            raise FileNotFoundError(f"Trend video not found: {trend_video_path}")
        generate_demo_trend_video(trend_video_path)

    if args.provider == "reference" and trend_video_path == default_demo_trend_path and not args.allow_demo_trend:
        raise ValueError(
            "Reference pipeline needs a real trend clip. "
            "Pass --trend-video /path/to/trend.mp4. "
            "Use --allow-demo-trend only for smoke tests."
        )

    logo_path = Path(args.logo_path).resolve()
    if not logo_path.exists():
        raise FileNotFoundError(f"Logo file not found: {logo_path}")

    if args.provider == "comfyui":
        if args.mode in {"image", "image_to_video", "image2video"}:
            reference_image = Path(args.reference_image or args.logo_path).resolve()
            if not reference_image.exists():
                raise FileNotFoundError(f"Reference image not found: {reference_image}")
        if args.mode in {"video", "video_to_video", "video2video"}:
            reference_video = Path(args.reference_video or args.trend_video).resolve()
            if not reference_video.exists():
                raise FileNotFoundError(f"Reference video not found: {reference_video}")

    job_config = build_job_config(args, root)

    async with AsyncSessionLocal() as session:
        project = await ProjectService.create(
            session,
            ProjectCreate(
                name=args.project_name,
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
                duration_sec=int(job_config.get("duration_sec_override") or args.duration_sec),
                scene_count=int(job_config.get("scene_count_override") or args.scene_count),
                config_json=job_config,
            ),
        )

    await run_job_pipeline(job.id)

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
    export_basename = f"{args.output_prefix}_{job_config['generation_mode']}_{job_config['quality_preset']}_{args.provider}"
    export_video = export_dir / f"{export_basename}.mp4"
    export_preview = export_dir / f"{export_basename}.jpg"
    export_subtitles = export_dir / f"{export_basename}.srt"
    export_metadata = export_dir / f"{export_basename}.json"

    shutil.copy2(final_video, export_video)
    shutil.copy2(preview_image, export_preview)
    shutil.copy2(subtitles, export_subtitles)
    shutil.copy2(metadata_json, export_metadata)

    return {
        "job_id": detail.id,
        "status": detail.status.value,
        "provider": args.provider,
        "generation_mode": job_config["generation_mode"],
        "quality_preset": job_config["quality_preset"],
        "final_video": str(export_video),
        "preview_image": str(export_preview),
        "subtitles": str(export_subtitles),
        "metadata_json": str(export_metadata),
        "storage_job_output": str(final_video.parent),
        "pipeline_state_path": outputs.get("pipeline_state_path"),
        "workflow_path": job_config["shot_overrides"][0]["provider_settings"].get("workflow_path"),
    }


def main() -> None:
    args = parse_args()
    root = configure_environment(args)
    prepare_workflows(root, args)
    _, started_comfyui = ensure_comfyui_running(root, args)
    try:
        result = asyncio.run(run_pipeline(args, root))
    finally:
        stop_started_comfyui(started_comfyui)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
