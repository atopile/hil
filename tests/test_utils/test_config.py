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
