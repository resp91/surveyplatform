"""도구 전역에서 쓰는 예외 정의."""


class BotError(Exception):
    """이 도구가 발생시키는 모든 오류의 기반 클래스."""


class ConfigError(BotError):
    """시나리오 파일이 잘못되었을 때."""


class ExcelError(BotError):
    """엑셀 파일을 읽을 수 없거나 지정한 열이 없을 때."""


class SecretError(BotError):
    """아이디/비밀번호 등 비밀값을 찾을 수 없을 때."""


class StepError(BotError):
    """실행 중 개별 단계가 실패했을 때."""

    def __init__(self, message: str, step_index: int | None = None, step_label: str | None = None):
        super().__init__(message)
        self.step_index = step_index
        self.step_label = step_label
