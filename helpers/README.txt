# HODOR ComfyUI workflow pack

Внутри 3 базовых workflow:
- `01_text_to_video_basic.json`
- `02_image_to_video_basic.json`
- `03_video_to_video_soft_remake.json`

Это **базовые стартовые графы** под:
- ComfyUI
- AnimateDiff Evolved
- VideoHelperSuite

## Что менять первым делом
1. `CheckpointLoaderSimple` -> свой checkpoint
2. `ADE_AnimateDiffLoaderGen1` -> свой motion module (`mm_sd_v15_v2.ckpt` или другой совместимый)
3. prompts
4. у image-to-video: файл `input.png`
5. у video-to-video: файл `trend.mp4`

## Рекомендованные стартовые значения для RTX 4060 8GB
- resolution: 576x1024
- frames: 16
- fps: 8
- text-to-video denoise: 1.0
- image-to-video denoise: 0.45-0.60
- video-to-video denoise: 0.35-0.55

## Важно
Video-to-video здесь сделан как **soft remake без ControlNet**.
Если захочешь жестче сохранять композицию/движение трендового ролика, добавь:
- ComfyUI-Advanced-ControlNet
- controlnet aux preprocessors

## Почему так
- AnimateDiff Evolved официально рекомендует VideoHelperSuite для загрузки и сборки видео
- для AnimateDiff + Context Options автор также рекомендует Advanced-ControlNet, если нужен ControlNet/SparseCtrl

## Если workflow не импортируется
Обычно причина одна из этих:
- другой class name узла в твоей версии custom node
- другой формат `widgets_values` в твоей сборке
- нет формата `video/h264-mp4` в VHS
- нет ffmpeg

## Быстрый план теста
1. Сначала открой `02_image_to_video_basic.json`
2. Добейся, чтобы он отработал
3. Потом `01_text_to_video_basic.json`
4. Потом `03_video_to_video_soft_remake.json`

