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
from zulip_bots.bots.gtd.commands.base import BaseCommand, Message
from zulip_bots.bots.gtd.commands.inbox import InboxCommand
from zulip_bots.bots.gtd.commands.todo import TodoCommand
from zulip_bots.bots.gtd.commands.find import FindCommand
from zulip_bots.bots.gtd.commands.db import DbRebuildCommand, DbPurgeCommand


class HelpCommand(BaseCommand):
    META = dict(
        command="help",
        description="Prints this help message",
        usage="help",
    )

    def execute(self, message: Message, client: zulip.Client, bot_handler: BotHandler) -> None:
        bot_handler.send_reply(message, self.help())

    @staticmethod
    def usage() -> str:
        return "This bot helps with implementing GTD with Zulip."

    @classmethod
    def help(cls) -> str:
        lines = [cls.usage(), "It supports the following commands:", "* `help`: prints this output"]

        for command in COMMANDS:
            lines.append(f"* `{command.META['command']}`: {command.META['description']}")
            lines.append(f"  * usage: `{command.META['usage']}`")

        return "\n".join(lines)


COMMANDS = [HelpCommand, InboxCommand, TodoCommand, FindCommand, DbRebuildCommand, DbPurgeCommand]


class GTDHandler:
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
        return HelpCommand.usage()

    @classmethod
    def help(cls) -> str:
        return HelpCommand.help()

    def handle_message(self, message: Message, bot_handler: BotHandler) -> None:
        assert self.db
        client: zulip.Client = bot_handler._client  # type: ignore

        try:
            command = message["content"].partition(" ")[0]
            for cls in COMMANDS:
                if cls.META["command"] == command:
                    return cls(self.db).execute(message, client, bot_handler)

            bot_handler.send_reply(
                message,
                f"Sorry, command not recognized: `{message['content']}`. Try running `help`?",
            )
        except BaseException as e:
            bot_handler.send_reply(message, f"FATAL ERROR: ```{e}```")
            self.log.critical("Fatal error. Shutting down", error=e)
            raise


handler_class = GTDHandler
