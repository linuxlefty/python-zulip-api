from typing import TypeVar, Generic

import zulip
import zulip_bots.bots.gtd.lib.model as Model
import zulip_bots.bots.gtd.lib.view as View

T = TypeVar("T")


class BaseController(Generic[T]):
    def __init__(self, client: zulip.Client):
        self.client = client

    def find(self, **kwargs) -> T:
        for name in sorted(dir(self)):
            if name.startswith("_finder_") and callable((attribute := getattr(self, name))):
                if result := attribute(**kwargs):
                    return result

        raise ValueError(f"Unable to find {self.__class__.__name__}: {kwargs}")


class ProjectList(BaseController[Model.ProjectList]):
    def _finder_1_all_fields_exist_and_is_a_project_list(
        self, id: int | None, name: str | None
    ) -> Model.ProjectList | None:
        if id and name and name.startswith("Project."):
            return Model.ProjectList.upsert(id, name)
        return None

    def _finder_2_it_is_in_the_database(
        self, id: int | None, name: str | None
    ) -> Model.ProjectList | None:
        # Doing separate selects because I'm paranoid.
        # I want to ensure it matches on `id` before `name` if it would result in two different rows
        return (
            Model.ProjectList.select().where(Model.ProjectList.id == id).get_or_none()
            or Model.ProjectList.select().where(Model.ProjectList.name == name).get_or_none()
        )

    def _finder_3_it_is_a_project(self, name: str | None, **_) -> Model.ProjectList | None:
        if name and name.startswith("Project."):
            assert (response := self.client.get_stream_id(name))["result"] == "success", response[
                "msg"
            ]
            return Model.ProjectList.upsert(response["stream_id"], name)
        return None


class Context(BaseController[Model.Context]):
    def _finder_1_all_fields_exist_and_is_a_context(
        self, id: int | None, name: str | None
    ) -> Model.Context | None:
        if id and name and name.startswith("@"):
            return Model.Context.upsert(id, name)
        return None

    def _finder_2_it_is_in_the_database(
        self, id: int | None, name: str | None
    ) -> Model.Context | None:
        # Doing separate selects because I'm paranoid.
        # I want to ensure it matches on `id` before `name` if it would result in two different rows
        return (
            Model.Context.select().where(Model.Context.id == id).get_or_none()
            or Model.Context.select().where(Model.Context.name == name).get_or_none()
        )

    def _finder_3_it_is_a_context(self, name: str | None, **_) -> Model.Context | None:
        if name and name.startswith("@"):
            assert (response := self.client.get_stream_id(name))["result"] == "success", response[
                "msg"
            ]
            return Model.Context.upsert(response["stream_id"], name)
        return None


class Project(BaseController[Model.Project]):
    def _finder_1_all_fields_exist(
        self, id: int, name: str, project_list: Model.ProjectList, completed: bool
    ) -> Model.Project | None:
        if all((id, name, project_list, completed)):
            return Model.Project.upsert(id, name, project_list, completed)
        return None

    def _finder_2_the_key_is_embedded_in_the_name(self, name: str, **_) -> Model.Project | None:
        if (groups := View.Project.parse_name(name)) and (id := groups.get("project")):
            return Model.Project.get_by_id(id)
        return None

    def _finder_3_we_can_find_the_parent_message_in_zulip(
        self, name: str, project_list: Model.ProjectList, completed: bool
    ) -> None:
        obj = Model.Project(name=name, project_list=project_list, completed=completed)
        fmt = View.Project(obj, self.client)
        if fmt.init():
            Model.Project.upsert(obj.id, obj.name, obj.project_list, obj.completed)

        # If the name changed, we need to send that back to Zulip
        if "name" in fmt.dirty:
            result = self.client.update_message(
                dict(message_id=obj.id, topic=obj.name, propogate_mode="change_all")
            )
            assert result["success"], result["msg"]


class Task(BaseController[Model.Task]):
    def _finder_1_all_fields_exist(
        self, id: int, name: str, project: Model.Project, context: Model.Context, completed: bool
    ) -> Model.Task | None:
        if all((id, name, project, context, completed)):
            return Model.Task.upsert(id, name, project, context, completed)
        return None

    def _finder_2_the_key_is_embedded_in_the_name(self, name: str, **_) -> Model.Task | None:
        if (groups := View.Task.parse_name(name)) and (id := groups.get("task")):
            return Model.Task.get_by_id(id)
        return None

    def _finder_3_we_can_find_the_parent_message_in_zulip(
        self, name: str, project: Model.Project, context: Context, completed: bool
    ) -> None:
        obj = Model.Task(name=name, project=project, context=context, completed=completed)
        fmt = View.Task(obj, self.client)
        if fmt.init():
            Model.Task.upsert(obj.id, obj.name, obj.project, obj.context, obj.completed)

        # If the name changed, we need to send that back to Zulip
        if "name" in fmt.dirty:
            result = self.client.update_message(
                dict(message_id=obj.id, topic=obj.name, propogate_mode="change_all")
            )
            assert result["success"], result["msg"]
        return None
