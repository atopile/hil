import itertools
import json
import logging
from pathlib import Path
from hil.utils.pet_name import get_pet_name
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConfigDict(defaultdict):
    def __init__(self, *args, **kwargs):
        super().__init__(ConfigDict, *args, **kwargs)


def load_config(configs_dir: Path, identifier: str | int | None = None) -> ConfigDict:
    config = ConfigDict()

    if not isinstance(identifier, str):
        identifier = get_pet_name(identifier)

    for candidate_path in itertools.chain(
        [configs_dir / f"{identifier}.json"],
        configs_dir.glob("*.json"),
    ):
        if candidate_path.is_file():
            with open(candidate_path, "r") as f:
                config.update(json.load(f))
            break

    return config


def save_config(config: ConfigDict, configs_dir: Path, pet_name: str | None = None):
    if pet_name is None:
        pet_name = get_pet_name()

    config_path = configs_dir / f"{pet_name}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f)
