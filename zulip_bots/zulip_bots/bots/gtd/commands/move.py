from typing import cast

import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message
from zulip_bots.bots.gtd.lib.controller import find as FindObj
from zulip_bots.bots.gtd.lib.model import BooleanField


class BaseMove(BaseCommand):
    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        command, _, payload = message["content"].partition(" ")
        assert command == self.META["command"]

        assert (
            message["display_recipient"] == "Inbox"
        ), "Sorry this command has to be run in the Inbox"

        payload = payload.strip("# *")
        prefix = self.META["_payload_prefix"]
        assert payload.startswith(prefix), "Sorry, prefix must start with '{prefix}'"

        stream_id = self._ensure_stream_exists(
            stream=payload.strip(), description="", user_id=int(message["sender_id"]), client=client
        )

        response = client.update_message(
            dict(message_id=message["id"], stream_id=stream_id, propagate_mode="change_all")
        )
        assert response["result"] == "success", response["msg"]

        # Update message since it moved
        message["display_recipient"] = payload

        bot_handler.send_reply(message, f"Message moved to {payload}")


class ProjectCommand(BaseMove):
    META = dict(
        command="project",
        usage="project <project list>",
        description="Moves something from your inbox into a project list",
        _payload_prefix="Project",
    )


class TaskCommand(BaseMove):
    META = dict(
        command="task",
        usage="task <context>",
        description="Moves something from your inbox into a context",
        _payload_prefix="@",
    )
