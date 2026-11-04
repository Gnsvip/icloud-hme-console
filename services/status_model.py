from enum import StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "active"
    WARNING = "warning"
    ERROR = "error"


class MailboxStatus(StrEnum):
    UNCALIBRATED = "uncalibrated"
    USED = "used"
    UNUSED_CHECKED = "unused_checked"
    TRASH = "trash"


class CodeStatus(StrEnum):
    UNCALIBRATED = "uncalibrated"
    USED = "used"
    UNUSED_CHECKED = "unused_checked"
    TRASH = "trash"


ACCOUNT_STATUSES = {s.value for s in AccountStatus}
MAILBOX_STATUSES = {s.value for s in MailboxStatus}
CODE_STATUSES = {s.value for s in CodeStatus}


def normalize_account_status(value: str) -> str:
    return value if value in ACCOUNT_STATUSES else AccountStatus.ERROR.value


def inventory_group_to_mailbox_status(group: str, checked: bool = False) -> str:
    if group == "trash":
        return MailboxStatus.TRASH.value
    if group == "finished":
        return MailboxStatus.USED.value
    return MailboxStatus.UNUSED_CHECKED.value if checked else MailboxStatus.UNCALIBRATED.value
