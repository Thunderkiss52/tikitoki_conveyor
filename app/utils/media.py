from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.utils.storage import write_text

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional dependency
    imageio_ffmpeg = None


def run_command(command: list[str]) -> None:
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{stderr}") from exc


def ffmpeg_available() -> bool:
    return _resolve_ffmpeg_bin() is not None


def ffprobe_media(input_path: Path) -> dict[str, Any]:
    ffprobe_bin = _resolve_ffprobe_bin()
    if ffprobe_bin is not None:
        command = [
            ffprobe_bin,
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

    if imageio_ffmpeg is None:
        wav_metadata = _probe_wav_audio(input_path)
        if wav_metadata is not None:
            return wav_metadata
        raise RuntimeError("Neither ffprobe nor imageio-ffmpeg are available for media probing.")

    try:
        reader = imageio_ffmpeg.read_frames(str(input_path))
        metadata = next(reader)
        source_size = metadata.get("source_size") or metadata.get("size") or (None, None)
        width, height = source_size
        return {
            "duration_sec": float(metadata.get("duration") or 0),
            "fps": float(metadata.get("fps") or 0) or None,
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}" if width and height else None,
            "has_audio": None,
            "codec": metadata.get("codec"),
        }
    except Exception:
        wav_metadata = _probe_wav_audio(input_path)
        if wav_metadata is not None:
            return wav_metadata
        raise


def extract_frames(input_path: Path, output_dir: Path, max_frames: int = 4) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame_%03d.jpg"
    command = [
        _ffmpeg_bin_or_raise(),
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
        _ffmpeg_bin_or_raise(),
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
        _ffmpeg_bin_or_raise(),
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
        _ffmpeg_bin_or_raise(),
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


def generate_procedural_music(output_path: Path, duration_sec: float, mood: str) -> Path:
    mood_value = (mood or "").lower()
    if any(keyword in mood_value for keyword in ("impact", "build-up", "build up", "drop", "collision", "hit")):
        build_end = max(duration_sec * 0.34, 1.8)
        drop_end = max(duration_sec * 0.56, build_end + 0.45)
        command = [
            _ffmpeg_bin_or_raise(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=58:sample_rate=48000:duration={duration_sec:.2f}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=116:sample_rate=48000:duration={duration_sec:.2f}",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=pink:sample_rate=48000:duration={duration_sec:.2f}",
            "-filter_complex",
            (
                "[0:a]volume=0.24,aecho=0.8:0.5:60:0.16[drone];"
                "[1:a]lowpass=f=950,apulsator=hz=2.9:amount=0.92,volume=0.21[pulse];"
                "[2:a]lowpass=f=2100,highpass=f=190,volume=0.036[noise];"
                f"[drone][pulse][noise]amix=inputs=3:normalize=0,"
                f"volume='if(lt(t,{build_end:.2f}),0.34+0.20*t,if(lt(t,{drop_end:.2f}),0.98,0.26))',"
                "alimiter=limit=0.96[a]"
            ),
            "-map",
            "[a]",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        run_command(command)
        return output_path

    low_frequency = 52
    pulse_frequency = 104
    pulse_rate = 1.7
    drone_volume = 0.26
    pulse_volume = 0.18
    noise_volume = 0.042

    if "comic" in mood_value or "fun" in mood_value:
        low_frequency = 82
        pulse_frequency = 196
        pulse_rate = 2.4
        drone_volume = 0.18
        pulse_volume = 0.16
        noise_volume = 0.024
    elif "bright" in mood_value or "upbeat" in mood_value:
        low_frequency = 74
        pulse_frequency = 148
        pulse_rate = 2.1
        drone_volume = 0.2
        pulse_volume = 0.18
        noise_volume = 0.028

    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={low_frequency}:sample_rate=48000:duration={duration_sec:.2f}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={pulse_frequency}:sample_rate=48000:duration={duration_sec:.2f}",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:sample_rate=48000:duration={duration_sec:.2f}",
        "-filter_complex",
        (
            f"[0:a]volume={drone_volume:.3f},aecho=0.8:0.6:60:0.22[drone];"
            f"[1:a]lowpass=f=900,apulsator=hz={pulse_rate:.2f}:amount=0.86,volume={pulse_volume:.3f}[pulse];"
            f"[2:a]lowpass=f=1400,highpass=f=180,volume={noise_volume:.3f}[noise];"
            "[drone][pulse][noise]amix=inputs=3:normalize=0,volume=1.7,alimiter=limit=0.96[a]"
        ),
        "-map",
        "[a]",
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
        _ffmpeg_bin_or_raise(),
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
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command)
    return output_path


def concat_audio(paths: list[Path], output_path: Path) -> Path:
    list_file = output_path.parent / "_audio_concat.txt"
    _write_concat_file(list_file, paths)
    command = [
        _ffmpeg_bin_or_raise(),
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


def fit_audio_to_duration(input_path: Path, output_path: Path, duration_sec: float) -> Path:
    media_info = ffprobe_media(input_path)
    source_duration = float(media_info.get("duration_sec") or 0)
    if source_duration <= 0:
        shutil.copy2(input_path, output_path)
        return output_path

    audio_filter = "anull"
    if source_duration > duration_sec and duration_sec > 0:
        tempo = max(0.5, min(2.0, source_duration / duration_sec))
        audio_filter = f"atempo={tempo:.5f}"

    if source_duration < duration_sec:
        padding = max(0.0, duration_sec - source_duration)
        audio_filter = f"{audio_filter},apad=pad_dur={padding:.3f}"

    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-i",
        str(input_path),
        "-af",
        audio_filter,
        "-t",
        f"{duration_sec:.2f}",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run_command(command)
    return output_path


def loop_audio_to_duration(input_path: Path, output_path: Path, duration_sec: float) -> Path:
    command = [
        _ffmpeg_bin_or_raise(),
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
            _ffmpeg_bin_or_raise(),
            "-y",
            "-i",
            str(music_path),
            "-i",
            str(voice_path),
            "-filter_complex",
            "[0:a]highpass=f=40,lowpass=f=12000,volume=2.25[music];"
            "[music][1:a]sidechaincompress=threshold=0.02:ratio=12:attack=15:release=280[ducked];"
            "[ducked][1:a]amix=inputs=2:weights='1.0 1.12':normalize=0,alimiter=limit=0.96[a]",
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
    command = [_ffmpeg_bin_or_raise(), "-y", "-i", str(video_path)]
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
        filters.append(f"[{logo_index}:v]scale=w=220:h=220:force_original_aspect_ratio=decrease[logo]")
        filters.append(f"{current_label}[logo]overlay=W-w-48:48[vlogo]")
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
            "-preset",
            "slow",
            "-crf",
            "18",
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
    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        _quality_scale_filter(width, height),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
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
        _ffmpeg_bin_or_raise(),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "thumbnail,scale=720:-1:flags=lanczos",
        "-frames:v",
        "1",
        str(output_path),
    ]
    run_command(command)
    return output_path


def convert_video_to_mp4(input_path: Path, output_path: Path) -> Path:
    command = [
        _ffmpeg_bin_or_raise(),
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


def fit_video_to_duration(input_path: Path, output_path: Path, duration_sec: float) -> Path:
    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(input_path),
        "-t",
        f"{duration_sec:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
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
    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-loop",
        "1",
        "-i",
        str(input_path),
        "-t",
        f"{duration_sec:.2f}",
        "-vf",
        _quality_scale_filter(width, height),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command)
    return output_path


def render_reference_video_clip(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    duration_sec: float,
    output_duration_sec: float,
    width: int,
    height: int,
    *,
    speed: float = 1.0,
    punch_in: float = 1.04,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    sharpen: float = 0.0,
    fps: float = 30.0,
    fade_in_sec: float = 0.0,
    fade_out_sec: float = 0.0,
) -> Path:
    source_duration = max(0.1, float(duration_sec))
    target_duration = max(0.1, float(output_duration_sec))
    filter_parts = [
        _cover_crop_filter(width, height, punch_in),
        f"setpts=PTS/{max(speed, 0.1):.5f}",
        f"eq=brightness={brightness:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f}",
    ]
    if sharpen > 0:
        filter_parts.append(f"unsharp=5:5:{sharpen:.3f}:5:5:0.0")
    if fade_in_sec > 0:
        filter_parts.append(f"fade=t=in:st=0:d={fade_in_sec:.2f}")
    if fade_out_sec > 0:
        filter_parts.append(f"fade=t=out:st={max(target_duration - fade_out_sec, 0):.2f}:d={fade_out_sec:.2f}")
    filter_parts.extend([f"fps={fps:.2f}", "format=yuv420p"])

    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-ss",
        f"{start_sec:.2f}",
        "-i",
        str(input_path),
        "-t",
        f"{source_duration:.2f}",
        "-an",
        "-vf",
        ",".join(filter_parts),
        "-t",
        f"{target_duration:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command)
    return output_path


def render_brand_reveal_clip(
    input_path: Path,
    output_path: Path,
    duration_sec: float,
    width: int,
    height: int,
    *,
    fps: float = 30.0,
    fade_in_sec: float = 0.35,
    background_blur: int = 30,
    background_brightness: float = -0.05,
    background_saturation: float = 0.82,
    image_scale: float = 0.72,
    zoom_end: float = 1.08,
) -> Path:
    target_duration = max(0.1, float(duration_sec))
    frames = max(1, int(round(target_duration * max(fps, 1.0))))
    fg_width = max(160, int(width * max(min(image_scale, 0.95), 0.25)))
    fg_height = max(160, int(height * max(min(image_scale, 0.95), 0.25)))
    zoom_step = max((zoom_end - 1.0) / max(frames, 1), 0.00015)
    blur_radius = max(int(background_blur), 1)

    filter_complex = (
        "[0:v]split=2[bgsrc][fgsrc];"
        f"[bgsrc]{_cover_crop_filter(width, height)},boxblur={blur_radius}:2,"
        f"eq=brightness={background_brightness:.3f}:contrast=1.08:saturation={background_saturation:.3f}[bg];"
        f"[fgsrc]{_cover_crop_filter(fg_width, fg_height)},"
        f"zoompan=z='min(zoom+{zoom_step:.6f},{zoom_end:.4f})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={fg_width}x{fg_height}:fps={fps:.2f},"
        "format=rgba,colorchannelmixer=aa=0.98[fg];"
        f"[fg]fade=t=in:st=0:d={fade_in_sec:.2f}:alpha=1[fga];"
        f"[bg][fga]overlay=(W-w)/2:(H-h)/2:format=auto,fade=t=in:st=0:d={fade_in_sec:.2f},format=yuv420p[v]"
    )
    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-loop",
        "1",
        "-i",
        str(input_path),
        "-t",
        f"{target_duration:.2f}",
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-r",
        f"{fps:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command)
    return output_path


def render_phone_ui_clip(
    output_path: Path,
    duration_sec: float,
    width: int,
    height: int,
    *,
    state: str,
    fps: float = 30.0,
) -> Path:
    target_duration = max(0.1, float(duration_sec))
    phone_w = int(width * 0.58)
    phone_h = int(height * 0.76)
    phone_x = (width - phone_w) // 2
    phone_y = int(height * 0.11)
    screen_w = int(phone_w * 0.88)
    screen_h = int(phone_h * 0.88)
    screen_x = phone_x + (phone_w - screen_w) // 2
    screen_y = phone_y + int(phone_h * 0.07)
    notch_w = int(phone_w * 0.22)
    notch_h = max(10, int(phone_h * 0.022))
    notch_x = phone_x + (phone_w - notch_w) // 2
    notch_y = phone_y + int(phone_h * 0.015)
    status_bar_h = max(18, int(screen_h * 0.06))
    barrier_y = screen_y + int(screen_h * 0.38)
    barrier_h = int(screen_h * 0.16)
    crop_w = int(width * 0.96)
    crop_h = int(height * 0.96)

    filter_parts = [
        f"drawbox=x=0:y=0:w={width}:h={height}:color=0x050b14:t=fill",
        f"drawbox=x={phone_x}:y={phone_y}:w={phone_w}:h={phone_h}:color=0x0d1628:t=fill",
        f"drawbox=x={phone_x}:y={phone_y}:w={phone_w}:h={phone_h}:color=0x68b7ff@0.22:t=10",
        f"drawbox=x={screen_x}:y={screen_y}:w={screen_w}:h={screen_h}:color=0x0b1220:t=fill",
        f"drawbox=x={notch_x}:y={notch_y}:w={notch_w}:h={notch_h}:color=black@0.88:t=fill",
        f"drawbox=x={screen_x}:y={screen_y}:w={screen_w}:h={status_bar_h}:color=0x0f1f39:t=fill",
    ]

    if state == "problem":
        filter_parts.extend(
            [
                f"drawbox=x={screen_x + int(screen_w * 0.12)}:y={screen_y + int(screen_h * 0.20)}:"
                f"w={int(screen_w * 0.76)}:h={int(screen_h * 0.17)}:color=0x61171a:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.12)}:y={screen_y + int(screen_h * 0.20)}:"
                f"w={int(screen_w * 0.76)}:h={int(screen_h * 0.17)}:color=0xff4457@0.65:t=5",
                f"drawbox=x={screen_x + int(screen_w * 0.42)}:y={screen_y + int(screen_h * 0.235)}:"
                f"w={int(screen_w * 0.16)}:h={int(screen_h * 0.07)}:color=white@0.92:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.14)}:y={screen_y + int(screen_h * 0.58)}:"
                f"w={int(screen_w * 0.72)}:h={int(screen_h * 0.08)}:color=0x1b2438:t=fill",
                f"crop={crop_w}:{crop_h}:x='(in_w-out_w)/2+sin(t*10)*10':"
                f"y='(in_h-out_h)/2+cos(t*12)*6',scale={width}:{height}:flags=lanczos",
            ]
        )
    elif state == "blocked":
        filter_parts.extend(
            [
                f"drawbox=x={screen_x + int(screen_w * 0.06)}:y={barrier_y}:w={int(screen_w * 0.88)}:"
                f"h={barrier_h}:color=0x1a0204@0.92:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.06)}:y={barrier_y}:w={int(screen_w * 0.88)}:"
                f"h={barrier_h}:color=0xff334a@0.92:t=6",
                f"drawbox=x={screen_x + int(screen_w * 0.10)}:y={barrier_y + int(barrier_h * 0.18)}:"
                f"w={int(screen_w * 0.80)}:h={max(3, int(barrier_h * 0.12))}:color=0xff5164@0.90:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.10)}:y={barrier_y + int(barrier_h * 0.70)}:"
                f"w={int(screen_w * 0.80)}:h={max(3, int(barrier_h * 0.12))}:color=0xff5164@0.90:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.24)}:y={barrier_y + int(barrier_h * 0.34)}:"
                f"w={int(screen_w * 0.52)}:h={max(10, int(barrier_h * 0.18))}:color=white@0.88:t=fill",
                f"crop={crop_w}:{crop_h}:x='(in_w-out_w)/2+sin(t*8)*6':"
                f"y='(in_h-out_h)/2+cos(t*9)*4',scale={width}:{height}:flags=lanczos",
            ]
        )
    else:
        filter_parts.extend(
            [
                f"drawbox=x={screen_x}:y={screen_y}:w={screen_w}:h={screen_h}:color=0x0e2a4d:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.12)}:y={screen_y + int(screen_h * 0.20)}:"
                f"w={int(screen_w * 0.76)}:h={int(screen_h * 0.16)}:color=0x123a68:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.12)}:y={screen_y + int(screen_h * 0.46)}:"
                f"w={int(screen_w * 0.76)}:h={int(screen_h * 0.11)}:color=0x0f2340:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.22)}:y={screen_y + int(screen_h * 0.67)}:"
                f"w={int(screen_w * 0.56)}:h={int(screen_h * 0.10)}:color=0x18d77d:t=fill",
                f"drawbox=x={screen_x + int(screen_w * 0.40)}:y={screen_y + int(screen_h * 0.695)}:"
                f"w={int(screen_w * 0.20)}:h={max(10, int(screen_h * 0.035))}:color=white@0.95:t=fill",
                f"crop={crop_w}:{crop_h}:x='(in_w-out_w)/2':y='(in_h-out_h)/2-6',scale={width}:{height}:flags=lanczos",
            ]
        )

    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x050b14:s={width}x{height}:d={target_duration:.2f}:r={fps:.2f}",
        "-vf",
        ",".join(filter_parts),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command)
    return output_path


def render_hodor_action_clip(
    input_path: Path,
    output_path: Path,
    duration_sec: float,
    width: int,
    height: int,
    *,
    action: str,
    fps: float = 30.0,
) -> Path:
    target_duration = max(0.1, float(duration_sec))
    barrier_y = int(height * 0.39)
    barrier_h = int(height * 0.17)
    crop_w = int(width * 0.96)
    crop_h = int(height * 0.96)

    if action == "impact":
        impact_time = target_duration * 0.56
        filter_complex = (
            f"color=c=0x040a13:s={width}x{height}:d={target_duration:.2f}:r={fps:.2f}[bg];"
            f"[0:v]scale=w='{int(width * 0.34)}+({int(width * 0.86)}*t/{target_duration:.2f})':"
            f"h=-1:eval=frame,format=rgba,rotate='8*PI*t/{target_duration:.2f}':"
            "ow='rotw(iw)':oh='roth(ih)':c=black@0,split=2[fg][glow];"
            "[glow]boxblur=22:2,colorchannelmixer=aa=0.52[glowb];"
            f"[bg]drawbox=x={int(width * 0.10)}:y={barrier_y}:w={int(width * 0.80)}:h={barrier_h}:"
            f"color=0x120204@0.94:t=fill:enable='lt(t,{impact_time:.2f})',"
            f"drawbox=x={int(width * 0.10)}:y={barrier_y}:w={int(width * 0.80)}:h={barrier_h}:"
            f"color=0xff2f45@0.95:t=6:enable='lt(t,{impact_time:.2f})',"
            f"drawbox=x={int(width * 0.28)}:y={barrier_y + int(barrier_h * 0.34)}:w={int(width * 0.44)}:"
            f"h={max(10, int(barrier_h * 0.18))}:color=white@0.90:t=fill:enable='lt(t,{impact_time:.2f})'[bg1];"
            "[bg1][glowb]overlay=(W-w)/2:(H-h)/2[tmp];"
            "[tmp][fg]overlay=(W-w)/2:(H-h)/2[core];"
            f"[core]drawbox=x=0:y=0:w={width}:h={height}:color=white@0.92:t=fill:"
            f"enable='between(t,{impact_time:.2f},{impact_time + 0.08:.2f})',"
            f"crop={crop_w}:{crop_h}:x='(in_w-out_w)/2+if(between(t,{impact_time - 0.03:.2f},{impact_time + 0.16:.2f}),sin(t*140)*14,0)':"
            f"y='(in_h-out_h)/2+if(between(t,{impact_time - 0.03:.2f},{impact_time + 0.16:.2f}),cos(t*120)*10,0)',"
            f"scale={width}:{height}:flags=lanczos,format=yuv420p[v]"
        )
    else:
        filter_complex = (
            f"color=c=0x040a13:s={width}x{height}:d={target_duration:.2f}:r={fps:.2f}[bg];"
            f"[0:v]scale=w='{int(width * 0.44)}+({int(width * 0.16)}*t/{target_duration:.2f})':"
            f"h=-1:eval=frame,format=rgba,rotate='6*PI*t/{target_duration:.2f}':"
            "ow='rotw(iw)':oh='roth(ih)':c=black@0,split=2[fg][glow];"
            "[glow]boxblur=18:2,colorchannelmixer=aa=0.44[glowb];"
            "[bg][glowb]overlay=(W-w)/2:(H-h)/2[tmp];"
            "[tmp][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
        )

    command = [
        _ffmpeg_bin_or_raise(),
        "-y",
        "-loop",
        "1",
        "-i",
        str(input_path),
        "-t",
        f"{target_duration:.2f}",
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-r",
        f"{fps:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
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


def _quality_scale_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        "setsar=1,format=yuv420p"
    )


def _cover_crop_filter(width: int, height: int, zoom: float = 1.0) -> str:
    scaled_width = max(width, int(math.ceil(width * max(zoom, 1.0))))
    scaled_height = max(height, int(math.ceil(height * max(zoom, 1.0))))
    return (
        f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height}"
    )


def _probe_wav_audio(input_path: Path) -> dict[str, Any] | None:
    if input_path.suffix.lower() != ".wav" or not input_path.exists():
        return None
    with wave.open(str(input_path), "rb") as handle:
        frame_rate = handle.getframerate()
        frame_count = handle.getnframes()
        duration = frame_count / float(frame_rate or 1)
        return {
            "duration_sec": duration,
            "fps": None,
            "width": None,
            "height": None,
            "resolution": None,
            "has_audio": True,
            "codec": "pcm_s16le",
        }


def _resolve_ffmpeg_bin() -> str | None:
    configured = _existing_binary(settings.FFMPEG_BIN)
    if configured:
        return configured
    if imageio_ffmpeg is None:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def _ffmpeg_bin_or_raise() -> str:
    resolved = _resolve_ffmpeg_bin()
    if resolved is None:
        raise RuntimeError("ffmpeg binary was not found. Install ffmpeg or add imageio-ffmpeg.")
    return resolved


def _resolve_ffprobe_bin() -> str | None:
    configured = _existing_binary(settings.FFPROBE_BIN)
    if configured:
        return configured
    return None


def _existing_binary(value: str | None) -> str | None:
    if not value:
        return None
    as_path = Path(value)
    if as_path.exists():
        return str(as_path)
    return shutil.which(value)
