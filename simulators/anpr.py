import re

PLATE_PATTERN = re.compile(r"[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}")
LOW_CONFIDENCE = 0.6
HIGH_CONFIDENCE = 0.97


class UnreadableImage(Exception):
    pass


def recognise(image_ref: str):
    name = image_ref.upper()
    if "UNREADABLE" in name:
        raise UnreadableImage(image_ref)
    match = PLATE_PATTERN.search(name)
    if match is None:
        raise UnreadableImage(image_ref)
    confidence = LOW_CONFIDENCE if "LOWCONF" in name else HIGH_CONFIDENCE
    return match.group(), confidence
