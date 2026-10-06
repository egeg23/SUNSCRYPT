"""Filesystem locations, overridable via env (SUNS_ENGINE_DATA, SUNS_ENGINE_RESULTS, SUNS_MODEL_DIR)."""
import os

ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.environ.get("SUNS_ENGINE_DATA", os.path.join(ENGINE_ROOT, "var", "data"))
RESULTS_DIR = os.environ.get("SUNS_ENGINE_RESULTS", os.path.join(ENGINE_ROOT, "var", "results"))
MODEL_DIR = os.environ.get("SUNS_MODEL_DIR", os.path.join(ENGINE_ROOT, "var", "models", "ft_small_s300"))
