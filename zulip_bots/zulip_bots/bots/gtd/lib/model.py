from __future__ import annotations

import enum
import string
from typing import cast

import structlog
from hashids import Hashids
from peewee import SqliteDatabase, Model, CharField, IntegerField, ForeignKeyField, BooleanField


hashids = Hashids(alphabet=string.digits + string.ascii_uppercase)
db = SqliteDatabase(None)
logger = structlog.get_logger()


class ProjectList(Model):
    id = IntegerField(primary_key=True)
    name = CharField(unique=True)

    class Meta:
        database = db

    @classmethod
    def upsert(cls, id: int | IntegerField, name: str | CharField) -> ProjectList:
        exists = cls.select().where(cls.id == id).get_or_none() != None
        logger.debug("ProjectList upsert", id=id, name=name, exists=exists)

        obj = cls(id=id, name=name)
        obj.save(force_insert=not exists)
        return obj


class Context(Model):
    id = IntegerField(primary_key=True)
    name = CharField(unique=True)

    class Meta:
        database = db

    @classmethod
    def upsert(cls, id: int | IntegerField, name: str | CharField) -> Context:
        exists = cls.select().where(cls.id == id).get_or_none() != None
        logger.debug("Context upsert", id=id, name=name, exists=exists)

        obj = cls(id=id, name=name)
        obj.save(force_insert=not exists)
        return obj


class Project(Model):
    id = IntegerField(primary_key=True)
    name = CharField()
    project_list = ForeignKeyField(ProjectList, backref="projects")
    completed = BooleanField()

    class Meta:
        database = db

    @classmethod
    def upsert(
        cls,
        id: int | IntegerField,
        name: str | CharField,
        project_list: ProjectList | ForeignKeyField,
        completed: bool | BooleanField,
    ) -> Project:
        exists = cls.select().where(cls.id == id).get_or_none() != None
        logger.debug(
            "Project upsert",
            id=id,
            name=name,
            project_list=project_list,
            completed=completed,
            exists=exists,
        )

        obj = cls(id=id, name=name, project_list=project_list, completed=completed)
        obj.save(force_insert=not exists)
        return obj


class Task(Model):
    id = IntegerField(primary_key=True)
    name = CharField()
    project = ForeignKeyField(Project, backref="tasks", null=True)
    context = ForeignKeyField(Context, backref="tasks")
    completed = BooleanField()

    class Meta:
        database = db

    @classmethod
    def upsert(
        cls,
        id: int | IntegerField,
        name: str | CharField,
        project: Project | ForeignKeyField,
        context: Context | ForeignKeyField,
        completed: bool | BooleanField,
    ) -> Task:
        exists = cls.select().where(cls.id == id).get_or_none() != None
        logger.debug(
            "Task upsert",
            id=id,
            name=name,
            project=project,
            context=context,
            completed=completed,
            exists=exists,
        )

        obj = cls(id=id, name=name, project=project, context=context, completed=completed)
        obj.save(force_insert=not exists)
        return obj


MODELS = [ProjectList, Project, Context, Task]


class DB:
    def __init__(self, file_name: str):
        self.file_name = file_name

    def __enter__(self) -> SqliteDatabase:
        db.init(self.file_name)
        db.__enter__()
        db.create_tables(MODELS)
        return db

    def __exit__(self, *args, **kwargs):
        db.__exit__(*args, **kwargs)


MODEL_TYPE_HINT = type[ProjectList] | type[Project] | type[Context] | type[Task]


class Keygen:
    MODEL_2_ORD: dict[MODEL_TYPE_HINT, int] = {
        ProjectList: ord("L"),
        Context: ord("C"),
        Project: ord("P"),
        Task: ord("T"),
    }
    ORD_2_MODEL: dict[int, MODEL_TYPE_HINT] = {
        ord("L"): ProjectList,
        ord("C"): Context,
        ord("P"): Project,
        ord("T"): Task,
    }

    @classmethod
    def encode(cls, obj: ProjectList | Project | Context | Task) -> str:
        return hashids.encode(cls.MODEL_2_ORD[obj.__class__], cast(int, obj.id))

    @classmethod
    def decode(cls, key: str) -> Model:
        char, id = hashids.decode(key)
        model = cls.ORD_2_MODEL[char]
        return model.select().where(model.id == id).get()

    @classmethod
    def decode_id(cls, key: str) -> int | None:
        result = hashids.decode(key)
        if result:
            return result[1]
        return None

    @classmethod
    def decode_all(cls, multikey: str) -> dict[str, Model]:
        return {
            obj.__class__.__name__: obj for key in multikey.split("-") if (obj := cls.decode(key))
        }
