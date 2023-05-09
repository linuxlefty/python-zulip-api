import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message
from zulip_bots.bots.gtd.lib.controller import find as FindObj, UnableToFindError
import zulip_bots.bots.gtd.lib.model as Model


class AuditCommand(BaseCommand):
    META = dict(
        command="audit",
        usage="audit",
        description="Takes a look and finds any projects that don't have any tasks",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        command, _, payload = message["content"].partition(" ")
        assert command == "audit"

        with self.db:
            idle_projects = [
                project
                for project in Model.Project.select()
                if (
                    not [task for task in project.tasks if not task.completed]
                    and not project.completed
                )
            ]

            if not idle_projects:
                bot_handler.send_reply(message, "You have no idle projects :tada:")
            else:
                lines = ["You have the following idle projects:"]
                for project in idle_projects:
                    lines.append(
                        f"* {self._internal_link_md(project.project_list.name, project.name)}"
                    )

                bot_handler.send_reply(message, "\n".join(lines))

            if message["type"] == "stream":
                try:
                    obj = FindObj(
                        stream=message["display_recipient"],
                        stream_id=int(message["stream_id"]),
                        topic=message["subject"],
                        client=client,
                    )
                except UnableToFindError:
                    self.log.info("Not a Project")
                else:
                    if isinstance(obj, Model.Project):
                        lines = ["This project has been associted with the following tasks:"]
                        for task in obj.tasks:  # type: ignore
                            lines.append(
                                f"* {self._internal_link_md(task.context.name, task.name)}"
                            )
                        bot_handler.send_reply(message, "\n".join(lines))
                    else:
                        self.log.info("Not a Project")
