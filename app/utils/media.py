from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.utils.storage import write_text


def run_command(command: list[str]) -> None:
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{stderr}") from exc


def ffmpeg_available() -> bool:
    return shutil.which(settings.FFMPEG_BIN) is not None


def ffprobe_media(input_path: Path) -> dict[str, Any]:
    command = [
        settings.FFPROBE_BIN,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(input_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout or "{}")

    video_stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), {})
    audio_stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), {})
    width = video_stream.get("width")
    height = video_stream.get("height")

    return {
        "duration_sec": float(payload.get("format", {}).get("duration") or video_stream.get("duration") or 0),
        "fps": _parse_frame_rate(video_stream.get("avg_frame_rate")),
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else None,
        "has_audio": bool(audio_stream),
        "codec": video_stream.get("codec_name"),
    }


def extract_frames(input_path: Path, output_dir: Path, max_frames: int = 4) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame_%03d.jpg"
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "fps=1,scale=540:-1",
        "-frames:v",
        str(max_frames),
        str(pattern),
    ]
    run_command(command)
    return sorted(output_dir.glob("frame_*.jpg"))


def generate_color_clip(
    output_path: Path,
    duration_sec: float,
    width: int,
    height: int,
    seed: str,
) -> Path:
    color = _color_from_seed(seed)
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}:d={duration_sec:.2f}:r=30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    run_command(command)
    return output_path


def generate_silent_audio(output_path: Path, duration_sec: float) -> Path:
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-t",
        f"{duration_sec:.2f}",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run_command(command)
    return output_path


def generate_tone_audio(output_path: Path, duration_sec: float, frequency: int = 220, volume: float = 0.08) -> Path:
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000",
        "-filter:a",
        f"volume={volume}",
        "-t",
        f"{duration_sec:.2f}",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run_command(command)
    return output_path


def concat_video(paths: list[Path], output_path: Path) -> Path:
    list_file = output_path.parent / "_video_concat.txt"
    _write_concat_file(list_file, paths)
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    run_command(command)
    return output_path


def concat_audio(paths: list[Path], output_path: Path) -> Path:
    list_file = output_path.parent / "_audio_concat.txt"
    _write_concat_file(list_file, paths)
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run_command(command)
    return output_path


def loop_audio_to_duration(input_path: Path, output_path: Path, duration_sec: float) -> Path:
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(input_path),
        "-t",
        f"{duration_sec:.2f}",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run_command(command)
    return output_path


def mix_audio(voice_path: Path | None, music_path: Path | None, output_path: Path) -> Path | None:
    if voice_path and music_path:
        command = [
            settings.FFMPEG_BIN,
            "-y",
            "-i",
            str(music_path),
            "-i",
            str(voice_path),
            "-filter_complex",
            "[0:a][1:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=250[ducked];"
            "[ducked][1:a]amix=inputs=2:weights='0.35 1.0':normalize=0[a]",
            "-map",
            "[a]",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        run_command(command)
        return output_path

    if voice_path:
        shutil.copy2(voice_path, output_path)
        return output_path

    if music_path:
        shutil.copy2(music_path, output_path)
        return output_path

    return None


def mux_video_with_audio(
    video_path: Path,
    output_path: Path,
    audio_path: Path | None = None,
    subtitles_path: Path | None = None,
    logo_path: Path | None = None,
) -> Path:
    command = [settings.FFMPEG_BIN, "-y", "-i", str(video_path)]
    logo_index = None
    audio_index = None

    if logo_path and logo_path.exists():
        logo_index = 1
        command.extend(["-i", str(logo_path)])

    if audio_path and audio_path.exists():
        audio_index = len([part for part in command if part == "-i"])
        command.extend(["-i", str(audio_path)])

    filters: list[str] = []
    current_label = "[0:v]"

    if logo_index is not None:
        filters.append(f"{current_label}[{logo_index}:v]overlay=W-w-48:48[vlogo]")
        current_label = "[vlogo]"

    if subtitles_path and subtitles_path.exists():
        escaped_subtitles_path = _escape_filter_path(subtitles_path)
        filters.append(f"{current_label}subtitles={escaped_subtitles_path}[vsub]")
        current_label = "[vsub]"

    if filters:
        command.extend(["-filter_complex", ";".join(filters), "-map", current_label])
    else:
        command.extend(["-map", "0:v:0"])

    if audio_index is not None:
        command.extend(["-map", f"{audio_index}:a:0", "-c:a", "aac", "-b:a", "192k"])
    else:
        command.append("-an")

    command.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    run_command(command)
    return output_path


def transcode_for_platform(input_path: Path, output_path: Path, width: int, height: int) -> Path:
    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        scale_filter,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command)
    return output_path


def extract_thumbnail(input_path: Path, output_path: Path) -> Path:
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "thumbnail,scale=540:-1",
        "-frames:v",
        "1",
        str(output_path),
    ]
    run_command(command)
    return output_path


def convert_video_to_mp4(input_path: Path, output_path: Path) -> Path:
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(output_path),
    ]
    run_command(command)
    return output_path


def loop_image_to_video(input_path: Path, output_path: Path, duration_sec: float, width: int, height: int) -> Path:
    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-loop",
        "1",
        "-i",
        str(input_path),
        "-t",
        f"{duration_sec:.2f}",
        "-vf",
        scale_filter,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    run_command(command)
    return output_path


def _parse_frame_rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    numerator, denominator = value.split("/")
    denominator_value = float(denominator)
    if denominator_value == 0:
        return None
    return round(float(numerator) / denominator_value, 2)


def _color_from_seed(seed: str) -> str:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()[:6]
    return f"0x{digest}"


def _write_concat_file(path: Path, items: list[Path]) -> None:
    content = "\n".join(f"file '{item.resolve()}'" for item in items)
    write_text(path, content)


def _escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:")
