#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def discover_model_name(directory: Path, placeholders: set[str]) -> str:
    candidates = sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name not in placeholders
    )
    if not candidates:
        raise FileNotFoundError(f"No usable model files found in {directory}")
    return candidates[0]


def patch_workflow(data: dict, checkpoint_name: str, motion_name: str, image_name: str | None, video_name: str | None) -> dict:
    for node in data.get("nodes", []):
        node_type = node.get("type")
        widgets = node.get("widgets_values")

        if node_type == "CheckpointLoaderSimple" and isinstance(widgets, list) and widgets:
            widgets[0] = checkpoint_name
        elif node_type == "ADE_AnimateDiffLoaderGen1" and isinstance(widgets, list) and widgets:
            widgets[0] = motion_name
        elif node_type == "LoadImage" and isinstance(widgets, list) and widgets and image_name:
            widgets[0] = image_name
        elif node_type == "VHS_LoadVideo" and isinstance(widgets, dict) and video_name:
            widgets["video"] = video_name
        elif node_type == "VHS_VideoCombine" and isinstance(widgets, dict):
            widgets["format"] = "video/h264-mp4"
    return data


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Patch helper ComfyUI workflows with local model names and input assets.")
    parser.add_argument("--helpers-dir", default=root / "helpers", type=Path)
    parser.add_argument("--output-dir", default=root / "workflows" / "comfyui_ui", type=Path)
    parser.add_argument("--comfyui-dir", default=root / "third_party" / "ComfyUI", type=Path)
    parser.add_argument("--image-source", default=root / "HODOR.jpg", type=Path)
    parser.add_argument("--video-source", type=Path)
    parser.add_argument("--sync-to-comfyui-user", action="store_true")
    args = parser.parse_args()

    checkpoints_dir = args.comfyui_dir / "models" / "checkpoints"
    motion_dir = args.comfyui_dir / "models" / "animatediff_models"
    input_dir = args.comfyui_dir / "input"

    checkpoint_name = discover_model_name(checkpoints_dir, {"put_checkpoints_here"})
    motion_name = discover_model_name(motion_dir, {"put_motion_models_here"})

    input_dir.mkdir(parents=True, exist_ok=True)

    image_name = None
    if args.image_source.exists():
        image_name = args.image_source.name
        shutil.copy2(args.image_source, input_dir / image_name)

    video_name = None
    if args.video_source and args.video_source.exists():
        video_name = args.video_source.name
        shutil.copy2(args.video_source, input_dir / video_name)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    comfyui_user_dir = args.comfyui_dir / "user" / "default" / "workflows" / "hodor_helpers"
    if args.sync_to_comfyui_user:
        comfyui_user_dir.mkdir(parents=True, exist_ok=True)

    for source_path in sorted(args.helpers_dir.glob("*.json")):
        data = json.loads(source_path.read_text(encoding="utf-8"))
        patched = patch_workflow(data, checkpoint_name, motion_name, image_name, video_name)
        rendered = json.dumps(patched, ensure_ascii=False, indent=2) + "\n"

        output_path = args.output_dir / source_path.name
        output_path.write_text(rendered, encoding="utf-8")

        if args.sync_to_comfyui_user:
            (comfyui_user_dir / source_path.name).write_text(rendered, encoding="utf-8")

    print(f"checkpoint={checkpoint_name}")
    print(f"motion_model={motion_name}")
    if image_name:
        print(f"image_input={input_dir / image_name}")
    if video_name:
        print(f"video_input={input_dir / video_name}")
    print(f"workflow_output_dir={args.output_dir}")
    if args.sync_to_comfyui_user:
        print(f"comfyui_user_workflows={comfyui_user_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
