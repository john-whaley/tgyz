import asyncio
import html
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from challenge_assets import ChallengeAsset, build_options, load_assets

LOGGER = logging.getLogger(__name__)
IMAGE_TRIGGER_PATTERN = re.compile(r"\byz(\d+)\b", re.IGNORECASE)


@dataclass
class PendingChallenge:
    chat_id: int
    target_user_id: int
    target_label: str
    correct_answer: str
    message_id: int
    token: str
    done: bool = False


class ChallengeBot:
    def __init__(self) -> None:
        self.viewers_dir = Path(os.getenv("VIEWERS_DIR", "viwers"))
        self.ttl_seconds = int(os.getenv("CHALLENGE_TTL_SECONDS", "180"))
        self.media_mode = os.getenv("MEDIA_MODE", "mixed").strip().lower()
        self.result_yes = os.getenv("RESULT_YES", "yes")
        self.result_no = os.getenv("RESULT_NO", "no")
        self.prompt_text = os.getenv("PROMPT_TEXT", "Please complete verification within 3 minutes.")
        self.expired_text = os.getenv("EXPIRED_TEXT", "Verification finished")
        self.not_yours_text = os.getenv("NOT_YOURS_TEXT", "This verification is not for you")
        self.submitted_text = os.getenv("SUBMITTED_TEXT", "Submitted")
        self.assets = load_assets(self.viewers_dir, self.media_mode)
        self.pending: dict[str, PendingChallenge] = {}

    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        if message is None or user is None or chat is None:
            return
        if user.is_bot:
            return
        if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return

        asset = self._asset_for_message(message.text or message.caption or "")
        token = secrets.token_urlsafe(9)
        options = build_options(asset, self.assets)
        keyboard = self._keyboard_for(token, options)
        target_label = self._target_label(user)
        caption = f"{target_label} {html.escape(self.prompt_text)}"

        try:
            sent = await self._send_challenge_media(message, asset, caption, keyboard)
        except TelegramError:
            LOGGER.exception("Failed to send challenge for %s", user.id)
            return

        self.pending[token] = PendingChallenge(
            chat_id=chat.id,
            target_user_id=user.id,
            target_label=target_label,
            correct_answer=asset.answer,
            message_id=sent.message_id,
            token=token,
        )
        asyncio.create_task(self._expire_later(context, token))

    def _asset_for_message(self, text: str) -> ChallengeAsset:
        match = IMAGE_TRIGGER_PATTERN.search(text)
        if match:
            image_index = int(match.group(1))
            for asset in self.assets:
                if asset.kind == "image" and asset.image_index == image_index:
                    return asset
            LOGGER.info("No image asset found for yz%s; using random asset", image_index)
        return secrets.choice(self.assets)

    @staticmethod
    async def _send_challenge_media(
        message,
        asset: ChallengeAsset,
        caption: str,
        keyboard: InlineKeyboardMarkup,
    ):
        with asset.path.open("rb") as media:
            if asset.kind == "image":
                return await message.reply_photo(
                    photo=media,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            return await message.reply_video(
                video=media,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                supports_streaming=True,
            )

    @staticmethod
    def _keyboard_for(token: str, options: list[str]) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        for index in range(0, len(options), 2):
            row = [
                InlineKeyboardButton(text=answer, callback_data=f"verify:{token}:{answer}")
                for answer in options[index : index + 2]
            ]
            rows.append(row)
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _target_label(user) -> str:
        if user.username:
            return f"@{html.escape(user.username)}"
        name = html.escape(user.full_name or str(user.id))
        return f'<a href="tg://user?id={user.id}">{name}</a>'

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None or not query.data:
            return

        parts = query.data.split(":", 2)
        if len(parts) != 3 or parts[0] != "verify":
            return
        _, token, answer = parts
        challenge = self.pending.get(token)
        if challenge is None or challenge.done:
            await query.answer(self.expired_text, show_alert=True)
            return
        if user.id != challenge.target_user_id:
            await query.answer(self.not_yours_text, show_alert=True)
            return

        challenge.done = True
        self.pending.pop(token, None)
        is_correct = answer == challenge.correct_answer
        await query.answer(self.submitted_text)
        await self._finish(context, challenge, self.result_yes if is_correct else self.result_no)

    async def _expire_later(self, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
        await asyncio.sleep(self.ttl_seconds)
        challenge = self.pending.get(token)
        if challenge is None or challenge.done:
            return
        challenge.done = True
        self.pending.pop(token, None)
        await self._finish(context, challenge, self.result_no)

    async def _finish(self, context: ContextTypes.DEFAULT_TYPE, challenge: PendingChallenge, result: str) -> None:
        try:
            await context.bot.send_message(
                chat_id=challenge.chat_id,
                text=result,
                reply_to_message_id=challenge.message_id,
                allow_sending_without_reply=True,
            )
        except TelegramError:
            LOGGER.exception("Failed to send verification result")

        try:
            await context.bot.edit_message_reply_markup(
                chat_id=challenge.chat_id,
                message_id=challenge.message_id,
                reply_markup=None,
            )
        except BadRequest as exc:
            LOGGER.debug("Could not remove challenge buttons: %s", exc)
        except TelegramError:
            LOGGER.exception("Failed to remove challenge buttons")


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    bot = ChallengeBot()
    application = Application.builder().token(token).build()
    application.add_handler(CallbackQueryHandler(bot.handle_callback, pattern=r"^verify:"))
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, bot.handle_group_message)
    )
    LOGGER.info("Telegram verification bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
