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


@dataclass(frozen=True)
class ChallengeAsset:
    path: Path
    kind: Literal["image", "video"]
    answer: str


def image_answer(path: Path) -> str | None:
    match = re.match(r"^(\d+)", path.stem)
    return match.group(1) if match else None


def load_assets(viewers_dir: Path, media_mode: str = "mixed") -> list[ChallengeAsset]:
    img_dir = viewers_dir / "img"
    videos_dir = viewers_dir / "videos"
    assets: list[ChallengeAsset] = []

    if img_dir.exists():
        for path in sorted(img_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                answer = image_answer(path)
                if answer is not None:
                    assets.append(ChallengeAsset(path=path, kind="image", answer=answer))
                else:
                    LOGGER.warning("Skipping image with no numeric answer prefix: %s", path)

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
        wrongs = {item.answer for item in assets if item.kind == "image" and item.answer != correct}
        while len(wrongs) < 9:
            wrongs.add(str(random.randint(0, 99)))
    else:
        wrongs = {item.answer for item in assets if item.kind == "video" and item.answer != correct}
        while len(wrongs) < 9:
            wrongs.add("".join(random.choice(ALPHABET) for _ in range(4)))
        wrongs.discard(correct)

    selected = random.sample(sorted(wrongs), 9)
    options = selected + [correct]
    random.shuffle(options)
    return options
