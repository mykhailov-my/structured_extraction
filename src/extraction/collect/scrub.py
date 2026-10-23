"""Removes contact details from collected texts: the repository is public and the homework's
data must hold no personal data. Emails, phone numbers, links and @handles are replaced, and
so are a messenger username without the "@" ("пишіть в телеграм ivan_hr") and the name in a
self-introduction ("Меня зовут Елена"). Other names in free text are not detected, so read
the texts before committing them."""

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Up to trailing punctuation, so "see t.me/hr_bot." keeps its full stop.
_LINK = re.compile(r"(?:https?://|www\.|t\.me/)\S+?(?=[.,;:!?)\]]*(?:\s|$))", re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z]\w{3,}")
# A username right after "в телеграм", "on Telegram:"; not "in Telegram bots".
_MESSENGER_NAME = re.compile(
    r"(?i)\b((?:в|у|на|in|on|via|через)\s+(?:telegram|телеграм\w*|viber|signal|whatsapp)\s*:?\s+)"
    r"(?!(?:bots?|channels?|groups?|chats?|api|apps?|mini|ads|premium)\b)[A-Za-z][\w.]{3,31}\b"
)
_INTRODUCTION = re.compile(
    r"\b((?i:my name is|мене звати|меня зовут)\s+)[A-ZА-ЯІЇЄҐ][\w'’-]+(?:\s+[A-ZА-ЯІЇЄҐ][\w'’-]+)?"
)
_NUMBER_RUN = re.compile(r"\+?\d[\d \t().-]{7,}\d")


def scrub(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _LINK.sub("[link]", text)
    text = _HANDLE.sub("[handle]", text)
    text = _MESSENGER_NAME.sub(r"\1[handle]", text)
    text = _INTRODUCTION.sub(r"\1[name]", text)
    return _NUMBER_RUN.sub(_phone, text)


def _phone(match: re.Match[str]) -> str:
    # 10-13 digits looks like a phone; salary ranges and year spans have 8 or 16.
    digits = sum(char.isdigit() for char in match.group())
    return "[phone]" if 10 <= digits <= 13 else match.group()
