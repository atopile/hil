from hil.utils.config import ConfigDict


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
