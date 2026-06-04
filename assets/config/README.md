# Official Config

Source of truth for official Harzoo configuration files shipped with the repository.

Structure mirrors runtime config (`~/.harzoo/config/`):

- `config.json`
- `profiles/*.md`
- `skills/*.md` (optional)
- `tools/*.py`

Notes:

- Runtime still defaults to `~/.harzoo/config`.
- MkDocs copies `profiles/` and `tools/` to `site/downloads/` on build.
