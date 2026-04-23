# Tikitoki Conveyor

Модульный монолит для генерации коротких видео по трендовому референсу: ingest → analyze → script → plan → generate → compose → export.

Система не пытается быть "одной магической моделью". Каждый этап изолирован, а AI-провайдеры заменяются через интерфейсы.

## Что уже есть

- FastAPI API с `projects`, `trends`, `jobs`
- PostgreSQL + Redis конфигурация
- SQLAlchemy async модели для `projects`, `trend_sources`, `jobs`, `job_shots`, `assets`, `logs`
- Job orchestrator со статусами:
  `queued`, `ingesting`, `analyzing`, `scripting`, `planning`, `generating_video`, `generating_voice`, `generating_music`, `composing`, `exporting`, `done`, `failed`
- RQ worker для фонового запуска job
- Локальное storage-дерево `storage/jobs/{job_id}/...`
- MVP pipeline, который реально проходит все стадии и отдает:
  `final.mp4`, `subtitles.srt`, `voiceover.wav`, `music.wav`, `thumb.jpg`, `meta.json`

## Важная оговорка

Сейчас провайдеры сделаны как заменяемые реализации, но для видео есть принципиальная разница:

- `VideoProvider=stub`: синтетический demo-режим, не production
- `VideoProvider=comfyui`: реальный video generation через ComfyUI API
- `TTSProvider`: делает silent voice track с корректной длительностью
- `MusicProvider`: берет первый трек из `storage/assets/music_library` или генерирует tone-bed
- `ScriptProvider`: шаблонный генератор сценария по template engine

Оркестратор теперь по умолчанию не даст молча использовать synthetic video в production job. Если выбран `stub`, без `allow_synthetic_video=true` job завершится ошибкой.

## Структура

```text
app/
├── api/
│   └── routes/
├── core/
├── db/
├── models/
├── providers/
│   ├── llm/
│   ├── music/
│   ├── tts/
│   └── video/
├── schemas/
├── services/
│   ├── analyze/
│   ├── compose/
│   ├── export/
│   ├── ingest/
│   ├── jobs/
│   ├── music/
│   ├── planning/
│   ├── projects/
│   ├── scripting/
│   ├── trends/
│   ├── video/
│   └── voice/
├── templates/
├── utils/
└── workers/
```

## Быстрый старт

### Docker

```bash
cp .env.example .env
docker-compose up --build
```

API будет на `http://localhost:8000`, Swagger на `http://localhost:8000/docs`, UI на `http://localhost:8000/ui/`.

Если хочешь, чтобы prompt parsing шел через ChatGPT API, задай:

```bash
export OPENAI_API_KEY=...
export OPENAI_PROMPT_MODEL=gpt-5.4-mini
```

Без `OPENAI_API_KEY` UI все равно работает, но prompt будет разбираться локальным fallback planner.

Текущий `docker-compose.yml` теперь ориентирован на production-like запуск:

- `api`, `worker`, `postgres`, `redis` живут в Docker
- код baked в image, без bind-mount всего репозитория
- `storage/` и `third_party/` пробрасываются как data volumes на хосте
- API стартует без `--reload`
- UI раздается тем же FastAPI контейнером

Если `8000` занят, подними стек на другом порту:

```bash
DOCKER_APP_PORT=8010 docker compose up --build
```

### Локально

Нужны:

- Python 3.11+
- `ffmpeg` и `ffprobe`
- PostgreSQL и Redis для API/worker режима
- для прямого локального HODOR-runner достаточно Python + `ffmpeg`

Запуск:

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
python -m app.workers.worker
```

## Быстрый локальный запуск HODOR

Если тебе нужно просто локально собрать первый ролик без API сервера и Redis, используй runner:

По умолчанию runner теперь ожидает `comfyui`-режим. Для synthetic demo надо явно указать `--provider stub`.

### 1. Установить зависимости

```bash
cp .env.example .env
pip install -r requirements.txt
```

### 2. Режим `stub` без ComfyUI

Это только demo/smoke режим. Он нужен для проверки orchestration, subtitles, voice/music sync и export, но не для настоящего продакшена.

Он соберет synthetic `final.mp4`, subtitles, preview и metadata:

```bash
python scripts/run_local_hodor.py --provider stub
```

Готовые файлы окажутся в:

- `exports/hodor_local_stub.mp4`
- `exports/hodor_local_stub.jpg`
- `exports/hodor_local_stub.srt`
- `exports/hodor_local_stub.json`

### 3. Режим `comfyui`

Это production-путь. Сначала подними ComfyUI локально.

`ComfyUIVideoProvider` теперь умеет работать в двух режимах:

- напрямую с `UI workflow JSON` из ComfyUI
- с экспортированным `API workflow JSON`

Для быстрого старта удобнее использовать уже готовые `UI workflows` из `workflows/comfyui_ui/`.

#### Быстрый локальный ComfyUI stack

Скрипт ниже поднимет локальный `ComfyUI`, `AnimateDiff Evolved`, `VideoHelperSuite`, manager и скачает минимальный набор весов для первого реального прогона:

```bash
./scripts/install_comfyui_stack.sh
./scripts/start_comfyui.sh
```

`start_comfyui.sh` сам включает `--cpu`, если `torch.cuda.is_available()` вернул `False`. Если хочешь явно зафиксировать режим:

```bash
COMFYUI_DEVICE_MODE=gpu ./scripts/start_comfyui.sh
COMFYUI_DEVICE_MODE=cpu ./scripts/start_comfyui.sh
```

В `WSL2` install script теперь сам смотрит версию CUDA driver через `libcuda.so` и подбирает совместимый wheel:

- `>= 13.0` → `cu130`
- `>= 12.8` → `cu128`
- `>= 12.6` → `cu126`
- иначе → `cpu`

Если хочешь зафиксировать flavor вручную:

```bash
COMFYUI_TORCH_FLAVOR=cu128 ./scripts/install_comfyui_stack.sh
COMFYUI_TORCH_FLAVOR=cu126 ./scripts/install_comfyui_stack.sh
COMFYUI_TORCH_FLAVOR=cpu ./scripts/install_comfyui_stack.sh
```

Что ставится по умолчанию:

- `ComfyUI v0.19.3`
- `Kosinkadink/ComfyUI-AnimateDiff-Evolved`
- `Kosinkadink/ComfyUI-VideoHelperSuite`
- `ComfyUI manager`
- `Comfy-Org/stable-diffusion-v1-5-archive / v1-5-pruned-emaonly-fp16.safetensors`
- `conrevo/AnimateDiff-A1111 / motion_module/mm_sd15_v2.safetensors`

Проверка health:

```bash
curl -sS http://127.0.0.1:8188/system_stats
```

Если хочешь только софт без скачивания базовых моделей:

```bash
INSTALL_BASE_MODELS=0 ./scripts/install_comfyui_stack.sh
```

## Helper Workflows

Папка `helpers/` теперь может быть быстро приведена к твоей локальной инсталляции:

```bash
python3 scripts/prepare_helper_workflows.py --sync-to-comfyui-user
```

Что делает скрипт:

- подставляет реальный local checkpoint в `CheckpointLoaderSimple`
- подставляет реальный local motion model в `ADE_AnimateDiffLoaderGen1`
- копирует `HODOR.jpg` в `third_party/ComfyUI/input/`
- пишет patched UI-workflows в `workflows/comfyui_ui/`
- опционально копирует их в `third_party/ComfyUI/user/default/workflows/hodor_helpers/`

Если хочешь сразу подготовить `video-to-video`:

```bash
python3 scripts/prepare_helper_workflows.py \
  --video-source /absolute/path/to/trend.mp4 \
  --sync-to-comfyui-user
```

Потом положи workflow, например, в:

- `workflows/hodor_animdiff_api.json`

Минимальный production entrypoint под WSL2 + RTX 4060 теперь такой:

```bash
bash scripts/use_local_factory.sh \
  --mode video_to_video \
  --quality high \
  --output-prefix hodor_product
```

Что делает wrapper:

- сам поднимает `ComfyUI` на GPU, если он еще не запущен
- ждет `system_stats`
- запускает factory runner без ручного `workflow-path`
- после завершения гасит временно поднятый `ComfyUI`

Если ноуту тяжело, используй щадящий режим:

```bash
bash scripts/use_local_factory.sh \
  --safe-thermal \
  --mode video_to_video \
  --output-prefix hodor_safe
```

Что включает `--safe-thermal`:

- добавляет `ComfyUI --lowvram`
- если `--quality` не задан, опускает рендер до `standard`
- пытается выставить `90%` power cap через Windows UAC

Если хочешь поставить power cap отдельно:

```bash
bash scripts/set_gpu_power_limit.sh 90
```

Если `ComfyUI` уже поднят вручную, можно запускать напрямую:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/run_local_hodor.py \
  --provider comfyui \
  --mode video_to_video \
  --quality high \
  --no-auto-start-comfyui
```

Доступные режимы:

- `text_to_video`
- `image_to_video`
- `video_to_video`

Доступные quality presets:

- `draft`
- `standard`
- `high`
- `ultra`

Под RTX 4060 8GB основной рабочий preset сейчас `high`:

- `576x1024`
- `16 frames`
- `24 steps`
- `8 fps`

Если у твоего workflow свои node ids, поправь mapping или передай свой:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/run_local_hodor.py \
  --provider comfyui \
  --workflow-path workflows/hodor_animdiff_api.json \
  --workflow-mapping-path workflows/hodor_animdiff_mapping.json
```

Если ComfyUI поднят не на `127.0.0.1:8188`:

```bash
bash scripts/use_local_factory.sh \
  --mode video_to_video \
  --quality high \
  --comfyui-base-url http://127.0.0.1:8189
```

У каждого job теперь также сохраняется stage manifest:

- `storage/jobs/{job_id}/data/pipeline_state.json`

Там видно, какой этап завершился, какой упал, и откуда можно делать `resume`.

### 4. Если хочешь свой trend video

```bash
python scripts/run_local_hodor.py \
  --provider stub \
  --trend-video /absolute/path/to/trend.mp4 \
  --skip-demo-trend
```

По умолчанию runner сам сгенерирует demo trend video, если файл не найден.

## UI

Теперь UI работает в prompt-first режиме:

- входные данные: `pictures`, `reference video`, `logo`, базовый `Generation Config`
- chat разбирает prompt на параметры и собирает `plan`
- если `reference video` не задан, UI автоматически переходит в:
  - `image_sequence`, если загружены картинки
  - `text_only`, если визуальных референсов нет
- `Shot Overrides` скрыты по умолчанию и появляются как упрощенный `Scene Tuning` только после первой генерации
- просмотр `jobs`, `final.mp4`, `thumb.jpg`, `meta.json`, `subtitles`, `voiceover`, `music`

URL:

- `http://localhost:8000/ui/`

## Основные API endpoints

- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `POST /api/v1/trends`
- `POST /api/v1/trends/upload`
- `GET /api/v1/trends`
- `POST /api/v1/jobs`
- `POST /api/v1/jobs/{job_id}/run`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/ui/assistant/plan`
- `POST /api/v1/ui/assistant/generate`
- `POST /api/v1/ui/assets/upload`
- `GET /api/v1/ui/assets`

## Пример потока

### 1. Создать проект

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "HODOR",
    "config": {
      "brand_colors": ["#0A1633", "#132A63"],
      "voice_style": "calm_dark_male",
      "music_style": "dark cyber tension",
      "default_aspect": "9:16"
    }
  }'
```

### 2. Зарегистрировать трендовый ролик

```bash
curl -X POST http://localhost:8000/api/v1/trends \
  -H "Content-Type: application/json" \
  -d '{
    "type": "video",
    "source_path": "storage/input/demo/door_cat.mp4",
    "hook_description": "person fails, cat succeeds"
  }'
```

Или загрузить файл:

```bash
curl -X POST http://localhost:8000/api/v1/trends/upload \
  -F "file=@/absolute/path/to/door_cat.mp4" \
  -F "hook_description=person fails, cat succeeds"
```

### 3. Создать и сразу прогнать job

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "project_xxx",
    "trend_source_id": "trend_xxx",
    "topic": "proxy for telegram",
    "language": "ru",
    "duration_sec": 8,
    "scene_count": 3,
    "run_now": true,
    "config_json": {
      "template": "dark_cinematic",
      "video_provider": "comfyui",
      "tts_provider": "stub",
      "music_provider": "library",
      "brand_overlay": true,
      "subtitles": true
    }
  }'
```

## ComfyUI вместо stub

Теперь `video_provider: "comfyui"` работает через:

- `COMFYUI_BASE_URL`
- `provider_settings.workflow_path`
- `provider_settings.workflow_mapping`
- `provider_settings.generation_mode`
- `provider_settings.quality_preset`

Провайдер умеет:

- работать напрямую с `UI workflow JSON` из ComfyUI
- работать с экспортированным `API workflow JSON`
- отправлять workflow в `/prompt`
- ждать completion по `/history/{prompt_id}`
- скачивать итоговый `mp4/webm/mov/gif/image` через `/view`
- конвертировать output в `clip_XX.mp4`
- загружать reference image в ComfyUI через `/upload/image`
- staging `reference_video` в `ComfyUI/input`
- подставлять `prompt`, `negative_prompt`, `width`, `height`, `frames`, `steps`, `cfg`, `seed`, `fps`, `filename_prefix`

Если `project.config.logo_path` задан, он автоматически передается в provider как `brand_image_path`.

### Пример `config_json` для твоего кейса

```json
{
  "video_provider": "comfyui",
  "template": "dark_cinematic",
  "brand_overlay": true,
  "subtitles": true,
  "voiceover_lines": [
    "Telegram снова не работает?",
    "Есть способ проще.",
    "HODOR."
  ],
  "overlay_lines": [
    "Когда Telegram не пускает",
    "А решение уже есть",
    "HODOR"
  ],
  "shot_overrides": [
    {
      "type": "hook",
      "prompt": "a frustrated man trying to open a locked door, dark room, cinematic lighting, neon blue tones, close-up, emotional tension, realistic, slight camera shake, dramatic atmosphere, ultra detailed, 9:16 vertical video",
      "overlay": "Когда Telegram не пускает",
      "camera": "close-up",
      "motion": "slight camera shake",
      "negative_prompt": "low quality, blurry, bad anatomy, distorted face, glitch, artifacts, watermark, text errors, deformed hands, extra limbs",
      "provider_settings": {
        "workflow_path": "workflows/hodor_animdiff_api.json",
        "workflow_mapping": {
          "prompt": ["6.inputs.text"],
          "negative_prompt": ["7.inputs.text"],
          "width": ["12.inputs.width"],
          "height": ["12.inputs.height"],
          "frames": ["12.inputs.batch_size"],
          "steps": ["3.inputs.steps"],
          "cfg": ["3.inputs.cfg"],
          "fps": ["30.inputs.frame_rate"],
          "filename_prefix": ["30.inputs.filename_prefix"],
          "brand_image": ["50.inputs.image"]
        },
        "resolution": "512x768",
        "frames": 24,
        "steps": 24,
        "cfg": 7,
        "fps": 8
      }
    }
  ]
}
```

Шаблоны лежат тут:

- [workflow_api.example.json](/home/thunder/work/tikitoki_conveyor/app/templates/comfyui/workflow_api.example.json)
- [workflow_mapping.example.json](/home/thunder/work/tikitoki_conveyor/app/templates/comfyui/workflow_mapping.example.json)

Подставь туда реальные node ids из своего ComfyUI workflow в API format.

### 4. Забрать артефакты

Финальные файлы будут в `storage/jobs/{job_id}/output/`.

## Реализованный pipeline

1. `IngestService` копирует source, делает metadata JSON, пытается извлечь keyframes
2. `TrendAnalyzerService` строит структуру ролика и темп
3. `ScriptGeneratorService` генерирует короткий сценарий по template engine
4. `ShotPlannerService` превращает сценарий в `shots`
5. `VideoGenerationService` рендерит клипы по shot-by-shot схеме
6. `VoiceGenerationService` собирает scene-based voice assets
7. `MusicGenerationService` подбирает или генерирует bed
8. `ComposerService` склеивает клипы, subtitles, voice, music, logo
9. `ExporterService` делает `final.mp4`, `thumb.jpg`, `meta.json`

## Что подменять дальше

- `app/providers/video/comfyui.py` → живой ComfyUI API
- `app/providers/video/stub.py` → explicit synthetic smoke only
- `app/providers/tts/stub.py` → ElevenLabs / XTTS
- `app/providers/music/stub.py` → MusicGen / library ranker
- `app/providers/llm/template.py` → OpenAI / Anthropic / локальная LLM

## Текущее ограничение MVP

- Trend analysis пока heuristic/template-based, не full CV
- TTS сейчас без реальной речи
- Настоящий video generation требует поднятого ComfyUI, но уже поддерживает и `UI workflow`, и `API workflow`
- Нет Alembic миграций и auth/admin UI
