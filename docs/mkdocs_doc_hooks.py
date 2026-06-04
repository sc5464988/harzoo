"""MkDocs hooks: copy manual download assets to site and hide nav/TOC/footer on pages."""

from __future__ import annotations

import shutil
from pathlib import Path

_NAV_AND_TOC_FRONT_MATTER = """---
hide:
  - navigation
  - toc
  - footer
---

"""


def _already_hides_nav_and_toc(content: str) -> bool:
    return "hide:" in content and "- navigation" in content and "- toc" in content and "- footer" in content


def _copy_download_assets_to_site(*, config) -> None:
    """Copy official config assets into ``site/downloads`` (not MkDocs pages)."""
    site_root = Path(config.site_dir) / "downloads"
    official_root = Path(config.docs_dir) / "official-config"
    for subdir in ("profiles", "tools"):
        src_dir = official_root / subdir
        if not src_dir.is_dir():
            continue
        dst_dir = site_root / subdir
        dst_dir.mkdir(parents=True, exist_ok=True)
        for asset in src_dir.iterdir():
            if asset.is_file() and asset.suffix in {".md", ".py"}:
                shutil.copy2(asset, dst_dir / asset.name)

    subprofiles_src = official_root / "profiles" / "subprofiles"
    if subprofiles_src.is_dir():
        subprofiles_dst = site_root / "profiles" / "subprofiles"
        subprofiles_dst.mkdir(parents=True, exist_ok=True)
        for asset in subprofiles_src.iterdir():
            if asset.is_file() and asset.suffix == ".md":
                shutil.copy2(asset, subprofiles_dst / asset.name)

    skills_src = official_root / "skills"
    if skills_src.is_dir():
        skills_dst = site_root / "skills"
        for skill_dir in sorted(p for p in skills_src.iterdir() if p.is_dir()):
            out_dir = skills_dst / skill_dir.name
            out_dir.mkdir(parents=True, exist_ok=True)
            for asset in skill_dir.iterdir():
                if asset.is_file() and asset.suffix == ".md":
                    shutil.copy2(asset, out_dir / asset.name)


def on_post_build(*, config, **kwargs):
    _copy_download_assets_to_site(config=config)


def on_page_read_source(*, page, config):
    content = page.file.content_string
    if _already_hides_nav_and_toc(content):
        return None
    return _NAV_AND_TOC_FRONT_MATTER + content
