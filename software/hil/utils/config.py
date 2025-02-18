import itertools
import json
import logging
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConfigDict(defaultdict):
    def __init__(self, *args, **kwargs):
        super().__init__(ConfigDict, *args, **kwargs)


def load_config(configs_dir: Path, pet_name: str | None = None) -> ConfigDict:
    config = ConfigDict()

    for candidate_path in itertools.chain(
        [configs_dir / f"{pet_name}.json"],
        configs_dir.glob("*.json"),
    ):
        if candidate_path.is_file():
            with open(candidate_path, "r") as f:
                config.update(json.load(f))
            break

    return config


def save_config(config: ConfigDict, configs_dir: Path, pet_name: str | None = None):
    config_path = configs_dir / f"{pet_name}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f)
