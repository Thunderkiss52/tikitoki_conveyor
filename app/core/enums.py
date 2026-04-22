from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    SCRIPTING = "scripting"
    PLANNING = "planning"
    GENERATING_VIDEO = "generating_video"
    GENERATING_VOICE = "generating_voice"
    GENERATING_MUSIC = "generating_music"
    COMPOSING = "composing"
    EXPORTING = "exporting"
    DONE = "done"
    FAILED = "failed"


class TrendSourceType(str, Enum):
    VIDEO = "video"
    URL = "url"
    TEXT = "text"


class GenerationMode(str, Enum):
    REFERENCE_BASED = "reference_based"
    TEMPLATE_ONLY = "template_only"


class AssetType(str, Enum):
    SOURCE_VIDEO = "source_video"
    SOURCE_META = "source_meta"
    KEYFRAME = "keyframe"
    TREND_ANALYSIS = "trend_analysis"
    SCRIPT = "script"
    SHOT_PLAN = "shot_plan"
    VIDEO_CLIP = "video_clip"
    VOICE_TRACK = "voice_track"
    MUSIC_TRACK = "music_track"
    SUBTITLE = "subtitle"
    COMPOSED_VIDEO = "composed_video"
    FINAL_VIDEO = "final_video"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"
