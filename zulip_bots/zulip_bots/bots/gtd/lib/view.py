import re
from typing import cast

import zulip
import zulip_bots.bots.gtd.lib.model as Model
from zulip_bots.lib import BotHandler

# NOTE: Zulip has Stream IDs, but they don't have topic IDs
# Because of that, we will be using the Message ID of the first message
# in the topic as the Project/Task ID


class Project:
    RE = re.compile(r"(?P<topic>.*)\s+#(?P<project_list>[0-9A-Z]+)-(?P<project>[0-9A-Z]+)")

    def __init__(self, project: Model.Project, client: zulip.Client) -> None:
        self.project = project
        self.client = client
        self.dirty: set[str] = set()
        return None

    @classmethod
    def parse_name(cls, name: str) -> dict[str, str] | None:
        if result := cls.RE.match(name):
            return result.groupdict()
        return None

    def init(self) -> bool:
        # Note, you have to initialize ID first so that the name can use it via hashid
        return bool(self.id and self.name)

    @property
    def name(self):
        if groups := self.parse_name(cast(str, self.project.name)):
            if (
                groups["project_list"] == self.project.project_list.id
                and groups["project"] == self.id
            ):
                return self.project.name

            # Clear off old ID
            self.project.name = cast(
                Model.CharField, cast(str, self.project.name).rpartition("#")[0].strip()
            )

        self.project.name += f" #{Model.Keygen.encode(self.project.project_list)}-{Model.Keygen.encode(self.project)}"  # type: ignore
        self.dirty.add("name")
        return self.project.name

    @property
    def id(self) -> int:
        if id := cast(int, self.project.id):
            return id

        result = self.client.get_messages(
            dict(
                anchor="oldest",
                narrow=[
                    dict(operator="stream", operand=self.project.project_list.id),
                    dict(operator="topic", operand=self.project.name),
                ],
                num_before=0,
                num_after=0,
            )
        )

        if not result["messages"]:
            raise RuntimeError("Unable to find the message!?")

        self.project.id = result["messages"][0]["id"]
        self.dirty.add("id")
        return cast(int, self.project.id)


class Task:
    RE = re.compile(
        r"(?P<topic>.*)\s+#(?P<project_list>[0-9A-Z]+)-(?P<project>[0-9A-Z]+)-(?P<context>[0-9A-Z]+)-(?P<task>[0-9A-Z]+)"
    )

    def __init__(self, task: Model.Task, client: zulip.Client):
        self.task = task
        self.client = client
        self.dirty: set[str] = set()

    @classmethod
    def parse_name(cls, name: str) -> dict[str, str] | None:
        if result := cls.RE.match(name):
            return result.groupdict()
        return None

    def init(self) -> bool:
        # Note, you have to initialize ID first so that the name can use it via hashid
        return bool(self.id and self.name)

    @property
    def name(self):
        if groups := self.parse_name(cast(str, self.task.name)):
            if (
                groups["project"] == self.task.project.id
                and groups["project_list"] == self.task.project.project_list.id
                and groups["context"] == self.task.context.id
                and groups["task"] == self.id
            ):
                return self.task.name

            # Clear off old ID
            self.task.name = cast(
                Model.CharField, cast(str, self.task.name).rpartition("#")[0].strip()
            )

        self.task.name += f" #{Model.Keygen.encode(self.task.project.project_list)}-{Model.Keygen.encode(self.task.project)}-{Model.Keygen.encode(self.task.context)}-{Model.Keygen.encode(self.task)}"  # type: ignore
        self.dirty.add("name")
        return self.task.id

    @property
    def id(self) -> int:
        if id := cast(int, self.task.id):
            return id

        result = self.client.get_messages(
            dict(
                anchor="oldest",
                narrow=[
                    dict(operator="stream", operand=self.task.context.id),
                    dict(operator="topic", operand=self.task.name),
                ],
                num_before=0,
                num_after=0,
            )
        )

        if not result["messages"]:
            raise RuntimeError("Unable to find the message!?")

        self.task.id = result["messages"][0]["id"]
        self.dirty.add("id")
        return cast(int, self.task.id)
