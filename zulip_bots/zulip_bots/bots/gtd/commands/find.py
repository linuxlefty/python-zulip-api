import re
import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message
from zulip_bots.lib import BotHandler


class FindCommand(BaseCommand):
    META = dict(
        command="find",
        usage="find [project_list|project|context|task] [partial name]",
        description="Searches for something in the database and returns the result",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
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
