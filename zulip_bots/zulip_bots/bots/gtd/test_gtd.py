import tempfile

import pytest
from typing import Any, Iterable
from unittest.mock import Mock, patch

from zulip_bots.test_lib import BotTestCase, DefaultTests, StubBotHandler
from zulip_bots.bots.gtd.gtd import GTDHandler
from zulip_bots.bots.gtd.lib.model import DB, MODELS, Keygen
from zulip_bots.bots.gtd.lib.model import (
    ProjectList as ProjectListDB,
    Project as ProjectDB,
    Task as TaskDB,
    Context as ContextDB,
)
from zulip_bots.bots.gtd.lib.view import Project as ProjectView, Task as TaskView


@pytest.fixture(autouse=True)
def db_file() -> Any:
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        with patch(
            "zulip_bots.test_lib.StubBotHandler.get_config_info", return_value={"db_file": f.name}
        ):
            yield


class TestHelpBot(BotTestCase, DefaultTests):
    bot_name: str = "gtd"

    def _get_handlers(
        self,
        stream_id: int = 42,
        stream_ids: list[int] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> tuple[Any, StubBotHandler]:
        bot, bot_handler = super()._get_handlers()

        def _mock_add_subscriptions(
            streams: Iterable[dict[str, Any]], **kwargs: Any
        ) -> dict[str, Any]:
            bot_handler.transcript.append(
                ("add_subscriptions", dict(streams=streams, kwargs=kwargs))
            )
            return dict(result="success")

        def _mock_send_message(message: dict[str, Any]) -> dict[str, Any]:
            bot_handler.transcript.append(("send_message", dict(message)))
            result = bot_handler.message_server.send(message)
            result["result"] = "success"
            return result

        def _mock_update_message(message: dict[str, Any]) -> dict[str, Any]:
            bot_handler.transcript.append(("update_message", message))
            return dict(result="success")

        bot_handler._client = Mock()  # type: ignore

        if stream_ids:
            bot_handler._client.get_stream_id = Mock(side_effect=(dict(result="success", stream_id=stream_id) for stream_id in stream_ids))  # type: ignore
        else:
            bot_handler._client.get_stream_id = Mock(return_value=dict(result="success", stream_id=stream_id))  # type: ignore

        bot_handler._client.get_messages = Mock(return_value=dict(messages=messages or list(), result="success"))  # type: ignore
        bot_handler._client.update_message = _mock_update_message  # type: ignore
        bot_handler._client.add_subscriptions = _mock_add_subscriptions  # type: ignore
        bot_handler.send_message = _mock_send_message  # type: ignore
        return bot, bot_handler

    def make_request_message(
        self, content: str, type: str = "stream", subject: str = "foo_subject", **kwargs
    ) -> dict[str, Any]:
        message = super().make_request_message(content)
        message["type"] = type
        message["subject"] = subject
        message.update(kwargs)
        return message

    def get_transcript(
        self,
        request: str,
        request_kwargs: dict[str, Any] | None = None,
        handlers_kwargs: dict[str, Any] | None = None,
    ) -> tuple[Any, StubBotHandler, list[tuple[str, dict[str, Any]]]]:
        handlers_kwargs = handlers_kwargs or dict()
        request_kwargs = request_kwargs or dict()

        bot, bot_handler = self._get_handlers(**handlers_kwargs)

        message = self.make_request_message(request, **request_kwargs)
        bot_handler.reset_transcript()
        bot.handle_message(message, bot_handler)
        return bot, bot_handler, list(bot_handler.transcript)

    def test_it_should_give_help_messages(self) -> None:
        dialog = [
            ("help", GTDHandler.help()),
            ("foo", "Sorry, command not recognized: `foo`. Try running `help`?"),
        ]

        self.verify_dialog(dialog)

    def test_inbox_should_create_inbox_if_it_does_not_exist(self) -> None:
        _, bot_handler, transcript = self.get_transcript("inbox some task")
        assert dict(transcript)["add_subscriptions"]["streams"][0]["name"] == "Inbox"

    def test_inbox_should_link_a_new_message(self) -> None:
        _, _, transcript = self.get_transcript("inbox some task")
        assert len(transcript) == 3
        transcript_dict = dict(transcript)
        assert "add_subscriptions" in transcript_dict
        assert transcript_dict["send_message"]["subject"] == "some task"
        assert (
            transcript_dict["send_message"]["content"] == "Created from #**foo_stream>foo_subject**"
        )
        assert transcript_dict["send_reply"]["content"] == "Created #**Inbox>some task**"

    def test_todo_should_create_context_if_it_does_not_exist(self) -> None:
        _, bot_handler, transcript = self.get_transcript("todo #**@Laptop** some task")
        assert dict(transcript)["add_subscriptions"]["streams"][0]["name"] == "@Laptop"

    def test_todo_should_link_a_new_message(self) -> None:
        _, _, transcript = self.get_transcript("todo #**@Laptop** some task")
        assert len(transcript) == 3
        transcript_dict = dict(transcript)
        assert "add_subscriptions" in transcript_dict
        assert transcript_dict["send_message"]["subject"] == "some task"
        assert (
            transcript_dict["send_message"]["content"] == "Created from #**foo_stream>foo_subject**"
        )
        assert transcript_dict["send_reply"]["content"] == "Created #**@Laptop>some task**"

    def test_project_todo_should_put_hashids_in_titles(self) -> None:
        _, _, transcript = self.get_transcript(
            "todo #**@Laptop** some task",
            request_kwargs=dict(
                display_recipient="Projects.Some Project", stream_id=142, subject="Test out GTD bot"
            ),
            handlers_kwargs=dict(stream_ids=[242, 342], messages=[{"id": 442}]),
        )
        assert len(transcript) == 5

        command, args = transcript[0]
        assert command == "add_subscriptions"
        assert args["streams"][0]["name"] == "@Laptop"

        command, args = transcript[1]
        assert command == "update_message"
        assert args["message_id"] == 442
        proj_parts = ProjectView.parse_name(args["topic"])
        assert proj_parts
        assert proj_parts["topic"] == "Test out GTD bot"
        assert ProjectDB.get_by_id(Keygen.decode(proj_parts["project"]).id)  # type: ignore

        assert transcript[2][0] == "send_message"

        command, args = transcript[3]
        assert command == "update_message"
        parts = TaskView.parse_name(args["topic"])
        assert parts
        assert parts["project"] == proj_parts["project"]
        assert parts["topic"] == "some task"
        assert ProjectDB.get_by_id(Keygen.decode(parts["project"]).id)  # type: ignore

        assert transcript[4][0] == "send_reply"

    def test_project_todo_should_keep_hashids_in_titles(self) -> None:
        proj_list_hash = "VLVC9D"  # [L, 342]
        proj_hash = "YVX1VB"  # [P, 442]
        context_hash = "KXKSKP"  # [C, 242]

        project_subject = f"Test out GTD bot #{proj_list_hash}-{proj_hash}"

        _, _, transcript = self.get_transcript(
            "todo #**@Laptop** some task",
            request_kwargs=dict(
                display_recipient="Projects.Some Project", stream_id=142, subject=project_subject
            ),
            handlers_kwargs=dict(stream_ids=[242, 342], messages=[{"id": 442}]),
        )
