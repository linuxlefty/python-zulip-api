# See readme.md for instructions on running this code.

import textwrap
import re
from ulid import ULID

import zulip
from zulip_bots.bots.gtd.lib.util import _Logger
import zulip_bots.bots.gtd.lib.model as Model
import zulip_bots.bots.gtd.lib.view as View
from zulip_bots.bots.gtd.lib.controller import ProjectList, Project, Context, Task
from zulip_bots.lib import BotHandler

Message = dict[str, str]


class GTDHandler:
    COMMANDS = {
        "inbox": (
            "Usage: `inbox <description>`\n"
            "  * Capture a new piece of information in your #**Inbox**.\n"
            "  * It will create this stream if it doesn't already exist."
        ),
        "todo": (
            "Usage: `todo @<context> <description>`\n"
            "  * Capture a new task.\n"
            "  * Will create a new context stream if it doesn't already exist."
        ),
        "db.rebuild": (
            "Usage: `db.rebuild`\n"
            "  * Retrieves all messages build a database of projects and tasks"
        ),
    }

    def __init__(self, db: Model.DB | None = None) -> None:
        self.db = db

    def initialize(self, bot_handler: BotHandler) -> None:
        self.log = _Logger(self.__class__.__name__)
        if self.db is None:
            if not (db_file := bot_handler.get_config_info("gtd").get("db_file")):
                raise ValueError("`db_file` not provided in the config")
            self.db = Model.DB(db_file)

    @staticmethod
    def usage() -> str:
        return "This bot helps with implementing GTD with Zulip."

    @classmethod
    def help(cls) -> str:
        return "\n".join(
            [cls.usage(), "It supports the following commands:", "* `help`: prints this output"]
            + [f"* `{command}`: {description}" for command, description in cls.COMMANDS.items()]
        )

    def command_help(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        bot_handler.send_reply(message, self.help())

    def _ensure_stream_exists(
        self, description: str, user_id: int, stream: str, client: zulip.Client
    ) -> int:
        response = client.add_subscriptions(
            streams=[
                {
                    "name": stream,
                    "description": "Catch-all for incoming stuff",
                }
            ],
            principals=[user_id],
            authorization_errors_fatal=True,
            announce=True,
        )
        assert response["result"] == "success"

        assert (response := client.get_stream_id(stream))["result"] == "success", response["msg"]
        return response["stream_id"]

    def _create_message_and_forward(
        self,
        source: Message,
        stream: str,
        stream_id: int,
        subject: str,
        client: zulip.Client,
        bot_handler: BotHandler,
    ) -> None:
        assert self.db
        if source["display_recipient"].startswith("Projects.") and stream.startswith("@"):
            self.log.log("Project and context detected. Updating database")
            with self.db as db:
                project_list = ProjectList(client).find(
                    id=source["stream_id"], name=source["display_recipient"]
                )
                project = Project(client).find(
                    name=source["subject"],
                    project_list=project_list,
                    resolved=source["subject"].startswith("✔"),
                )
                context = Context(client).find(id=stream_id, name=stream)
                task = Model.Task(
                    name=subject,
                    project=project,
                    context=context,
                    completed=subject.startswith("✔"),
                )
                View.Task(task, client).init()  # Set up the subject links

                response = bot_handler.send_message(
                    dict(
                        type="stream",
                        to=context.name,
                        subject=task.name,
                        content=(
                            # Have a link back origining message unless this is a PM
                            f"Created from #**{source['display_recipient']}>{source['subject']}"
                            if source["type"] == "stream"
                            else subject
                        ),
                    )
                )
                assert response
                assert response and response["result"] == "success", response["msg"]

                Model.Task.upsert(
                    id=response["id"],
                    name=task.name,
                    project=task.project,
                    context=task.context,
                    completed=task.completed,
                )
        else:
            self.log.log("Not a project or not sending to a context")

            response = bot_handler.send_message(
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
            assert response
            assert response and response["result"] == "success", response["msg"]

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

    def command_todo(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        """
        Creates a new message in a context stream and links back to the current stream.
        The context stream will be created if it doesn't already exist.
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "todo"

        if not (r := re.search(r'#\**"?@"?(?P<context>[\w\s]+)["\*]+\s+(?P<message>.*)', payload)):
            bot_handler.send_reply(
                message, "Sorry, I couldn't parse that TODO. Try running `help`?"
            )
            return

        context, task = r.groups()

        # Ensure that the context stream exists
        stream_id = self._ensure_stream_exists(
            stream=f"@{context}",
            description="",
            user_id=int(message["sender_id"]),
            client=client,
        )

        self._create_message_and_forward(
            source=message,
            stream=f"@{context}",
            stream_id=stream_id,
            subject=task,
            client=client,
            bot_handler=bot_handler,
        )

    # def command_db_rebuild(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
    #     """
    #     Retrieves all messages build a database of projects and tasks
    #     """
    #     command, _, payload = message["content"].partition(" ")
    #     assert command == "db.rebuild"

    #     with self.db as db:

    #         assert (response := client.get_streams())['result'] == 'success'

    #         for stream in response['streams']:
    #             match stream['name']:
    #                 case 'Inbox' | name if name.startswith('Projects.'):
    #                     self.log.log('Storing ProjectList `{name}`')
    #                     ProjectList(id=stream['id'], name=name).save()
    #                 case name if name.startswith('@'):
    #                     self.log.log('Storing Context `{name}`')
    #                     Context(id=stream['id'], name=name).save()
    #                 case name:
    #                     self.log.log('Skipping stream: `{name}`')

    #         for project_list in ProjectList.select():
    #             assert (response := client.get_stream_topics(project_list.id))['result'] == 'success'
    #             for topic in response['topics']:
    #                 Project(project_list=project_list, name=topic['name'], resolved=topic['name'].startswith('✔')).save()

    #         for context in Context.select():
    #             assert (response := client.get_stream_topics(context.id))['result'] == 'success'
    #             for topic in response['topics']:

    def handle_message(self, message: Message, bot_handler: BotHandler) -> None:
        client: zulip.Client = bot_handler._client  # type: ignore

        match message["content"].partition(" ")[0]:
            case "help":
                self.command_help(message, client, bot_handler)
            case "inbox":
                self.command_inbox(message, client, bot_handler)
            case "todo":
                self.command_todo(message, client, bot_handler)
            case _:
                bot_handler.send_reply(
                    message,
                    f"Sorry, command not recognized: `{message['content']}`. Try running `help`?",
                )


handler_class = GTDHandler
