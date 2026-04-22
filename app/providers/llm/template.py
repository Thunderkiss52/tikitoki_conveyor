from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.pipeline import ContentTemplate, ScriptPackage
from app.utils.storage import safe_slug


class TemplateScriptProvider:
    def __init__(self, template_path: Path | None = None) -> None:
        template_file = template_path or Path(__file__).resolve().parents[2] / "templates" / "content_templates.json"
        raw_templates = json.loads(template_file.read_text(encoding="utf-8"))
        self.templates = {
            name: ContentTemplate(name=name, **payload)
            for name, payload in raw_templates.items()
        }

    def generate_script(self, context: dict[str, Any]) -> ScriptPackage:
        topic = context["topic"]
        project_name = context["project_name"]
        language = context.get("language", "ru")
        analysis = context.get("analysis", {})
        cta = context.get("cta") or ("Ссылка в профиле" if language == "ru" else "Link in bio")
        template_name = context.get("template") or self._select_template(topic, analysis)
        template = self.templates[template_name]

        scene_count = int(context.get("scene_count", len(template.scene_roles)))
        roles = list(template.scene_roles[:scene_count])
        if len(roles) < scene_count:
            roles.extend(["cta"] * (scene_count - len(roles)))

        voiceover = [self._voice_line(role, topic, project_name, cta, language) for role in roles]
        overlays = [self._overlay_line(role, topic, project_name, cta, language) for role in roles]
        title = f"{project_name} {safe_slug(topic)}"

        return ScriptPackage(
            title=title,
            template=template_name,
            voiceover=voiceover,
            overlays=overlays,
            cta=cta,
        )

    def _select_template(self, topic: str, analysis: dict[str, Any]) -> str:
        combined_text = f"{topic} {analysis.get('mood', '')} {analysis.get('hook', '')}".lower()
        if any(keyword in combined_text for keyword in ("cat", "кот", "pet", "animal")):
            return "funny_pet_contrast"
        if any(keyword in combined_text for keyword in ("dark", "proxy", "cyber", "cinematic")):
            return "dark_cinematic"
        return "meme_problem_solution"

    def _voice_line(self, role: str, topic: str, project_name: str, cta: str, language: str) -> str:
        if language != "ru":
            return self._voice_line_en(role, topic, project_name, cta)

        mapping = {
            "problem": f"{topic} снова упирается в стену?",
            "human_fails": f"{topic} снова упирается в стену?",
            "hook_closeup": f"{topic} опять завис в самый неудобный момент?",
            "contrast": f"{project_name} проходит там, где другие застревают.",
            "pet_succeeds": f"{project_name} проходит там, где другие застревают.",
            "reveal": f"{project_name} открывает доступ без лишнего шума.",
            "solution": "Запустил, подключился и продолжаешь работать.",
            "brand_line": f"{project_name}. Быстро. Чисто. По делу.",
            "brand_punchline": f"{project_name}. Контраст, который сразу считывается.",
            "cta": cta,
        }
        return mapping.get(role, f"{project_name} держит тему под контролем.")

    def _voice_line_en(self, role: str, topic: str, project_name: str, cta: str) -> str:
        mapping = {
            "problem": f"{topic} stalls at the worst moment?",
            "contrast": f"{project_name} gets through where others fail.",
            "solution": "Launch it and keep moving.",
            "cta": cta,
        }
        return mapping.get(role, f"{project_name} keeps the flow moving.")

    def _overlay_line(self, role: str, topic: str, project_name: str, cta: str, language: str) -> str:
        if language != "ru":
            mapping = {
                "problem": "When the app locks up",
                "contrast": "The workaround is ready",
                "solution": project_name,
                "cta": cta,
            }
            return mapping.get(role, project_name)

        mapping = {
            "problem": "Когда всё снова тупит",
            "human_fails": "Когда вход не пускает",
            "hook_closeup": "Хук в первые секунды",
            "contrast": "Решение уже рядом",
            "pet_succeeds": "А кто-то уже внутри",
            "reveal": project_name,
            "solution": "Запустил и пользуешься",
            "brand_line": project_name,
            "brand_punchline": project_name,
            "cta": cta,
        }
        return mapping.get(role, project_name)
