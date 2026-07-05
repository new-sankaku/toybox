from pathlib import Path

# Anchor for all project-root-relative paths (db, .env, static, assets, recordings,
# logs). Independent of how deeply a module is nested inside the package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
