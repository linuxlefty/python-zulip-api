import uuid
from typing import cast

import structlog

import zulip
import zulip_bots.bots.gtd.lib.view as View
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.lib.controller import (
    ProjectList,
    Project,
    Context,
    Task,
)

Message = dict[str, str]


class BaseCommand:
    META = dict(
        command="FIXME",
        description="FIXME",
        usage="FIXME",
    )

    def __init__(self, db: Model.DB) -> None:
        self.db = db
        self.log = structlog.get_logger()

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
                (view := View.Task(task, client)).init()  # Set up the subject line
                Model.Task.upsert(
                    id=task.id,
                    name=task.name,
                    project=task.project,
                    context=task.context,
                    completed=task.completed,
                )
                if "name" in view.dirty:
                    # Send the updated subject line to Zulip
                    source["subject"] = cast(str, project.name)
                    result = client.update_message(
                        dict(message_id=task.id, topic=task.name, propogate_mode="change_all")
                    )
                    assert result["result"] == "success", result["msg"]

                bot_handler.send_reply(
                    source, f"Created {self._internal_link_md(stream,task.name)}"
                )

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

            bot_handler.send_reply(source, f"Created {self._internal_link_md(stream,subject)}")

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        raise NotImplementedError()
