import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from app.completion_service import (
    COMPLETION_CALLBACK_PREFIX,
    claim_completion_callback,
    finish_completion_callback,
    parse_completion_callback_data,
)

router = Router()
LOGGER = logging.getLogger(__name__)


@router.callback_query(F.data.startswith(COMPLETION_CALLBACK_PREFIX))
async def completion_done_callback(callback: CallbackQuery, bot: Bot) -> None:
    result_text = "Не удалось обработать кнопку."
    answer_attempted = False
    try:
        occurrence_id = parse_completion_callback_data(callback.data)
        message = callback.message
        if occurrence_id is None or message is None:
            return

        chat = getattr(message, "chat", None)
        message_id = getattr(message, "message_id", None)
        if chat is None or message_id is None:
            return

        result = await claim_completion_callback(
            occurrence_id=occurrence_id,
            chat_id=int(chat.id),
            callback_message_id=int(message_id),
            callback_message_sent_at=getattr(message, "date", None),
            user_id=int(callback.from_user.id),
            display_name=callback.from_user.full_name,
        )
        result_text = str(result["response_text"])
        answer_attempted = True
        try:
            await callback.answer(result_text)
        except Exception:
            LOGGER.warning("Could not answer completion callback.", exc_info=True)
        await finish_completion_callback(bot, result)
    except Exception:
        LOGGER.exception("Completion callback processing failed.")
    finally:
        if not answer_attempted:
            try:
                await callback.answer(result_text)
            except TelegramAPIError:
                LOGGER.warning("Could not answer completion callback.", exc_info=True)
