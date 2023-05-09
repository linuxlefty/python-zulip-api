from typing import cast

import zulip
import zulip_bots.bots.gtd.lib.model as Model
import zulip_bots.bots.gtd.lib.view as View
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message
from zulip_bots.bots.gtd.lib.controller import (
    ProjectList,
    Project,
    Context,
    Task,
    UnableToFindError,
)


class DbRebuildCommand(BaseCommand):
    META = dict(
        command="db.rebuild",
        usage="db.rebuild",
        description="Retrieves all messages build a database of projects and tasks",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        """
        Retrieves all messages build a database of projects and tasks
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "db.rebuild"

        with self.db as db:
            self.log.warning("Truncating tables")
            Model.Task.truncate_table()
            Model.Context.truncate_table()
            Model.Project.truncate_table()
            Model.ProjectList.truncate_table()

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


class DbPurgeCommand(BaseCommand):
    META = dict(
        command="db.purge",
        usage="db.purge",
        description="Deletes the internal database. Purges all project IDs from topic names. **WARNING** this is irreversable. Proceed with caution.",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        """
        Retrieves all messages build a database of projects and tasks
        """
        command, _, payload = message["content"].partition(" ")
        assert command == "db.purge"
        assert payload == "--force", "This is a dangerous command. It must be called with '--force'"

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
