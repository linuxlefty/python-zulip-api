# See readme.md for instructions on running this code.

import textwrap
import re
import uuid
from typing import cast

import structlog

import zulip
import zulip_bots.bots.gtd.lib.model as Model
import zulip_bots.bots.gtd.lib.view as View
from zulip_bots.bots.gtd.lib.controller import (
    ProjectList,
    Project,
    Context,
    Task,
    UnableToFindError,
)
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
        "find": (
            "Usage: `find [project_list|project|context|task] [partial name]\n`"
            "  * Searches for something in the database and returns the result"
        ),
        "db.rebuild": (
            "Usage: `db.rebuild`\n"
            "  * Retrieves all messages build a database of projects and tasks"
        ),
        "db.purge": (
            "Usage: `db.purge`\n"
            "  * Deletes the internal database. Purges all project IDs from topic names.\n"
            "  * **WARNING** this is irreversable. Proceed with caution.\n"
        ),
    }

    def __init__(self, db: Model.DB | None = None) -> None:
        self.db = db

    def initialize(self, bot_handler: BotHandler) -> None:
        self.log = structlog.get_logger()
        if self.db is None:
            if not (db_file := bot_handler.get_config_info("gtd").get("db_file")):
                raise ValueError("`db_file` not provided in the config")
            self.log.debug("initialized database", db_file=db_file)
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

    def _internal_link_md(
        self, stream: str | Model.CharField, topic: str | Model.CharField | None = None
    ):
        if topic:
            return f"#**{stream}>{topic}**"
        return f"#**{stream}**"

    def _ensure_stream_exists(
        self, description: str, user_id: int, stream: str, client: zulip.Client
    ) -> int:
        response = client.add_subscriptions(
            streams=[{"name": stream, "description": description}],
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
            self.log.info("Project and context detected. Updating database")
            with self.db as db:
                project_list = ProjectList(client).find(
                    id=source["stream_id"], name=source["display_recipient"]
                )
                project = Project(client).find(
                    name=source["subject"],
                    project_list=project_list,
                    completed=source["subject"].startswith("✔"),
                )
                context = Context(client).find(id=stream_id, name=stream)

                response = bot_handler.send_message(
                    dict(
                        type="stream",
                        to=context.name,
                        subject=(temp_task_name := str(uuid.uuid4())),
                        content=(
                            # Have a link back origining message unless this is a PM
                            f"{subject}\n------\nCreated from {self._internal_link_md(source['display_recipient'],project.name)}"
                            if source["type"] == "stream"
                            else subject
                        ),
                    )
                )
                assert response
                assert response and response["result"] == "success", response["msg"]

                # Now that the task has been created and we have an ID, save this in the database
                task = Model.Task(
                    id=response["id"],
                    name=subject,
                    project=project,
                    context=context,
                    completed=subject.startswith("✔"),
                )
                View.Task(task, client).init()  # Set up the subject line
                Model.Task.upsert(
                    id=task.id,
                    name=task.name,
                    project=task.project,
                    context=task.context,
                    completed=task.completed,
                )
                # Send the updated subject line to Zulip
                result = client.update_message(
                    dict(message_id=task.id, topic=task.name, propogate_mode="change_all")
                )
                assert result["result"] == "success", result["msg"]

        else:
            self.log.info("Not a project or not sending to a context")

            response = bot_handler.send_message(
                dict(
                    type="stream",
                    to=stream,
                    subject=subject,
                    content=(
                        # Have a link back origining message unless this is a PM
                        f"Created from {self._internal_link_md(source['display_recipient'],source['subject'])}"
                        if source["type"] == "stream"
                        else subject
                    ),
                )
            )
            assert response
            assert response and response["result"] == "success", response["msg"]

        bot_handler.react(source, "robot")
        bot_handler.send_reply(source, f"Created {self._internal_link_md(stream,subject)}")

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

    def command_find(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        command, _, payload = message["content"].partition(" ")
        assert command == "find"

        if not (r := re.search(r"(?P<operator>[\w]+)\s+(?P<operand>.*)", payload)):
            bot_handler.send_reply(
                message, "Sorry, I couldn't parse that FIND. Try running `help`?"
            )
            return

        operator, operand = r.groups()
        data: dict[str, str] = dict()

        assert self.db
        with self.db:
            match operator:
                case "project_list":
                    for project_list in Model.ProjectList.select().where(
                        Model.ProjectList.name.contains(operand)
                    ):
                        data[self._internal_link_md(project_list.name)] = Model.Keygen.encode(
                            project_list
                        )
                case "project":
                    for project in Model.Project.select().where(
                        Model.Project.name.contains(operand)
                    ):
                        data[
                            self._internal_link_md(project.project_list.name, project.name)
                        ] = Model.Keygen.encode(project)
                case "context":
                    for context in Model.Context.select().where(
                        Model.Context.name.contains(operand)
                    ):
                        data[self._internal_link_md(context.name)] = Model.Keygen.encode(context)
                case "task":
                    for task in Model.Task.select().where(Model.Task.name.contains(operand)):
                        data[
                            self._internal_link_md(task.context.name, task.name)
                        ] = Model.Keygen.encode(task)
                case _:
                    bot_handler.send_reply(
                        message, "Sorry, I couldn't parse that FIND. Try running `help`?"
                    )
                    return

        if data:
            result = "| Name | HashID |\n| ---- | ---- |\n"
            result += "\n".join(f"| {name} | `#{data[name]}` |" for name in sorted(data))
        else:
            result = "No results found"

        bot_handler.send_reply(message, result)

    def command_db_rebuild(
        self, message: Message, client: zulip.Client, bot_handler: BotHandler
    ) -> None:
        """
        Retrieves all messages build a database of projects and tasks
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "db.rebuild"

        assert self.db
        with self.db as db:
            assert (response := client.get_streams())["result"] == "success"

            for stream in response["streams"]:
                match stream["name"]:
                    case name if name.startswith("Project"):
                        project_list = ProjectList(client).find(id=stream["stream_id"], name=name)
                        self.log.info(
                            "Stored ProjectList", id=project_list.id, name=project_list.name
                        )
                    case name if name.startswith("@"):
                        context = Context(client).find(id=stream["stream_id"], name=name)
                        self.log.info("Stored Context", id=context.id, name=context.name)
                    case name:
                        self.log.debug("Skipping stream", name=name)

            for project_list in Model.ProjectList.select():
                assert (response := client.get_stream_topics(cast(int, project_list.id)))[
                    "result"
                ] == "success"
                for topic in response["topics"]:
                    if topic["name"] == "stream events":
                        self.log.debug("Skipping stream events")
                        continue
                    project = Project(client).find(
                        project_list=project_list,
                        name=topic["name"],
                        completed=topic["name"].startswith("✔"),
                    )
                    self.log.info(
                        "Stored project",
                        project_list=project.project_list.name,
                        name=project.name,
                        completed=project.completed,
                    )

            unknown_tasks = list()

            for context in Model.Context.select():
                assert (response := client.get_stream_topics(cast(int, context.id)))[
                    "result"
                ] == "success"
                for topic in response["topics"]:
                    if topic["name"] == "stream events":
                        self.log.debug("Skipping stream events")
                        continue
                    try:
                        task = Task(client).find(
                            project=None,
                            context=context,
                            name=topic["name"],
                            completed=topic["name"].startswith("✔"),
                        )
                        self.log.info(
                            "Stored task",
                            context=task.context.name,
                            name=task.name,
                            completed=task.completed,
                        )
                    except UnableToFindError:
                        self.log.warning(
                            "Unable to store task", context=context.name, name=topic["name"]
                        )
                        task = Model.Task(
                            context=context,
                            name=topic["name"],
                            completed=topic["name"].startswith("✔"),
                        )
                        view = View.Task(task, client)
                        unknown_tasks.append(
                            dict(
                                context=context,
                                name=topic["name"],
                                id=view.id,
                            )
                        )

        result = "Successfuly updated database!"
        if unknown_tasks:
            result += "\n\nThe following tasks could not be stored and need to be manually updated with their HashID:\n"
            result += "\n".join(
                (
                    f"  * {self._internal_link_md(metadata['context'].name, metadata['name'])}"
                    for metadata in unknown_tasks
                )
            )
        bot_handler.send_reply(message, result)

    def command_db_purge(
        self, message: Message, client: zulip.Client, bot_handler: BotHandler
    ) -> None:
        command, _, payload = message["content"].partition(" ")
        assert command == "db.purge"
        assert payload == "--force", "This is a dangerous command. It must be called with '--force'"

        assert self.db
        with self.db:
            self.log.warning("Truncating tables")
            Model.Task.truncate_table()
            Model.Context.truncate_table()
            Model.Project.truncate_table()
            Model.ProjectList.truncate_table()

        self.log.warning("Purging topics of IDs")

        stream_response = client.get_streams()
        assert stream_response["result"] == "success", stream_response["msg"]

        for stream in stream_response["streams"]:
            topic_response = client.get_stream_topics(stream["stream_id"])
            assert topic_response["result"] == "success", topic_response["msg"]

            for topic in topic_response["topics"]:
                old_topic = topic["name"]
                new_topic = old_topic.partition("#")[0] if "#" in old_topic else old_topic

                if old_topic == new_topic:
                    self.log.debug("Skipping topic. No change", topic=old_topic)
                    continue

                response = client.get_messages(
                    dict(
                        anchor="oldest",
                        narrow=(
                            [
                                dict(operator="stream", operand=stream["stream_id"]),
                                dict(operator="topic", operand=topic["name"]),
                            ]
                        ),
                        num_before=1,
                        num_after=1,
                    )
                )
                assert response["result"] == "success", response["msg"]
                message_id = response["messages"][0]["id"]

                self.log.info("Stripping off ID", old_topic=old_topic, new_topic=new_topic)
                response = client.update_message(
                    dict(message_id=message_id, topic=new_topic, propagate_mode="change_all")
                )
                assert response["result"] == "success", response["msg"]

        bot_handler.send_reply(message, ":nuclear: Purge complete :nuclear:")

    def handle_message(self, message: Message, bot_handler: BotHandler) -> None:
        client: zulip.Client = bot_handler._client  # type: ignore

        try:
            match message["content"].partition(" ")[0]:
                case "help":
                    self.command_help(message, client, bot_handler)
                case "inbox":
                    self.command_inbox(message, client, bot_handler)
                case "todo":
                    self.command_todo(message, client, bot_handler)
                case "find":
                    self.command_find(message, client, bot_handler)
                case "db.rebuild":
                    self.command_db_rebuild(message, client, bot_handler)
                case "db.purge":
                    self.command_db_purge(message, client, bot_handler)
                case _:
                    bot_handler.send_reply(
                        message,
                        f"Sorry, command not recognized: `{message['content']}`. Try running `help`?",
                    )
        except BaseException as e:
            bot_handler.send_reply(message, f"FATAL ERROR: ```{e}```")
            self.log.critical("Fatal error. Shutting down", error=e)
            raise


handler_class = GTDHandler
