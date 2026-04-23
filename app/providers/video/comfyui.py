from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.render_presets import build_comfyui_provider_settings
from app.models.pipeline import ShotSpec
from app.utils.media import fit_video_to_duration, loop_image_to_video
from app.utils.storage import resolve_local_path, safe_slug


class ComfyUIVideoProvider:
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    ANIMATED_EXTENSIONS = {".gif"}
    SCALAR_INPUT_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

    def __init__(self) -> None:
        self.base_url = settings.COMFYUI_BASE_URL.rstrip("/")
        self.timeout_sec = settings.COMFYUI_TIMEOUT_SEC
        self.poll_interval_sec = settings.COMFYUI_POLL_INTERVAL_SEC
        self.default_workflow_template = settings.COMFYUI_WORKFLOW_TEMPLATE
        self.input_dir = resolve_local_path(settings.COMFYUI_INPUT_DIR)
        self._object_info_cache: dict[str, dict[str, Any]] = {}

    def generate(self, shot_spec: ShotSpec, output_path: Path, config: dict[str, object]) -> Path:
        provider_settings = build_comfyui_provider_settings(overrides=dict(config.get("provider_settings") or {}))
        workflow_path = self._workflow_path(provider_settings)
        raw_workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        client_id = str(uuid4())

        context = self._build_context(shot_spec, output_path, config, provider_settings)
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_sec) as client:
            workflow = self._prepare_workflow(client, raw_workflow)
            uploads = self._stage_reference_assets(client, provider_settings)
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
                "ComfyUI provider needs either a real workflow JSON or a generation mode with prepared helper workflows. "
                "Set provider_settings.workflow_path or provider_settings.generation_mode."
            )
        return path

    def _prepare_workflow(self, client: httpx.Client, raw_workflow: dict[str, Any]) -> dict[str, Any]:
        if self._looks_like_ui_workflow(raw_workflow):
            return self._convert_ui_workflow_to_api(client, raw_workflow)
        return raw_workflow

    def _looks_like_ui_workflow(self, workflow: dict[str, Any]) -> bool:
        return isinstance(workflow.get("nodes"), list) and isinstance(workflow.get("links"), list)

    def _convert_ui_workflow_to_api(
        self,
        client: httpx.Client,
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        links_by_id: dict[int, list[Any]] = {}
        for raw_link in workflow.get("links", []):
            if isinstance(raw_link, list) and len(raw_link) >= 5:
                links_by_id[int(raw_link[0])] = raw_link

        prompt: dict[str, Any] = {}
        for node in sorted(workflow.get("nodes", []), key=lambda item: int(item.get("id", 0))):
            node_id = str(node["id"])
            class_type = str(node["type"])
            schema = self._object_info(client, class_type)
            inputs = self._convert_ui_node_inputs(node, links_by_id, schema)
            prompt[node_id] = {"class_type": class_type, "inputs": inputs}

            node_title = node.get("title") or node.get("properties", {}).get("Node name for S&R")
            if node_title:
                prompt[node_id]["_meta"] = {"title": str(node_title)}

        return prompt

    def _convert_ui_node_inputs(
        self,
        node: dict[str, Any],
        links_by_id: dict[int, list[Any]],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        connected_names: set[str] = set()

        for raw_input in node.get("inputs", []):
            link_id = raw_input.get("link")
            input_name = raw_input.get("name")
            if link_id is None or input_name is None:
                continue

            link = links_by_id.get(int(link_id))
            if link is None:
                raise KeyError(f"Workflow link {link_id} referenced by node {node.get('id')} was not found.")

            connected_names.add(str(input_name))
            inputs[str(input_name)] = [str(link[1]), int(link[2])]

        widget_values = node.get("widgets_values")
        hidden_inputs = set((schema.get("input", {}) or {}).get("hidden", {}))
        valid_inputs = self._valid_schema_inputs(schema)

        if isinstance(widget_values, dict):
            for key, value in widget_values.items():
                if key in valid_inputs or key in hidden_inputs:
                    inputs[key] = self._normalize_widget_value(value)
            return inputs

        if not isinstance(widget_values, list):
            return inputs

        widget_index = 0
        ordered_widget_inputs = self._ordered_widget_input_names(schema, connected_names)
        for input_name in ordered_widget_inputs:
            if widget_index >= len(widget_values):
                break
            inputs[input_name] = self._normalize_widget_value(widget_values[widget_index])
            widget_index += 1
            if self._has_control_after_generate(schema, input_name):
                widget_index += 1

        return inputs

    def _object_info(self, client: httpx.Client, class_type: str) -> dict[str, Any]:
        cached = self._object_info_cache.get(class_type)
        if cached is not None:
            return cached

        response = client.get(f"/object_info/{class_type}")
        response.raise_for_status()
        payload = response.json()
        schema = payload.get(class_type)
        if not isinstance(schema, dict):
            raise KeyError(f"ComfyUI object_info for {class_type} is missing or malformed.")
        self._object_info_cache[class_type] = schema
        return schema

    def _valid_schema_inputs(self, schema: dict[str, Any]) -> set[str]:
        input_payload = schema.get("input", {}) or {}
        return set(input_payload.get("required", {})) | set(input_payload.get("optional", {}))

    def _ordered_widget_input_names(self, schema: dict[str, Any], connected_names: set[str]) -> list[str]:
        ordered: list[str] = []
        input_payload = schema.get("input", {}) or {}
        input_order = schema.get("input_order", {}) or {}

        for category in ("required", "optional"):
            category_payload = input_payload.get(category, {}) or {}
            for input_name in input_order.get(category, []):
                if input_name in connected_names:
                    continue
                if self._is_widget_input(category_payload.get(input_name)):
                    ordered.append(input_name)

        return ordered

    def _is_widget_input(self, raw_info: Any) -> bool:
        input_type, extra_info = self._parse_input_info(raw_info)
        if isinstance(input_type, list):
            return True
        if input_type in self.SCALAR_INPUT_TYPES:
            return True
        return bool(extra_info.get("forceInput"))

    def _has_control_after_generate(self, schema: dict[str, Any], input_name: str) -> bool:
        input_payload = schema.get("input", {}) or {}
        for category in ("required", "optional", "hidden"):
            if input_name not in (input_payload.get(category, {}) or {}):
                continue
            _, extra_info = self._parse_input_info(input_payload[category][input_name])
            return bool(extra_info.get("control_after_generate"))
        return False

    def _parse_input_info(self, raw_info: Any) -> tuple[Any, dict[str, Any]]:
        if not isinstance(raw_info, list) or not raw_info:
            return raw_info, {}
        input_type = raw_info[0]
        extra_info = raw_info[1] if len(raw_info) > 1 and isinstance(raw_info[1], dict) else {}
        return input_type, extra_info

    def _normalize_widget_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return {"__value__": value}
        return value

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
            "generation_mode": provider_settings.get("generation_mode"),
            "quality_preset": provider_settings.get("quality_preset"),
            "brand_image_path": (
                provider_settings.get("brand_image_path")
                or config.get("brand_image_path")
                or provider_settings.get("reference_image_path")
            ),
            "reference_video_path": provider_settings.get("reference_video_path"),
            "output_basename": output_path.stem,
        }

    def _stage_reference_assets(self, client: httpx.Client, provider_settings: dict[str, Any]) -> dict[str, str]:
        reference_images = dict(provider_settings.get("reference_images") or {})
        reference_videos = dict(provider_settings.get("reference_videos") or {})
        if provider_settings.get("brand_image_path"):
            reference_images.setdefault("brand_image", provider_settings["brand_image_path"])
        if provider_settings.get("reference_image_path"):
            reference_images.setdefault("reference_image", provider_settings["reference_image_path"])
        if provider_settings.get("reference_video_path"):
            reference_videos.setdefault("reference_video", provider_settings["reference_video_path"])

        staged: dict[str, str] = {}
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
            staged[alias] = payload.get("name") or local_path.name

        for alias, raw_path in reference_videos.items():
            local_path = resolve_local_path(str(raw_path))
            if not local_path.exists():
                raise FileNotFoundError(f"Reference video not found: {local_path}")
            staged[alias] = self._stage_local_input_file(local_path)

        return staged

    def _stage_local_input_file(self, local_path: Path) -> str:
        self.input_dir.mkdir(parents=True, exist_ok=True)
        stat = local_path.stat()
        digest = hashlib.md5(
            f"{local_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
        ).hexdigest()[:8]
        staged_name = f"{safe_slug(local_path.stem)}_{digest}{local_path.suffix.lower()}"
        staged_path = self.input_dir / staged_name
        if not staged_path.exists():
            shutil.copy2(local_path, staged_path)
        return staged_name

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
            normalized = fit_video_to_duration(downloaded_path, output_path, shot_spec.duration_sec)
            self._cleanup_intermediate(downloaded_path, output_path)
            return normalized

        if suffix in self.VIDEO_EXTENSIONS or suffix in self.ANIMATED_EXTENSIONS:
            normalized = fit_video_to_duration(downloaded_path, output_path, shot_spec.duration_sec)
            self._cleanup_intermediate(downloaded_path, output_path)
            return normalized

        if suffix in self.IMAGE_EXTENSIONS:
            width = int(context["width"])
            height = int(context["height"])
            normalized = loop_image_to_video(downloaded_path, output_path, shot_spec.duration_sec, width, height)
            self._cleanup_intermediate(downloaded_path, output_path)
            return normalized

        raise RuntimeError(f"Unsupported ComfyUI output format: {downloaded_path.name}")

    def _cleanup_intermediate(self, intermediate_path: Path, output_path: Path) -> None:
        if intermediate_path.resolve() == output_path.resolve():
            return
        if intermediate_path.exists():
            intermediate_path.unlink()

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
            self._set_scalar_if_present(inputs, "custom_width", context.get("width"))
            self._set_scalar_if_present(inputs, "custom_height", context.get("height"))
            self._set_scalar_if_present(inputs, "steps", context.get("steps"))
            self._set_scalar_if_present(inputs, "cfg", context.get("cfg"))
            self._set_scalar_if_present(inputs, "seed", context.get("seed"))
            self._set_scalar_if_present(inputs, "sampler_name", context.get("sampler_name"))
            self._set_scalar_if_present(inputs, "scheduler", context.get("scheduler"))
            self._set_scalar_if_present(inputs, "denoise", context.get("denoise"))
            self._set_scalar_if_present(inputs, "frame_rate", context.get("fps"))
            self._set_scalar_if_present(inputs, "fps", context.get("fps"))
            self._set_scalar_if_present(inputs, "force_rate", context.get("fps"))
            self._set_scalar_if_present(inputs, "filename_prefix", context.get("filename_prefix"))

            for frame_key in ("frames", "length", "video_length", "frame_count", "batch_size", "frame_load_cap"):
                self._set_scalar_if_present(inputs, frame_key, context.get("frames"))

        reference_image = uploads.get("reference_image") or uploads.get("brand_image")
        if reference_image:
            self._inject_uploaded_image(nodes, reference_image)

        reference_video = uploads.get("reference_video")
        if reference_video:
            self._inject_uploaded_video(nodes, reference_video)

    def _inject_uploaded_image(self, nodes: list[tuple[str, dict[str, Any]]], uploaded_name: str) -> None:
        for _, node in nodes:
            class_type = str(node.get("class_type", "")).lower()
            inputs = node.get("inputs", {})
            if "loadimage" in class_type and isinstance(inputs.get("image"), str):
                inputs["image"] = uploaded_name

    def _inject_uploaded_video(self, nodes: list[tuple[str, dict[str, Any]]], uploaded_name: str) -> None:
        for _, node in nodes:
            class_type = str(node.get("class_type", "")).lower()
            inputs = node.get("inputs", {})
            if "loadvideo" in class_type and isinstance(inputs.get("video"), str):
                inputs["video"] = uploaded_name

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
