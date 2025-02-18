from hil.utils.pet_name import get_pet_name


def test_get_pet_name_deterministic():
    # Test that same input produces same output
    identifier = 0x123456789ABC
    name1 = get_pet_name(identifier)
    name2 = get_pet_name(identifier)
    assert name1 == name2

    # Test format is correct (adjective-animal)
    assert "-" in name1
    adjective, animal = name1.split("-")
    assert len(adjective) > 0
    assert len(animal) > 0


def test_get_pet_name_different_inputs():
    # Test that different inputs produce different outputs
    name1 = get_pet_name(0x111111111111)
    name2 = get_pet_name(0x222222222222)
    assert name1 != name2


def test_get_pet_name_no_input():
    # Test that calling without identifier works
    name = get_pet_name()
    assert isinstance(name, str)
    assert "-" in name
