from __future__ import annotations

import json
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.models.pipeline import ShotSpec
from app.utils.media import convert_video_to_mp4, loop_image_to_video
from app.utils.storage import resolve_local_path, safe_slug


class ComfyUIVideoProvider:
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    ANIMATED_EXTENSIONS = {".gif"}

    def __init__(self) -> None:
        self.base_url = settings.COMFYUI_BASE_URL.rstrip("/")
        self.timeout_sec = settings.COMFYUI_TIMEOUT_SEC
        self.poll_interval_sec = settings.COMFYUI_POLL_INTERVAL_SEC
        self.default_workflow_template = settings.COMFYUI_WORKFLOW_TEMPLATE

    def generate(self, shot_spec: ShotSpec, output_path: Path, config: dict[str, object]) -> Path:
        provider_settings = dict(config.get("provider_settings") or {})
        workflow_path = self._workflow_path(provider_settings)
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        client_id = str(uuid4())

        context = self._build_context(shot_spec, output_path, config, provider_settings)
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_sec) as client:
            uploads = self._upload_reference_images(client, provider_settings)
            self._apply_mapping(workflow, provider_settings.get("workflow_mapping"), {**context, **uploads})
            self._apply_heuristics(workflow, context, uploads)

            prompt_id = self._queue_prompt(client, workflow, client_id)
            history_payload = self._wait_for_history(client, prompt_id)
            artifact = self._best_output_artifact(history_payload)
            if artifact is None:
                raise RuntimeError("ComfyUI finished without downloadable outputs.")

            downloaded_path = self._download_output(client, artifact, output_path.parent)
            return self._normalize_output(downloaded_path, output_path, shot_spec, context)

    def _workflow_path(self, provider_settings: dict[str, Any]) -> Path:
        explicit_workflow_path = provider_settings.get("workflow_path")
        configured_path = explicit_workflow_path or self.default_workflow_template
        path = resolve_local_path(str(configured_path))
        if not path.exists():
            raise FileNotFoundError(
                "ComfyUI workflow JSON not found. "
                f"Checked: {path}. Set provider_settings.workflow_path or COMFYUI_WORKFLOW_TEMPLATE."
            )
        if explicit_workflow_path is None and path.name.endswith(".example.json"):
            raise ValueError(
                "ComfyUI provider needs a real workflow JSON in API format. "
                "Set provider_settings.workflow_path to your exported workflow file."
            )
        return path

    def _build_context(
        self,
        shot_spec: ShotSpec,
        output_path: Path,
        config: dict[str, object],
        provider_settings: dict[str, Any],
    ) -> dict[str, Any]:
        width, height = self._resolve_resolution(config, provider_settings)
        filename_prefix = provider_settings.get("filename_prefix") or f"job_{safe_slug(output_path.stem)}"
        return {
            "prompt": shot_spec.prompt,
            "negative_prompt": str(config.get("negative_prompt") or ""),
            "width": width,
            "height": height,
            "frames": self._coerce_int(provider_settings.get("frames")),
            "steps": self._coerce_int(provider_settings.get("steps")),
            "cfg": self._coerce_float(provider_settings.get("cfg")),
            "seed": self._coerce_int(provider_settings.get("seed")),
            "fps": self._coerce_float(provider_settings.get("fps")),
            "sampler_name": provider_settings.get("sampler_name"),
            "scheduler": provider_settings.get("scheduler"),
            "denoise": self._coerce_float(provider_settings.get("denoise")),
            "filename_prefix": filename_prefix,
            "brand_image_path": (
                provider_settings.get("brand_image_path")
                or config.get("brand_image_path")
                or provider_settings.get("reference_image_path")
            ),
            "output_basename": output_path.stem,
        }

    def _upload_reference_images(self, client: httpx.Client, provider_settings: dict[str, Any]) -> dict[str, str]:
        reference_images = dict(provider_settings.get("reference_images") or {})
        if provider_settings.get("brand_image_path"):
            reference_images.setdefault("brand_image", provider_settings["brand_image_path"])
        if provider_settings.get("reference_image_path"):
            reference_images.setdefault("reference_image", provider_settings["reference_image_path"])

        uploaded: dict[str, str] = {}
        for alias, raw_path in reference_images.items():
            local_path = resolve_local_path(str(raw_path))
            if not local_path.exists():
                raise FileNotFoundError(f"Reference image not found: {local_path}")

            mime_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
            with local_path.open("rb") as file_handle:
                response = client.post(
                    "/upload/image",
                    data={"overwrite": "true", "type": "input"},
                    files={"image": (local_path.name, file_handle, mime_type)},
                )
            response.raise_for_status()
            payload = response.json()
            uploaded[alias] = payload.get("name") or local_path.name
        return uploaded

    def _queue_prompt(self, client: httpx.Client, workflow: dict[str, Any], client_id: str) -> str:
        response = client.post("/prompt", json={"prompt": workflow, "client_id": client_id})
        response.raise_for_status()
        payload = response.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {payload}")
        return str(prompt_id)

    def _wait_for_history(self, client: httpx.Client, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout_sec
        last_payload: dict[str, Any] = {}

        while time.time() < deadline:
            response = client.get(f"/history/{prompt_id}")
            response.raise_for_status()
            payload = response.json()
            last_payload = payload
            prompt_payload = payload.get(prompt_id)
            if prompt_payload:
                status = prompt_payload.get("status", {})
                if status.get("status_str") == "error":
                    messages = status.get("messages") or []
                    raise RuntimeError(f"ComfyUI prompt failed: {messages or prompt_payload}")
                if prompt_payload.get("outputs"):
                    return prompt_payload
            time.sleep(self.poll_interval_sec)

        raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}. Last payload: {last_payload}")

    def _best_output_artifact(self, history_payload: dict[str, Any]) -> dict[str, Any] | None:
        outputs = history_payload.get("outputs", {})
        candidates: list[dict[str, Any]] = []
        for node_output in outputs.values():
            for key in ("videos", "gifs", "images"):
                for item in node_output.get(key, []):
                    candidates.append(item)

        if not candidates:
            return None

        def rank(item: dict[str, Any]) -> tuple[int, str]:
            filename = str(item.get("filename", ""))
            suffix = Path(filename).suffix.lower()
            if suffix in self.VIDEO_EXTENSIONS:
                return (0, filename)
            if suffix in self.ANIMATED_EXTENSIONS:
                return (1, filename)
            if suffix in self.IMAGE_EXTENSIONS:
                return (2, filename)
            return (3, filename)

        return sorted(candidates, key=rank)[0]

    def _download_output(self, client: httpx.Client, artifact: dict[str, Any], target_dir: Path) -> Path:
        filename = str(artifact["filename"])
        response = client.get(
            "/view",
            params={
                "filename": filename,
                "subfolder": artifact.get("subfolder", ""),
                "type": artifact.get("type", "output"),
            },
        )
        response.raise_for_status()

        download_path = target_dir / Path(filename).name
        download_path.write_bytes(response.content)
        return download_path

    def _normalize_output(
        self,
        downloaded_path: Path,
        output_path: Path,
        shot_spec: ShotSpec,
        context: dict[str, Any],
    ) -> Path:
        suffix = downloaded_path.suffix.lower()
        if suffix == output_path.suffix.lower():
            shutil.move(str(downloaded_path), str(output_path))
            return output_path

        if suffix in self.VIDEO_EXTENSIONS or suffix in self.ANIMATED_EXTENSIONS:
            return convert_video_to_mp4(downloaded_path, output_path)

        if suffix in self.IMAGE_EXTENSIONS:
            width = int(context["width"])
            height = int(context["height"])
            return loop_image_to_video(downloaded_path, output_path, shot_spec.duration_sec, width, height)

        raise RuntimeError(f"Unsupported ComfyUI output format: {downloaded_path.name}")

    def _apply_mapping(
        self,
        workflow: dict[str, Any],
        raw_mapping: Any,
        context: dict[str, Any],
    ) -> None:
        if not raw_mapping:
            return

        if not isinstance(raw_mapping, dict):
            raise TypeError("provider_settings.workflow_mapping must be an object")

        for source_key, raw_paths in raw_mapping.items():
            value = context.get(source_key)
            if value is None:
                continue
            paths = raw_paths if isinstance(raw_paths, list) else [raw_paths]
            for path in paths:
                self._set_path(workflow, str(path), value)

    def _apply_heuristics(
        self,
        workflow: dict[str, Any],
        context: dict[str, Any],
        uploads: dict[str, str],
    ) -> None:
        nodes = self._sorted_nodes(workflow)
        clip_nodes = [
            node
            for _, node in nodes
            if str(node.get("class_type", "")).lower().startswith("cliptextencode")
        ]
        if clip_nodes:
            self._set_first_text_input(clip_nodes[0], str(context["prompt"]))
            if len(clip_nodes) > 1 and context.get("negative_prompt"):
                self._set_first_text_input(clip_nodes[1], str(context["negative_prompt"]))

        for _, node in nodes:
            inputs = node.get("inputs", {})
            self._set_scalar_if_present(inputs, "width", context.get("width"))
            self._set_scalar_if_present(inputs, "height", context.get("height"))
            self._set_scalar_if_present(inputs, "steps", context.get("steps"))
            self._set_scalar_if_present(inputs, "cfg", context.get("cfg"))
            self._set_scalar_if_present(inputs, "seed", context.get("seed"))
            self._set_scalar_if_present(inputs, "sampler_name", context.get("sampler_name"))
            self._set_scalar_if_present(inputs, "scheduler", context.get("scheduler"))
            self._set_scalar_if_present(inputs, "denoise", context.get("denoise"))
            self._set_scalar_if_present(inputs, "frame_rate", context.get("fps"))
            self._set_scalar_if_present(inputs, "fps", context.get("fps"))
            self._set_scalar_if_present(inputs, "filename_prefix", context.get("filename_prefix"))

            for frame_key in ("frames", "length", "video_length", "frame_count", "batch_size"):
                self._set_scalar_if_present(inputs, frame_key, context.get("frames"))

        for upload_name in uploads.values():
            self._inject_uploaded_image(nodes, upload_name)

    def _inject_uploaded_image(self, nodes: list[tuple[str, dict[str, Any]]], uploaded_name: str) -> None:
        for _, node in nodes:
            class_type = str(node.get("class_type", "")).lower()
            inputs = node.get("inputs", {})
            if "loadimage" in class_type and isinstance(inputs.get("image"), str):
                inputs["image"] = uploaded_name
                return

    def _set_first_text_input(self, node: dict[str, Any], value: str) -> None:
        inputs = node.get("inputs", {})
        for key in ("text", "prompt", "string"):
            current_value = inputs.get(key)
            if current_value is not None and not isinstance(current_value, list):
                inputs[key] = value
                return

    def _set_scalar_if_present(self, inputs: dict[str, Any], key: str, value: Any) -> None:
        if value is None or key not in inputs:
            return
        if isinstance(inputs[key], list):
            return
        inputs[key] = value

    def _sorted_nodes(self, workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return sorted(workflow.items(), key=lambda item: self._node_sort_key(item[0]))

    def _node_sort_key(self, value: str) -> tuple[int, str]:
        return (0, value) if value.isdigit() else (1, value)

    def _set_path(self, workflow: dict[str, Any], dotted_path: str, value: Any) -> None:
        parts = dotted_path.split(".")
        current: Any = workflow
        for part in parts[:-1]:
            if isinstance(current, dict):
                if part not in current:
                    raise KeyError(f"Invalid workflow mapping path: {dotted_path}")
                current = current[part]
                continue
            raise KeyError(f"Invalid workflow mapping path: {dotted_path}")

        leaf = parts[-1]
        if not isinstance(current, dict):
            raise KeyError(f"Invalid workflow mapping path: {dotted_path}")
        if leaf not in current:
            raise KeyError(f"Invalid workflow mapping path: {dotted_path}")
        current[leaf] = value

    def _resolve_resolution(self, config: dict[str, Any], provider_settings: dict[str, Any]) -> tuple[int, int]:
        raw_resolution = provider_settings.get("resolution")
        if isinstance(raw_resolution, str) and "x" in raw_resolution:
            width, height = raw_resolution.lower().split("x", 1)
            return int(width), int(height)
        if isinstance(raw_resolution, dict):
            width = raw_resolution.get("width")
            height = raw_resolution.get("height")
            if width and height:
                return int(width), int(height)
        return int(config.get("width", 1080)), int(config.get("height", 1920))

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, str) and "-" in value:
            value = value.split("-", 1)[0]
        return int(float(value))

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, str) and "-" in value:
            value = value.split("-", 1)[0]
        return float(value)
