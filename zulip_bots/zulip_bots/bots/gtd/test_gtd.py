from zulip_bots.test_lib import BotTestCase, DefaultTests, StubBotHandler
from zulip_bots.bots.gtd.gtd import GTDHandler
from typing import Any
from unittest.mock import Mock


class TestHelpBot(BotTestCase, DefaultTests):
    bot_name: str = "gtd"

    def _get_handlers(self) -> tuple[Any, StubBotHandler]:
        bot, bot_handler = super()._get_handlers()
        bot_handler._client = Mock()
        return bot, bot_handler

    def make_request_message(
        self, content: str, type: str = "stream", subject: str = "foo_subject"
    ) -> dict[str, Any]:
        message = super().make_request_message(content)
        message["type"] = type
        message["subject"] = subject
        return message

    def get_transcript(self, request: str) -> tuple[Any, StubBotHandler, dict[str, Any]]:
        bot, bot_handler = self._get_handlers()
        message = self.make_request_message(request)
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
        _, bot_handler, _ = self.get_transcript("inbox some task")
        args, kwargs = bot_handler._client.add_subscriptions.call_args
        assert kwargs["streams"][0]["name"] == "Inbox"

    def test_inbox_should_link_a_new_message(self) -> None:
        _, _, transcript = self.get_transcript("inbox some task")
        assert len(transcript) == 2
        transcript_dict = dict(transcript)
        assert transcript_dict["send_message"]["subject"] == "some task"
        assert (
            transcript_dict["send_message"]["content"] == "Created from #**foo_stream>foo_subject"
        )
        assert transcript_dict["send_reply"]["content"] == "Created #**@Laptop>some task**"

    def test_todo_should_create_context_if_it_does_not_exist(self) -> None:
        _, bot_handler, _ = self.get_transcript("todo #**@Laptop** some task")
        args, kwargs = bot_handler._client.add_subscriptions.call_args
        assert kwargs["streams"][0]["name"] == "@Laptop"

    def test_inbox_should_link_a_new_message(self) -> None:
        _, _, transcript = self.get_transcript("todo #**@Laptop** some task")
        assert len(transcript) == 2
        transcript_dict = dict(transcript)
        assert transcript_dict["send_message"]["subject"] == "some task"
        assert (
            transcript_dict["send_message"]["content"] == "Created from #**foo_stream>foo_subject"
        )
        assert transcript_dict["send_reply"]["content"] == "Created #**@Laptop>some task**"
