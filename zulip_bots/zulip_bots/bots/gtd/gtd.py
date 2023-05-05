# See readme.md for instructions on running this code.

import textwrap
import re

import zulip
from zulip_bots.lib import BotHandler

Message = dict[str, str]


class GTDHandler:
    COMMANDS = {
        "inbox": (
            "Usage: inbox <description>\n"
            "Capture a new piece of information in your #**Inbox**."
            " It will create this stream if it doesn't already exist."
        ),
        "todo": (
            "Usage todo @<context> <description>\n"
            "Capture a new task. Will create a new context stream if it doesn't already exist."
        ),
    }

    @staticmethod
    def usage() -> str:
        return "This bot helps with implementing GTD with Zulip."

    @classmethod
    def help(cls) -> str:
        return (
            cls.usage()
            + textwrap.dedent(
                """\
            It supports the following commands:

            | Command | Description |
            | ------- | ----------- |
            | help | prints this output |
            """
            )
            + "\n".join(
                f"| {command} | {description} |" for command, description in cls.COMMANDS.items()
            )
        )

    def command_help(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        bot_handler.send_reply(message, self.help())

    def _ensure_stream_exists(
        self, description: str, user_id: int, stream: str, client: zulip.Client
    ):
        return client.add_subscriptions(
            streams=[
                {
                    "name": stream,
                    "description": "Catch-all for incoming stuff",
                }
            ],
            principals=user_id,
            authorization_errors_fatal=True,
            announce=True,
        )

    def _create_message_and_forward(
        self, source: Message, stream: str, subject: str, bot_handler: BotHandler
    ) -> None:
        bot_handler.send_message(
            dict(
                type="stream",
                to=stream,
                subject=subject,
                content=(
                    # Have a link back origining message unless this is a PM
                    f"Created from #**{source['display_recipient']}>{source['subject']}"
                    if source["type"] == "stream"
                    else subject
                ),
            )
        )

        bot_handler.react(source, "robot")
        bot_handler.send_reply(source, f"Created #**{stream}>{subject}**")

    def command_inbox(
        self, message: Message, client: zulip.Client, bot_handler: BotHandler
    ) -> None:
        """
        Creates a new message in the #Inbox stream and links back to the current stream.
        The #Inbox stream will be created if it doesn't already exist.
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "inbox"

        # Ensure that the inbox stream exists
        self._ensure_stream_exists(
            stream="Inbox",
            description="Catch-all for incoming stuff",
            user_id=message["sender_id"],
            client=client,
        )

        self._create_message_and_forward(
            source=message, stream="Inbox", subject=payload, bot_handler=bot_handler
        )

    def command_todo(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> str:
        """
        Creates a new message in a context stream and links back to the current stream.
        The context stream will be created if it doesn't already exist.
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "todo"

        if not (r := re.search(r'#\**"?@"?(?P<context>[\w\s]+)["\*]+\s+(?P<message>.*)', payload)):
            bot_handler.send_reply(message, "Sorry, I couldn't parse that TODO. Try running `help`?")
            return

        context, task = r.groups()

        # Ensure that the context stream exists
        self._ensure_stream_exists(
            stream=f"@{context}",
            description="",
            user_id=message["sender_id"],
            client=client,
        )

        self._create_message_and_forward(
            source=message, stream=f"@{context}", subject=task, bot_handler=bot_handler
        )

    def handle_message(self, message: Message, bot_handler: BotHandler) -> None:
        client = bot_handler._client

        match message["content"].partition(' ')[0]:
            case "help":
                self.command_help(message, client, bot_handler)
            case 'inbox':
                self.command_inbox(message, client, bot_handler)
            case "todo":
                self.command_todo(message, client, bot_handler)
            case _:
                bot_handler.send_reply(
                    message,
                    f"Sorry, command not recognized: `{message['content']}`. Try running `help`?",
                )


handler_class = GTDHandler
