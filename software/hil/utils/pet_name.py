#! python3

from typing import Annotated
import uuid
import hashlib
import typer
import random

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
    "axolotl",
    "badger",
    "beaver",
    "capybara",
    "dolphin",
    "ferret",
    "fox",
    "giraffe",
    "hedgehog",
    "hippo",
    "koala",
    "lemur",
    "llama",
    "lynx",
    "meerkat",
    "monkey",
    "narwhal",
    "otter",
    "panda",
    "pangolin",
    "penguin",
    "platypus",
    "quokka",
    "rabbit",
    "raccoon",
    "seal",
    "sloth",
    "squirrel",
    "tiger",
    "walrus",
    "wombat",
    "zebra",
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
    hashed = hashlib.md5(identifier.to_bytes(6)).digest()

    # Extract first 3 bytes for adjective (24 bits)
    adj_hash = int.from_bytes(hashed[:3])
    # Extract last 3 bytes for animal (24 bits)
    animal_hash = int.from_bytes(hashed[-3:])

    # Select deterministic names using modulo
    adjective = ADJECTIVES[adj_hash % len(ADJECTIVES)]
    animal = ANIMALS[animal_hash % len(ANIMALS)]

    return f"{adjective}-{animal}"


def main(
    identifier: int | None = None,
    im_feeling_lucky: Annotated[bool, typer.Option("--im-feeling-lucky", "-r")] = False,
):
    if im_feeling_lucky:
        identifier = random.randint(0, 2**48 - 1)

    name = get_pet_name(identifier)
    print(name)


if __name__ == "__main__":
    typer.run(main)
