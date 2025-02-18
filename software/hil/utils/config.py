import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import Self
import uuid

logger = logging.getLogger(__name__)


class ConfigDict(defaultdict):
    DEFAULTS = {"machine-metadata": {"mac": uuid.getnode()}}

    def __init__(self, *args, **kwargs):
        super().__init__(ConfigDict, *args, **kwargs)
        self._touched = set()

    @classmethod
    def from_dict(cls, data: dict):
        self = cls(
            {
                str(k): ConfigDict.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.items()
            }
        )
        return self

    def nested_update(self, other: dict, touch=False) -> Self:
        for k, v in other.items():
            k = str(k)
            if isinstance(v, dict):
                self_v = self[k]
                if isinstance(self_v, ConfigDict):
                    self_v.nested_update(v)
                else:
                    logger.warning(f"Overriding non-ConfigDict value for key {k}")
                    # Use super to avoid marking these items as touched
                    if touch:
                        self[k] = ConfigDict.from_dict(v)
                    else:
                        super().__setitem__(k, ConfigDict.from_dict(v))
            else:
                # Use super to avoid marking these items as touched
                if touch:
                    self[k] = v
                else:
                    super().__setitem__(k, v)
        return self

    def __getitem__(self, key):
        # The JSON module will stringify keys regardless
        key = str(key)
        self._touch(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        key = str(key)
        self._touch(key)
        super().__setitem__(key, value)

    def _touch(self, key):
        self._touched.add(key)

    def clean(self):
        """Recursively clean the dict and any sub-dicts of un-read items"""
        for key in list(self.keys()):
            if key in self._touched:
                value = self[key]
                if isinstance(value, ConfigDict):
                    value.clean()
            else:
                del self[key]


def load_config(configs_dir: Path, pet_name: str) -> ConfigDict:
    path = configs_dir / f"{pet_name}.json"
    if path.is_file():
        with open(path, "r") as f:
            try:
                return (
                    ConfigDict()
                    .nested_update(ConfigDict.DEFAULTS, touch=True)
                    .nested_update(json.load(f), touch=False)
                )
            except Exception as e:
                logger.exception(f"Error loading config from {path}: {e}")

    return ConfigDict().nested_update(ConfigDict.DEFAULTS, touch=True)


def save_config(config: ConfigDict, configs_dir: Path, pet_name: str):
    config_path = configs_dir / f"{pet_name}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f)
