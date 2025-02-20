import pytest
from hil.framework import Calibration, ConfigDict


def test_calibration_class():
    """Test the Calibration class functionality"""
    # Test initialization and basic mapping
    x = [1.0, 2.0, 3.0]
    y = [100.0, 200.0, 300.0]
    cal = Calibration(x, y)

    # Test map_xy with values within range
    assert cal.map_xy(1.5) == 150  # Should linearly interpolate
    assert cal.map_xy(1.0) == 100  # Exact match
    assert cal.map_xy(2.5) == 250  # Another interpolation

    # Test map_xy with values at boundaries
    assert cal.map_xy(1.0) == 100  # Lower bound
    assert cal.map_xy(3.0) == 300  # Upper bound

    # Test map_xy with values outside range
    with pytest.raises(ValueError):
        cal.map_xy(0.5)  # Below lower bound
    with pytest.raises(ValueError):
        cal.map_xy(3.5)  # Above upper bound

    # Test update method
    new_x = [1.0, 2.0, 3.0, 4.0]
    new_y = [10.0, 20.0, 30.0, 40.0]
    cal.update(new_x, new_y)

    # Verify the update worked
    assert cal.x == new_x
    assert cal.y == new_y
    assert cal.map_xy(2.5) == 25  # New interpolation with updated values


def test_calibration_class_with_bounds():
    x = [1.0, 2.0, 3.0]
    y = [100.0, 200.0, 300.0]
    cal = Calibration(x, y, lower_bound=0.5, upper_bound=3.5)

    assert cal.map_xy(0.5) == 100  # Below lower bound
    assert cal.map_xy(3.5) == 300  # Above upper bound


def test_from_config():
    config = ConfigDict()
    default_x = [1.0, 2.0]
    default_y = [100.0, 200.0]

    cal2 = Calibration.from_config(config, default_x, default_y)

    # Verify the config was populated with defaults
    assert cal2.x == default_x
    assert cal2.y == default_y

    # Test that the calibration works with the config values
    assert cal2.map_xy(1.5) == 150


def test_non_increasing_x_values():
    bad_x = [3.0, 2.0, 1.0]  # Decreasing values
    bad_y = [300.0, 200.0, 100.0]

    with pytest.raises(ValueError):
        Calibration(bad_x, bad_y)
