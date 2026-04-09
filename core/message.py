from __future__ import annotations

import asyncio

from astrbot.api import logger


class MessageService:
    async def send_and_get_msg_id(self, event, obmsg: list):
        try:
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                    AiocqhttpMessageEvent,
                )

                if isinstance(event, AiocqhttpMessageEvent):
                    client = event.bot
                    group_id = getattr(event.message_obj, "group_id", None) or getattr(event, "get_group_id", lambda: None)()
                    if group_id:
                        send_result = await client.send_group_msg(
                            group_id=int(group_id), message=obmsg
                        )
                    else:
                        send_result = await client.send_private_msg(
                            user_id=int(event.get_sender_id()), message=obmsg
                        )
                    if send_result:
                        msg_id = int(send_result.get("message_id"))
                        logger.info(f"[Skland][消息追踪] 消息已发送，message_id={msg_id}")
                        return client, msg_id
        except Exception as exc:
            logger.warning(f"[Skland][消息追踪] 协议端发送失败: {exc}")
            return None, None
        return None, None

    def schedule_recall(self, client, message_id: int, delay: float):
        async def _do_recall():
            await asyncio.sleep(delay)
            try:
                await client.delete_msg(message_id=message_id)
                logger.info(f"[Skland][撤回] 已撤回消息 {message_id}")
            except Exception as exc:
                logger.warning(f"[Skland][撤回] 撤回消息失败: {exc}")

        return asyncio.create_task(_do_recall())

    async def recall_now(self, client, message_id: int):
        try:
            await client.delete_msg(message_id=message_id)
            logger.info(f"[Skland][撤回] 已立即撤回消息 {message_id}")
        except Exception as exc:
            logger.warning(f"[Skland][撤回] 立即撤回失败: {exc}")
