import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message


class InboxCommand(BaseCommand):
    META = dict(
        command="inbox",
        usage="inbox <description>",
        description="Capture a new piece of information in your #**Inbox**. It will create this stream if it doesn't already exist.",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        """
        Creates a new message in the #Inbox stream and links back to the current stream.
        The #Inbox stream will be created if it doesn't already exist.
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "inbox"

        # Ensure that the inbox stream exists
        stream_id = self._ensure_stream_exists(
            stream="Inbox",
            description="Catch-all for incoming stuff",
            user_id=int(message["sender_id"]),
            client=client,
        )

        self._create_message_and_forward(
            source=message,
            stream="Inbox",
            stream_id=stream_id,
            subject=payload,
            client=client,
            bot_handler=bot_handler,
        )
