from pathlib import Path

from hil.utils.config import ConfigDict, load_config, save_config


def test_configdict():
    # Create a nested defaultdict
    d = ConfigDict()

    # Test that we can access arbitrary nested levels without KeyError
    d["a"]["b"]["c"] = 1
    assert d["a"]["b"]["c"] == 1

    # Test that accessing undefined paths returns a new defaultdict
    assert isinstance(d["x"]["y"], ConfigDict)

    # Test that we can still set values at any level
    d["p"]["q"] = 2
    assert d["p"]["q"] == 2

    # Test that nested levels maintain defaultdict behavior
    d["m"]["n"]["o"]["p"] = 3
    assert d["m"]["n"]["o"]["p"] == 3


def test_configdict_from_dict():
    # Test creating from a flat dictionary
    flat_dict = {"a": 1, "b": 2}
    config = ConfigDict.from_dict(flat_dict)
    assert config["a"] == 1
    assert config["b"] == 2
    assert isinstance(config, ConfigDict)

    # Test creating from a nested dictionary
    nested_dict = {"a": {"b": {"c": 1}}, "x": 2}
    config = ConfigDict.from_dict(nested_dict)
    assert config["a"]["b"]["c"] == 1
    assert config["x"] == 2
    assert isinstance(config["a"], ConfigDict)
    assert isinstance(config["a"]["b"], ConfigDict)

    # Test that undefined paths still return ConfigDict
    assert isinstance(config["undefined"]["path"], ConfigDict)

    # Test mixed nested and flat values
    mixed_dict = {
        "flat": 1,
        "nested": {"value": 2},
        "list": [1, 2, 3],  # Non-dict values should be preserved as-is
    }
    config = ConfigDict.from_dict(mixed_dict)
    assert config["flat"] == 1
    assert config["nested"]["value"] == 2
    assert config["list"] == [1, 2, 3]
    assert isinstance(config["nested"], ConfigDict)


def test_configdict_clean():
    # Test cleaning of unused paths
    config = ConfigDict.from_dict(
        {
            "used": 1,
            "unused": 2,
            "nested": {"used": 3, "unused": 4},
            "deep": {"nested": {"used": 5, "unused": 6}},
            1: "integer key",  # Test integer key
        }
    )

    # Access some paths to mark them as used
    assert config["used"] == 1
    assert config["nested"]["used"] == 3
    assert config["deep"]["nested"]["used"] == 5
    assert config[1] == "integer key"  # Access integer key

    # Clean the config
    config.clean()

    # Check that used paths are retained
    assert config["used"] == 1
    assert config["nested"]["used"] == 3
    assert config["deep"]["nested"]["used"] == 5
    assert config[1] == "integer key"

    # Check that unused paths are removed
    assert "unused" not in config
    assert "unused" not in config["nested"]
    assert "unused" not in config["deep"]["nested"]


def test_load_save_config(tmp_path: Path):
    # Create a test config
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    original_config = {
        "string_key": "value",
        1: "integer key",
        "nested": {"key": "value"},
        "list": [1, 2, 3],
    }

    # Test saving
    config = ConfigDict.from_dict(original_config)
    save_config(config, config_dir, "test_pet")

    # Verify the file exists
    config_path = config_dir / "test_pet.json"
    assert config_path.exists()

    # Test loading
    loaded_config = load_config(config_dir, "test_pet")
    assert loaded_config["string_key"] == "value"
    assert loaded_config["1"] == "integer key"  # Integer keys are converted to strings
    assert loaded_config["nested"]["key"] == "value"
    assert loaded_config["list"] == [1, 2, 3]

    # Test loading with non-existent pet name
    empty_config = load_config(config_dir, "non_existent_pet")
    assert isinstance(empty_config, ConfigDict)
    assert empty_config == ConfigDict.DEFAULTS

    # Test loading from empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    empty_config = load_config(empty_dir, "test_pet")
    assert isinstance(empty_config, ConfigDict)
    assert empty_config == ConfigDict.DEFAULTS


def test_load_config_invalid_json(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    # Create an invalid JSON file
    invalid_config_path = config_dir / "invalid.json"
    invalid_config_path.write_text("{invalid json")

    # Should return default ConfigDict for invalid JSON
    config = load_config(config_dir, "test_pet")
    assert isinstance(config, ConfigDict)
    assert config == ConfigDict.DEFAULTS
