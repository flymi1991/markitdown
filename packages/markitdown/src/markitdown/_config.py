import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_FILENAME = "markitdown_config.json"


def _find_config() -> Optional[str]:
    candidates = []
    candidates.append(Path(sys.argv[0]).resolve().parent / CONFIG_FILENAME)
    candidates.append(Path(sys.prefix) / "Scripts" / CONFIG_FILENAME)
    cwd = Path.cwd()
    candidates.append(cwd / CONFIG_FILENAME)
    pkg_dir = Path(__file__).resolve().parent
    candidates.append(pkg_dir / CONFIG_FILENAME)
    package_root = pkg_dir.parents[1]
    candidates.append(package_root / CONFIG_FILENAME)
    for parent in [cwd] + list(cwd.parents):
        candidates.append(parent / CONFIG_FILENAME)
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def load_config() -> Dict[str, Any]:
    path = _find_config()
    if path is None:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_llm_config() -> Dict[str, Any]:
    cfg = load_config()
    return cfg.get("llm", {})


def get_ocr_llm_config() -> Dict[str, Any]:
    cfg = load_config()
    return cfg.get("ocr_llm", {})


def create_llm_client() -> Optional[Any]:
    llm_cfg = get_llm_config()
    api_key = llm_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
    base_url = llm_cfg.get("base_url") or os.environ.get("OpenAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=base_url)
    except ImportError:
        return None


def create_ocr_llm_client() -> Optional[Any]:
    llm_cfg = get_ocr_llm_config()
    api_key = llm_cfg.get("api_key")
    base_url = llm_cfg.get("base_url")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=base_url)
    except ImportError:
        return None


def get_llm_model() -> Optional[str]:
    llm_cfg = get_llm_config()
    return llm_cfg.get("model") or os.environ.get("OPENAI_MODEL") or "deepseek-chat"


def get_ocr_llm_model() -> Optional[str]:
    llm_cfg = get_ocr_llm_config()
    return llm_cfg.get("model")
