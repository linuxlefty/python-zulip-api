import re

import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message


class TodoCommand(BaseCommand):
    META = dict(
        command="todo",
        usage="todo @<context> <description>",
        description=(
            "Capture a new task. Will create a new context stream if it doesn't already exist."
        ),
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        """
        Creates a new message in a context stream and links back to the current stream.
        The context stream will be created if it doesn't already exist.
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "todo"

        if not (r := re.search(r'#\**"?@"?(?P<context>[^"\*]+)["\*]+\s+(?P<message>.*)', payload)):
            bot_handler.send_reply(
                message, "Sorry, I couldn't parse that TODO. Try running `help`?"
            )
            return

        context, task = r.groups()
        context = "@" + context

        # Ensure that the context stream exists
        stream_id = self._ensure_stream_exists(
            stream=context,
            description="",
            user_id=int(message["sender_id"]),
            client=client,
        )

        self._create_message_and_forward(
            source=message,
            stream=context,
            stream_id=stream_id,
            subject=task,
            client=client,
            bot_handler=bot_handler,
        )
