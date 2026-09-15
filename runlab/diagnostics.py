from __future__ import annotations

from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os
import platform


def app_data_root() -> Path:
    override=os.environ.get('NHRA_TECH_DATA_HOME')
    if override:
        return Path(override).expanduser().resolve()
    system=platform.system().lower()
    if system=='windows':
        base=os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        return (Path(base) if base else Path.home()/'AppData'/'Local')/'NHRA'/'TechData'
    if system=='darwin':
        return Path.home()/'Library'/'Application Support'/'NHRA Tech Data'
    return Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local'/'state'))/'nhra-tech-data'


def log_dir() -> Path:
    path=app_data_root()/'logs'; path.mkdir(parents=True,exist_ok=True); return path


def configure_logging() -> Path:
    path=log_dir()/'nhra-tech-data.log'
    logger=logging.getLogger()
    # Avoid duplicate handlers when main() is re-entered in development.
    if not any(isinstance(h,RotatingFileHandler) and Path(getattr(h,'baseFilename',''))==path for h in logger.handlers):
        handler=RotatingFileHandler(path,maxBytes=2_000_000,backupCount=5,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s — %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path
