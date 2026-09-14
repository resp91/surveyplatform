"""시나리오의 각 action 을 실제 브라우저 동작으로 옮긴다."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Step
from .errors import StepError
from .templating import Context

logger = logging.getLogger(__name__)


class StepExecutor:
    """Playwright 페이지 위에서 단계를 실행한다.

    switch_frame 로 바뀐 프레임은 다음 switch_frame 까지 유지된다.
    """

    def __init__(self, page: Any, output_dir: Path, default_timeout_ms: int, secrets: Any):
        self.page = page
        self.output_dir = output_dir
        self.default_timeout_ms = default_timeout_ms
        self.secrets = secrets
        self._scope: Any = page          # locator 를 만들 대상(페이지 또는 프레임)
        self._dialog_handler_installed = False

    # ---------------------------------------------------------------- 실행
    def execute(self, step: Step, context: Context, step_index: int) -> None:
        params = context.render(step.params)
        timeout = step.timeout_ms or self.default_timeout_ms

        if step.skip_if_empty:
            probe = context.render("{{ " + step.skip_if_empty + " }}")
            if not str(probe).strip():
                logger.info("  [%02d] 건너뜀 (%s 값이 비어 있음): %s",
                            step_index + 1, step.skip_if_empty, step.describe())
                return

        handler = getattr(self, f"_do_{step.action}", None)
        if handler is None:  # config 검증을 통과했다면 여기 오지 않는다.
            raise StepError(f"구현되지 않은 action: {step.action}", step_index, step.describe())

        logger.info("  [%02d] %s", step_index + 1, self.secrets.mask(step.describe()))
        try:
            handler(params, timeout)
        except Exception as exc:
            message = self.secrets.mask(str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__)
            if step.optional:
                logger.warning("       선택 단계 실패, 계속 진행합니다: %s", message)
                return
            raise StepError(message, step_index, step.describe()) from exc

    # ------------------------------------------------------------ 공통 도구
    def _locator(self, params: dict[str, Any]) -> Any:
        locator = self._scope.locator(params["selector"])
        nth = params.get("nth")
        if nth is not None:
            locator = locator.nth(int(nth))
        else:
            # 같은 선택자가 여러 개 잡히면 첫 번째를 쓴다(사내 화면은 중복 id 가 흔하다).
            locator = locator.first
        return locator

    # -------------------------------------------------------------- 액션들
    def _do_goto(self, params: dict[str, Any], timeout: int) -> None:
        self._scope = self.page  # 페이지를 옮기면 프레임 선택은 초기화된다.
        self.page.goto(params["url"], timeout=timeout, wait_until=params.get("wait_until", "load"))

    def _do_click(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).click(
            timeout=timeout,
            force=bool(params.get("force", False)),
            button=params.get("button", "left"),
        )

    def _do_double_click(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).dblclick(timeout=timeout, force=bool(params.get("force", False)))

    def _do_fill(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).fill(str(params["value"]), timeout=timeout)

    def _do_type(self, params: dict[str, Any], timeout: int) -> None:
        locator = self._locator(params)
        if params.get("clear_first", True):
            locator.fill("", timeout=timeout)
        # 키 입력 이벤트에 반응하는 자동완성/검증 스크립트가 있는 칸에 쓴다.
        locator.press_sequentially(str(params["value"]), delay=int(params.get("delay_ms", 30)), timeout=timeout)

    def _do_paste(self, params: dict[str, Any], timeout: int) -> None:
        """실제 클립보드를 거쳐 붙여넣는다. 권한이 막히면 fill 로 대체한다."""
        locator = self._locator(params)
        value = str(params["value"])
        locator.click(timeout=timeout)
        if params.get("clear_first", True):
            locator.press("Control+a", timeout=timeout)
        try:
            self.page.evaluate("text => navigator.clipboard.writeText(text)", value)
            locator.press("Control+v", timeout=timeout)
        except Exception:
            logger.warning("       클립보드를 쓸 수 없어 직접 입력으로 대체합니다.")
            locator.fill(value, timeout=timeout)

    def _do_select_option(self, params: dict[str, Any], timeout: int) -> None:
        locator = self._locator(params)
        if params.get("option_label") is not None:
            locator.select_option(label=str(params["option_label"]), timeout=timeout)
        elif params.get("index") is not None:
            locator.select_option(index=int(params["index"]), timeout=timeout)
        else:
            locator.select_option(value=str(params.get("value", "")), timeout=timeout)

    def _do_check(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).check(timeout=timeout)

    def _do_uncheck(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).uncheck(timeout=timeout)

    def _do_press(self, params: dict[str, Any], timeout: int) -> None:
        if params.get("selector"):
            self._locator(params).press(params["key"], timeout=timeout)
        else:
            self.page.keyboard.press(params["key"])

    def _do_upload(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).set_input_files(params["path"], timeout=timeout)

    def _do_wait_for(self, params: dict[str, Any], timeout: int) -> None:
        self._locator(params).wait_for(state=params.get("state", "visible"), timeout=timeout)

    def _do_wait_for_text(self, params: dict[str, Any], timeout: int) -> None:
        scope = self._scope.locator(params["selector"]) if params.get("selector") else self._scope.locator("body")
        scope.first.get_by_text(str(params["text"]), exact=False).first.wait_for(
            state="visible", timeout=timeout
        )

    def _do_wait_for_url(self, params: dict[str, Any], timeout: int) -> None:
        self.page.wait_for_url(params["url"], timeout=timeout)

    def _do_wait(self, params: dict[str, Any], timeout: int) -> None:
        self.page.wait_for_timeout(int(params["ms"]))

    def _do_switch_frame(self, params: dict[str, Any], timeout: int) -> None:
        if params.get("selector"):
            self._scope = self.page.frame_locator(params["selector"])
        elif params.get("name"):
            frame = self.page.frame(name=params["name"])
            if frame is None:
                raise RuntimeError(f"'{params['name']}' 이름의 프레임을 찾지 못했습니다.")
            self._scope = frame
        elif params.get("url"):
            frame = self.page.frame(url=params["url"])
            if frame is None:
                raise RuntimeError(f"'{params['url']}' 주소의 프레임을 찾지 못했습니다.")
            self._scope = frame
        else:
            self._scope = self.page  # 인자가 없으면 최상위 문서로 복귀

    def _do_screenshot(self, params: dict[str, Any], timeout: int) -> None:
        target = params.get("path") or f"screenshot-{int(self.page.evaluate('Date.now()'))}.png"
        path = Path(target)
        if not path.is_absolute():
            path = self.output_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path), full_page=True)
        logger.info("       화면 저장: %s", path)

    def _do_assert_text(self, params: dict[str, Any], timeout: int) -> None:
        scope = self._scope.locator(params["selector"]) if params.get("selector") else self._scope.locator("body")
        content = scope.first.inner_text(timeout=timeout)
        if str(params["text"]) not in content:
            raise RuntimeError(f"화면에서 '{params['text']}' 를 찾지 못했습니다.")

    def _do_assert_visible(self, params: dict[str, Any], timeout: int) -> None:
        if not self._locator(params).is_visible(timeout=timeout):
            raise RuntimeError(f"'{params['selector']}' 가 보이지 않습니다.")

    def _do_handle_dialog(self, params: dict[str, Any], timeout: int) -> None:
        """이후 나타나는 alert/confirm 창을 자동 처리하도록 등록한다."""
        accept = bool(params.get("accept", True))
        prompt_text = params.get("prompt_text")

        def _on_dialog(dialog: Any) -> None:
            logger.info("       확인창 자동 처리(%s): %s", "확인" if accept else "취소", dialog.message)
            if accept:
                dialog.accept(prompt_text) if prompt_text is not None else dialog.accept()
            else:
                dialog.dismiss()

        if self._dialog_handler_installed:
            self.page.remove_listener("dialog", self._dialog_callback)
        self._dialog_callback = _on_dialog
        self.page.on("dialog", _on_dialog)
        self._dialog_handler_installed = True
