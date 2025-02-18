import uuid
import hashlib


ADJECTIVES = [
    "happy",
    "sleepy",
    "grumpy",
    "bouncy",
    "fluffy",
    "clever",
    "silly",
    "mighty",
    "gentle",
    "brave",
    "peaceful",
    "witty",
    "jolly",
    "friendly",
    "lively",
    "perky",
    "cute",
    "funny",
    "quirky",
    "sassy",
    "snug",
    "snarky",
    "snazzy",
    "snooty",
    "wobbly",
    "zippy",
    "pudgy",
    "clumsy",
    "dizzy",
    "goofy",
    "plucky",
    "wiggly",
    "bumbling",
    "derpy",
    "peppy",
    "squiggly",
    "wacky",
    "zesty",
    "loopy",
    "fuzzy",
]

ANIMALS = [
    "panda",
    "otter",
    "penguin",
    "koala",
    "dolphin",
    "rabbit",
    "raccoon",
    "fox",
    "hedgehog",
    "squirrel",
    "beaver",
    "badger",
    "wombat",
    "lemur",
    "lynx",
    "seal",
    "sloth",
    "tiger",
    "zebra",
    "giraffe",
    "monkey",
    "llama",
    "walrus",
    "hippo",
    "meerkat",
    "platypus",
    "quokka",
    "narwhal",
    "capybara",
    "pangolin",
    "axolotl",
    "ferret",
]


def looks_like_a_pet_name(name: str) -> bool:
    try:
        adjective, animal = name.split("-")
    except ValueError:
        return False

    return adjective in ADJECTIVES and animal in ANIMALS


def get_pet_name(identifier: int | None = None) -> str:
    """
    Generate a deterministic pet name, typically from a MAC address.
    Returns a combination of an adjective and an animal name.

    Example:
        >>> get_pet_name(0x001A2B3C4D5E)
        'chunky-otter'
    """
    if identifier is None:
        identifier = uuid.getnode()

    # MACs aren't evenly distributed, so we hash them to get a more even distribution
    hashed = hashlib.sha256(identifier.to_bytes(6)).digest()

    # Extract first 3 bytes for adjective (24 bits)
    adj_hash = int.from_bytes(hashed[:3])
    # Extract last 3 bytes for animal (24 bits)
    animal_hash = int.from_bytes(hashed[-3:])

    # Select deterministic names using modulo
    adjective = ADJECTIVES[adj_hash % len(ADJECTIVES)]
    animal = ANIMALS[animal_hash % len(ANIMALS)]

    return f"{adjective}-{animal}"
