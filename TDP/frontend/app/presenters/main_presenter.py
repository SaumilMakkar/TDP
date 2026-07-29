from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class HomePageContext:
    page_title: str
    css_version: str
    script_version: str


def build_home_page_context() -> dict:
    context = HomePageContext(
        page_title='Next-Gen PBM Automation',
        css_version='20260722-app-shell-brand-bigger-5',
        script_version='20260717-escalation-threshold-and-daw-list-fix',
    )
    return asdict(context)
