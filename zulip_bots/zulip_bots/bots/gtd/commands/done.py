from typing import cast

import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message
from zulip_bots.bots.gtd.lib.controller import find as FindObj
from zulip_bots.bots.gtd.lib.model import BooleanField


class DoneCommand(BaseCommand):
    META = dict(
        command="done",
        usage="done",
        description="Marks a task or project as done",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        command, _, payload = message["content"].partition(" ")
        assert command == "done"

        assert message["type"] == "stream", "Sorry you can't use this command in DMs"

        with self.db:
            obj = FindObj(
                stream=message["display_recipient"],
                stream_id=int(message["stream_id"]),
                topic=message["subject"],
                client=client,
            )

            # Mark it as done in Zulip
            message["subject"] = "✔ " + message["subject"]
            response = client.update_message(
                dict(message_id=obj.id, topic=message["subject"], propagate_mode="change_all")
            )

            # Mark it as done in the database
            obj.completed = cast(BooleanField, True)
            obj.save()

            bot_handler.send_reply(message, f"{obj} marked as complete :check:")
