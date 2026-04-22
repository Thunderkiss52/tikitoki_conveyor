from app.providers.llm.template import TemplateScriptProvider


def get_script_provider(name: str):
    providers = {
        "template": TemplateScriptProvider,
        "openai": TemplateScriptProvider,
        "anthropic": TemplateScriptProvider,
    }
    provider_cls = providers.get(name.lower())
    if provider_cls is None:
        raise ValueError(f"Unsupported script provider: {name}")
    return provider_cls()
