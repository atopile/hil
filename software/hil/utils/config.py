import itertools
import json
import logging
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConfigDict(defaultdict):
    def __init__(self, *args, **kwargs):
        super().__init__(ConfigDict, *args, **kwargs)

    @classmethod
    def from_dict(cls, d: dict):
        self = cls(d)
        for k, v in d.items():
            if isinstance(v, dict):
                self[k] = cls.from_dict(v)
        return self


def load_config(configs_dir: Path, pet_name: str | None = None) -> ConfigDict:
    for candidate_path in itertools.chain(
        [configs_dir / f"{pet_name}.json"],
        configs_dir.glob("*.json"),
    ):
        if candidate_path.is_file():
            with open(candidate_path, "r") as f:
                try:
                    return ConfigDict.from_dict(json.load(f))
                except Exception as e:
                    logger.exception(f"Error loading config from {candidate_path}: {e}")

    return ConfigDict()


def save_config(config: ConfigDict, configs_dir: Path, pet_name: str | None = None):
    config_path = configs_dir / f"{pet_name}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f)
