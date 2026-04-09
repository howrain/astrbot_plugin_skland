from __future__ import annotations

import asyncio


class MessageService:
    async def send_and_get_msg_id(self, event, obmsg: list):
        try:
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                    AiocqhttpMessageEvent,
                )

                if isinstance(event, AiocqhttpMessageEvent):
                    client = event.bot
                    group_id = getattr(event.message_obj, "group_id", None)
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
                        return client, msg_id
        except Exception:
            return None, None
        return None, None

    def schedule_recall(self, client, message_id: int, delay: float):
        async def _do_recall():
            await asyncio.sleep(delay)
            try:
                await client.delete_msg(message_id=message_id)
            except Exception:
                pass

        return asyncio.create_task(_do_recall())

    async def recall_now(self, client, message_id: int):
        try:
            await client.delete_msg(message_id=message_id)
        except Exception:
            pass
