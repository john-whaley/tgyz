import logging
import random
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LOGGER = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4"}
ALPHABET = string.ascii_letters + string.digits

IMAGE_OPTION_SETS = [
    [113, 54, 0, 47, 88, 150, 46, 38, 34, 120],
    [3, 166, 73, 56, 163, 61, 146, 93, 123, 190],
    [150, 85, 95, 72, 148, 7, 9, 34, 81, 163],
    [23, 156, 167, 25, 125, 53, 183, 144, 2, 91],
    [99, 18, 121, 115, 17, 19, 147, 165, 151, 118],
    [48, 1, 115, 199, 125, 82, 191, 193, 3, 64],
    [198, 136, 72, 177, 76, 40, 94, 125, 2, 111],
    [96, 150, 73, 48, 61, 80, 68, 4, 27, 113],
    [184, 62, 161, 169, 98, 69, 24, 8, 3, 66],
    [142, 126, 36, 195, 123, 58, 31, 84, 82, 166],
    [8, 116, 164, 94, 16, 35, 184, 117, 71, 6],
    [2, 154, 128, 108, 179, 1, 160, 53, 32, 11],
    [7, 105, 10, 22, 157, 45, 31, 113, 177, 134],
    [79, 72, 48, 107, 102, 15, 134, 122, 178, 130],
    [5, 138, 144, 161, 59, 143, 38, 158, 92, 125],
    [18, 186, 65, 57, 31, 179, 1, 99, 74, 23],
    [122, 5, 103, 198, 24, 114, 191, 105, 120, 160]
]


@dataclass(frozen=True)
class ChallengeAsset:
    path: Path
    kind: Literal["image", "video"]
    answer: str
    image_index: int | None = None
    option_set: tuple[str, ...] | None = None


def image_details(path: Path) -> tuple[int, str, tuple[str, ...]] | None:
    # Accept the real Chinese enumeration comma and its mojibake form seen in
    # older local filenames/source output.
    match = re.match(r"^(\d+)(?:\u3001|\u040e\u045e)(.+)$", path.stem)
    if not match:
        return None

    index = int(match.group(1))
    answer = match.group(2)
    if index < 1 or index > len(IMAGE_OPTION_SETS):
        LOGGER.warning("Skipping image with option index out of range: %s", path)
        return None

    options = tuple(str(option) for option in IMAGE_OPTION_SETS[index - 1])
    if answer not in options:
        LOGGER.warning("Image answer %s is not in option set %d: %s", answer, index, path)
        options = options[:9] + (answer,)
    return index, answer, options


def load_assets(viewers_dir: Path, media_mode: str = "mixed") -> list[ChallengeAsset]:
    img_dir = viewers_dir / "img"
    videos_dir = viewers_dir / "videos"
    assets: list[ChallengeAsset] = []

    if img_dir.exists():
        for path in sorted(img_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                details = image_details(path)
                if details is not None:
                    image_index, answer, option_set = details
                    assets.append(
                        ChallengeAsset(
                            path=path,
                            kind="image",
                            answer=answer,
                            image_index=image_index,
                            option_set=option_set,
                        )
                    )
                else:
                    LOGGER.warning("Skipping image with invalid name format: %s", path)

    if videos_dir.exists():
        for path in sorted(videos_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                assets.append(ChallengeAsset(path=path, kind="video", answer=path.stem))

    if media_mode == "image":
        assets = [asset for asset in assets if asset.kind == "image"]
    elif media_mode == "video":
        assets = [asset for asset in assets if asset.kind == "video"]
    elif media_mode != "mixed":
        raise ValueError("MEDIA_MODE must be one of: mixed, image, video")

    if not assets:
        raise RuntimeError(f"No challenge assets found under {viewers_dir!s}")

    LOGGER.info("Loaded %d challenge assets from %s", len(assets), viewers_dir)
    return assets


def build_options(asset: ChallengeAsset, assets: list[ChallengeAsset]) -> list[str]:
    correct = asset.answer
    if asset.kind == "image":
        if asset.option_set is None:
            raise ValueError(f"Image asset has no option set: {asset.path}")
        options = list(asset.option_set)
        random.shuffle(options)
        return options

    wrongs = {item.answer for item in assets if item.kind == "video" and item.answer != correct}
    while len(wrongs) < 9:
        wrongs.add("".join(random.choice(ALPHABET) for _ in range(4)))
    wrongs.discard(correct)

    selected = random.sample(sorted(wrongs), 9)
    options = selected + [correct]
    random.shuffle(options)
    return options
