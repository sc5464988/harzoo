"""Native Playwright browser automation tool with ref-based actions."""


from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

_BROWSER_ACTIONS = [
    "session_start",
    "session_close",
    "navigate",
    "back",
    "forward",
    "reload",
    "snapshot",
    "click_ref",
    "type_ref",
    "fill_ref",
    "press_key",
    "select_ref",
    "check_ref",
    "uncheck_ref",
    "scroll_ref",
    "scroll_page",
    "wait",
    "extract",
    "tab_list",
    "tab_new",
    "tab_switch",
    "tab_close",
    "upload_ref",
    "screenshot",
]

_MANUAL_TAKEOVER_KEYWORDS = (
    "captcha",
    "verify you are human",
    "verification code",
    "one-time code",
    "scan qr",
    "scan the qr",
    "sms code",
    "2fa",
    "two-factor",
    "security check",
    "human verification",
    "manual review",
)

# session_start with default chromium: try channels in this order before giving up.
_DEFAULT_SESSION_CHROMIUM_CHANNELS: tuple[str, ...] = ("msedge", "chrome", "chromium")


def _text_arg_for_input_actions(kwargs: dict[str, Any]) -> str:
    """Models often pass `value` instead of `text` for fill_ref/type_ref; accept both."""
    t = kwargs.get("text")
    if t is not None and str(t).strip() != "":
        return str(t)
    v = kwargs.get("value")
    if v is not None and str(v).strip() != "":
        return str(v)
    if t is not None:
        return str(t)
    return ""


class BrowserRuntime:
    """单会话浏览器运行时，封装 Playwright 生命周期与页面状态。"""

    def __init__(
        self,
        *,
        headed: bool = True,
        browser_name: str = "chromium",
        timeout_ms: int = 15000,
        persistent_profile: bool = True,
        profile_dir: str | None = None,
        browser_channel: str | None = None,
    ) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._snapshot_id = ""
        self._ref_elements: dict[str, Any] = {}
        self._snapshot_elements: list[dict[str, Any]] = []
        self._default_timeout_ms = int(timeout_ms)
        self._headed = bool(headed)
        self._browser_name = str(browser_name or "chromium").strip().lower()
        self._persistent_profile = bool(persistent_profile)
        self._profile_dir = str(profile_dir).strip() if profile_dir else None
        self._browser_channel = str(browser_channel).strip().lower() if browser_channel else None
        self._last_action_ts = 0.0
        self._init_playwright()

    @classmethod
    def create(
        cls,
        *,
        headed: bool = True,
        browser_name: str = "chromium",
        timeout_ms: int = 15000,
        persistent_profile: bool = True,
        profile_dir: str | None = None,
        browser_channel: str | None = None,
    ) -> BrowserRuntime:
        return cls(
            headed=headed,
            browser_name=browser_name,
            timeout_ms=timeout_ms,
            persistent_profile=persistent_profile,
            profile_dir=profile_dir,
            browser_channel=browser_channel,
        )

    def _init_playwright(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:
            raise RuntimeError("Playwright is required for Browser. Install with: pip install playwright && playwright install") from e

        self._pw = sync_playwright().start()
        try:
            launch_target = getattr(self._pw, self._browser_name, None) or self._pw.chromium
            launch_options = {"headless": not self._headed}
            if self._headed:
                launch_options["no_viewport"] = True
            if self._browser_name == "chromium" and self._browser_channel:
                launch_options["channel"] = self._browser_channel

            if self._persistent_profile:
                if self._profile_dir:
                    profile_path = Path(self._profile_dir).expanduser().resolve()
                else:
                    profile_path = Path(tempfile.mkdtemp(prefix="browser_profile_")).resolve()
                profile_path.mkdir(parents=True, exist_ok=True)
                self._profile_dir = str(profile_path)
                self._context = launch_target.launch_persistent_context(
                    user_data_dir=str(profile_path),
                    **launch_options,
                )
                pages = self._context.pages
                self._page = pages[0] if pages else self._context.new_page()
            else:
                self._browser = launch_target.launch(**launch_options)
                self._context = self._browser.new_context()
                self._page = self._context.new_page()

            self._context.set_default_timeout(self._default_timeout_ms)
        except Exception:
            # Cleanup partially initialized Playwright resources so fallback
            # channel attempts can start fresh.
            for obj, close_name in (
                (self._context, "close"),
                (self._browser, "close"),
                (self._pw, "stop"),
            ):
                if obj is None:
                    continue
                try:
                    getattr(obj, close_name)()
                except Exception:
                    pass
            self._context = None
            self._browser = None
            self._pw = None
            self._page = None
            raise

    def close(self) -> None:
        errs = []
        for obj, close_name in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ):
            if obj is None:
                continue
            try:
                getattr(obj, close_name)()
            except Exception as e:
                errs.append(str(e))
        self._context = None
        self._browser = None
        self._pw = None
        self._page = None
        self._ref_elements.clear()
        if errs:
            raise RuntimeError("; ".join(errs))

    def _ensure_page(self) -> Any:
        if self._page is None:
            raise RuntimeError("Browser session is not initialized")
        return self._page

    def _set_active_page(self, page: Any) -> None:
        self._page = page

    def _serialize_page_state(self) -> dict[str, Any]:
        page = self._ensure_page()
        return {
            "url": page.url,
            "title": page.title(),
        }

    def runtime_meta(self) -> dict[str, Any]:
        mode = "persistent_profile" if self._persistent_profile else "ephemeral"
        return {
            "mode": mode,
            "profile_dir": self._profile_dir,
            "browser_name": self._browser_name,
            "browser_channel": self._browser_channel,
            "headed": self._headed,
        }

    def _build_snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        page = self._ensure_page()
        handles = page.query_selector_all("a[href], button, input, textarea, select, summary, [role], [contenteditable='true'], [tabindex]")

        refs = {}
        elements = []
        for handle in handles:
            try:
                visible = bool(handle.is_visible())
            except Exception:
                visible = False
            if not visible:
                continue
            try:
                payload = handle.evaluate("""(el) => {
                        const roleRaw = el.getAttribute("role");
                        const tag = (el.tagName || "").toLowerCase();
                        const role = roleRaw || (
                            tag === "a" ? "link" :
                            tag === "button" ? "button" :
                            tag === "input" || tag === "textarea" ? "textbox" :
                            tag === "select" ? "combobox" :
                            ""
                        );
                        const name = (
                            el.getAttribute("aria-label")
                            || el.getAttribute("name")
                            || el.getAttribute("placeholder")
                            || (el.innerText || "").trim()
                            || (el.textContent || "").trim()
                            || ""
                        ).slice(0, 120);
                        const text = ((el.innerText || el.textContent || "").trim()).slice(0, 200);
                        const inputLike = ["input", "textarea", "select"].includes(tag);
                        const editable = el.isContentEditable || inputLike;
                        const disabled = !!(el.disabled || el.getAttribute("aria-disabled") === "true");
                        return {
                            role: role || "generic",
                            tag,
                            name,
                            text,
                            enabled: !disabled,
                            editable,
                        };
                    }""")
            except Exception:
                continue

            ref = f"e{len(elements) + 1}"
            refs[ref] = handle
            elements.append(
                {
                    "ref": ref,
                    "role": str(payload.get("role", "generic")),
                    "tag": str(payload.get("tag", "")),
                    "name": str(payload.get("name", "")),
                    "text": str(payload.get("text", "")),
                    "visible": True,
                    "enabled": bool(payload.get("enabled", True)),
                    "editable": bool(payload.get("editable", False)),
                }
            )
            if len(elements) >= max(1, int(limit)):
                break

        self._ref_elements = refs
        self._snapshot_elements = elements
        self._snapshot_id = f"snap_{int(time.time() * 1000)}"
        state = self._serialize_page_state()
        return {
            "snapshot_id": self._snapshot_id,
            "page": state,
            "elements": elements,
        }

    def _pace_actions(self, *, min_action_interval_ms: int = 140) -> None:
        interval_ms = max(0, int(min_action_interval_ms))
        if interval_ms == 0:
            self._last_action_ts = time.time()
            return
        now = time.time()
        elapsed_ms = (now - self._last_action_ts) * 1000.0
        if elapsed_ms < interval_ms:
            time.sleep((interval_ms - elapsed_ms) / 1000.0)
        self._last_action_ts = time.time()

    def _is_retryable_error(self, err: Exception) -> bool:
        name = type(err).__name__.lower()
        msg = str(err).lower()
        if "timeout" in name:
            return True
        retryable_markers = (
            "timeout",
            "element is not attached",
            "execution context was destroyed",
            "target closed",
            "navigation",
            "another element",
            "intercept",
            "detached",
            "not visible",
            "not stable",
        )
        return any(marker in msg for marker in retryable_markers)

    def _recover_after_failure(self, *, backoff_ms: int = 300) -> None:
        page = self._ensure_page()
        page.wait_for_timeout(max(60, int(backoff_ms)))
        try:
            page.wait_for_load_state("domcontentloaded", timeout=max(600, int(backoff_ms) * 4))
        except Exception:
            # Recovery is best-effort; keep original action error for callers.
            pass

    def _run_with_retries(
        self,
        fn: Any,
        *,
        retry_count: int = 1,
        retry_backoff_ms: int = 300,
        min_action_interval_ms: int = 140,
    ) -> Any:
        attempts = 1 + max(0, int(retry_count))
        last_error = None
        for idx in range(attempts):
            self._pace_actions(min_action_interval_ms=min_action_interval_ms)
            try:
                return fn()
            except Exception as err:  # noqa: BLE001
                last_error = err
                should_retry = idx < attempts - 1 and self._is_retryable_error(err)
                if not should_retry:
                    raise
                self._recover_after_failure(backoff_ms=max(60, int(retry_backoff_ms) * (idx + 1)))
        if last_error is not None:
            raise last_error
        raise RuntimeError("Browser action failed without explicit error")

    def _settle_after_action(self, *, settle_ms: int = 220, prefer_network_idle: bool = False) -> None:
        page = self._ensure_page()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=1800)
        except Exception:
            pass
        if prefer_network_idle:
            try:
                page.wait_for_load_state("networkidle", timeout=1500)
            except Exception:
                pass
        stable_wait = max(0, int(settle_ms))
        if stable_wait > 0:
            page.wait_for_timeout(stable_wait)

    def _prepare_interaction_target(self, handle: Any) -> None:
        handle.scroll_into_view_if_needed()
        try:
            handle.wait_for_element_state("visible", timeout=2000)
        except Exception as e:
            raise RuntimeError(f"Target element is not visible: {e}") from e
        try:
            handle.wait_for_element_state("stable", timeout=1500)
        except Exception:
            # Not all pages/elements can reach strict "stable"; proceed cautiously.
            pass
        try:
            handle.wait_for_element_state("enabled", timeout=1200)
        except Exception as e:
            raise RuntimeError(f"Target element is disabled: {e}") from e

    def detect_manual_takeover(self) -> dict[str, Any] | None:
        page = self._ensure_page()
        try:
            text_hint = page.evaluate("""() => {
                    const t = document?.body?.innerText || "";
                    return t.slice(0, 6000);
                }""")
        except Exception:
            text_hint = ""
        base = f"{page.url}\n{page.title()}\n{text_hint}".lower()
        hits = [kw for kw in _MANUAL_TAKEOVER_KEYWORDS if kw in base]
        if not hits:
            return None
        return {
            "required": True,
            "reason": "Detected verification/safety challenge. Manual user takeover is required.",
            "signals": hits[:4],
        }

    def _resolve_ref(self, ref: str) -> Any:
        key = str(ref).strip()
        handle = self._ref_elements.get(key)
        if handle is None:
            raise ValueError(f"Unknown ref: {key}. Call snapshot first.")
        return handle

    def _auto_snapshot(self, enabled: bool, limit: int) -> dict[str, Any] | None:
        if not enabled:
            return None
        return self._build_snapshot(limit=limit)

    def navigate(
        self,
        *,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30000,
        retry_count: int = 1,
        retry_backoff_ms: int = 350,
        settle_ms: int = 260,
    ) -> dict[str, Any]:
        page = self._ensure_page()
        self._run_with_retries(
            lambda: page.goto(url, wait_until=wait_until, timeout=timeout_ms),
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms, prefer_network_idle=True)
        return self._serialize_page_state()

    def back(self, *, retry_count: int = 1, retry_backoff_ms: int = 260, settle_ms: int = 220) -> dict[str, Any]:
        page = self._ensure_page()
        self._run_with_retries(
            page.go_back,
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms)
        return self._serialize_page_state()

    def forward(self, *, retry_count: int = 1, retry_backoff_ms: int = 260, settle_ms: int = 220) -> dict[str, Any]:
        page = self._ensure_page()
        self._run_with_retries(
            page.go_forward,
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms)
        return self._serialize_page_state()

    def reload(self, *, retry_count: int = 1, retry_backoff_ms: int = 260, settle_ms: int = 260) -> dict[str, Any]:
        page = self._ensure_page()
        self._run_with_retries(
            page.reload,
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms, prefer_network_idle=True)
        return self._serialize_page_state()

    def click_ref(
        self,
        *,
        ref: str,
        retry_count: int = 1,
        retry_backoff_ms: int = 260,
        settle_ms: int = 180,
    ) -> None:
        handle = self._resolve_ref(ref)
        self._run_with_retries(
            lambda: self._click_handle(handle),
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms)

    def _click_handle(self, handle: Any) -> None:
        self._prepare_interaction_target(handle)
        try:
            handle.click(trial=True, timeout=1500)
        except Exception:
            pass
        handle.click()

    def type_ref(
        self,
        *,
        ref: str,
        text: str,
        submit: bool = False,
        delay_ms: int = 0,
        retry_count: int = 1,
        retry_backoff_ms: int = 260,
        settle_ms: int = 180,
    ) -> None:
        handle = self._resolve_ref(ref)
        self._run_with_retries(
            lambda: self._type_handle(handle, text=str(text), submit=submit, delay_ms=delay_ms),
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms)

    def _type_handle(self, handle: Any, *, text: str, submit: bool, delay_ms: int) -> None:
        self._prepare_interaction_target(handle)
        handle.click()
        handle.type(str(text), delay=max(0, int(delay_ms)))
        if submit:
            handle.press("Enter")

    def fill_ref(
        self,
        *,
        ref: str,
        text: str,
        submit: bool = False,
        retry_count: int = 1,
        retry_backoff_ms: int = 260,
        settle_ms: int = 180,
    ) -> None:
        handle = self._resolve_ref(ref)
        self._run_with_retries(
            lambda: self._fill_handle(handle, text=str(text), submit=submit),
            retry_count=retry_count,
            retry_backoff_ms=retry_backoff_ms,
        )
        self._settle_after_action(settle_ms=settle_ms)

    def _element_prefers_keyboard_fill(self, handle: Any) -> bool:
        """Use click + type for SPA/contenteditable; keep native fill for select etc."""
        return bool(handle.evaluate("""(el) => {
                    const t = (el.tagName || "").toLowerCase();
                    if (t === "select") return false;
                    if (t === "textarea") return true;
                    if (el.isContentEditable) return true;
                    if (t !== "input") return false;
                    const typ = (el.getAttribute("type") || "text").toLowerCase();
                    return !["button","submit","reset","checkbox","radio","file","hidden","image"].includes(typ);
                }"""))

    def _fill_handle(self, handle: Any, *, text: str, submit: bool) -> None:
        self._prepare_interaction_target(handle)
        if not self._element_prefers_keyboard_fill(handle):
            handle.fill(str(text))
        else:
            handle.click()
            try:
                handle.fill("")
            except Exception:
                try:
                    handle.evaluate("""(el) => {
                            if (el.isContentEditable) {
                                el.textContent = "";
                            } else {
                                el.value = "";
                            }
                            el.dispatchEvent(new Event("input", { bubbles: true }));
                            el.dispatchEvent(new Event("change", { bubbles: true }));
                        }""")
                except Exception:
                    pass
            handle.type(str(text), delay=0)
        if submit:
            handle.press("Enter")

    def press_key(self, *, key: str) -> None:
        page = self._ensure_page()
        page.keyboard.press(str(key))

    def select_ref(
        self,
        *,
        ref: str,
        value: str | None = None,
        label: str | None = None,
        retry_count: int = 1,
        retry_backoff_ms: int = 260,
        settle_ms: int = 180,
    ) -> Any:
        handle = self._resolve_ref(ref)
        if label:
            result = self._run_with_retries(
                lambda: handle.select_option(label=str(label)),
                retry_count=retry_count,
                retry_backoff_ms=retry_backoff_ms,
            )
            self._settle_after_action(settle_ms=settle_ms)
            return result
        if value is not None:
            result = self._run_with_retries(
                lambda: handle.select_option(value=str(value)),
                retry_count=retry_count,
                retry_backoff_ms=retry_backoff_ms,
            )
            self._settle_after_action(settle_ms=settle_ms)
            return result
        raise ValueError("select_ref requires value or label")

    def check_ref(
        self,
        *,
        ref: str,
        retry_count: int = 1,
        retry_backoff_ms: int = 260,
        settle_ms: int = 150,
    ) -> None:
        handle = self._resolve_ref(ref)
        self._run_with_retries(handle.check, retry_count=retry_count, retry_backoff_ms=retry_backoff_ms)
        self._settle_after_action(settle_ms=settle_ms)

    def uncheck_ref(
        self,
        *,
        ref: str,
        retry_count: int = 1,
        retry_backoff_ms: int = 260,
        settle_ms: int = 150,
    ) -> None:
        handle = self._resolve_ref(ref)
        self._run_with_retries(handle.uncheck, retry_count=retry_count, retry_backoff_ms=retry_backoff_ms)
        self._settle_after_action(settle_ms=settle_ms)

    def scroll_ref(self, *, ref: str, amount: int = 500) -> None:
        handle = self._resolve_ref(ref)
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box() or {"x": 0, "y": 0, "width": 1, "height": 1}
        page = self._ensure_page()
        page.mouse.move(float(box["x"]) + float(box["width"]) / 2.0, float(box["y"]) + float(box["height"]) / 2.0)
        page.mouse.wheel(0, int(amount))

    def scroll_page(self, *, amount: int = 700) -> None:
        self._ensure_page().mouse.wheel(0, int(amount))

    def wait(
        self,
        *,
        wait_for: str = "timeout",
        value: str | None = None,
        timeout_ms: int = 10000,
        load_state: str = "domcontentloaded",
        settle_ms: int = 220,
    ) -> None:
        page = self._ensure_page()
        w = str(wait_for).strip().lower()
        if w == "timeout":
            page.wait_for_timeout(timeout_ms)
            return
        if w == "text":
            if not value:
                raise ValueError("wait_for=text requires value")
            page.get_by_text(str(value)).first.wait_for(timeout=timeout_ms)
            return
        if w == "selector":
            if not value:
                raise ValueError("wait_for=selector requires value")
            page.locator(str(value)).first.wait_for(timeout=timeout_ms)
            return
        if w == "load_state":
            page.wait_for_load_state(load_state, timeout=timeout_ms)
            return
        if w == "stable":
            try:
                page.wait_for_load_state(load_state, timeout=timeout_ms)
            except Exception:
                pass
            # Short "quiet window" to reduce page jitter before next action.
            page.wait_for_timeout(max(50, int(settle_ms)))
            return
        raise ValueError(f"Unsupported wait_for: {wait_for}")

    def extract(
        self,
        *,
        mode: str = "text",
        ref: str | None = None,
        selector: str | None = None,
        attribute: str | None = None,
    ) -> dict[str, Any]:
        page = self._ensure_page()
        target = None
        if ref:
            target = self._resolve_ref(ref)
        elif selector:
            target = page.locator(str(selector)).first

        m = str(mode).strip().lower()
        if m == "text":
            value = target.inner_text() if target is not None else page.inner_text("body")
            return {"mode": "text", "value": value}
        if m == "html":
            if target is not None:
                value = target.inner_html()
            else:
                value = page.content()
            return {"mode": "html", "value": value}
        if m == "attribute":
            if target is None:
                raise ValueError("extract mode=attribute requires ref or selector")
            if not attribute:
                raise ValueError("extract mode=attribute requires attribute")
            value = target.get_attribute(str(attribute))
            return {"mode": "attribute", "attribute": attribute, "value": value}
        raise ValueError(f"Unsupported extract mode: {mode}")

    def tabs(self) -> list[dict[str, Any]]:
        if self._context is None:
            return []
        out = []
        active = self._ensure_page()
        for idx, p in enumerate(self._context.pages):
            out.append(
                {
                    "tab_id": f"tab_{idx + 1}",
                    "index": idx,
                    "url": p.url,
                    "title": p.title(),
                    "active": p == active,
                }
            )
        return out

    def tab_new(self, *, url: str | None = None) -> dict[str, Any]:
        if self._context is None:
            raise RuntimeError("Browser context missing")
        page = self._context.new_page()
        self._set_active_page(page)
        if url:
            page.goto(url)
        return self._serialize_page_state()

    def tab_switch(self, *, tab_id: str | None = None, index: int | None = None) -> dict[str, Any]:
        if self._context is None:
            raise RuntimeError("Browser context missing")
        idx = index
        if idx is None and tab_id:
            tid = str(tab_id).strip().lower()
            if not tid.startswith("tab_"):
                raise ValueError("tab_id format must be tab_N")
            idx = int(tid.split("_", 1)[1]) - 1
        if idx is None:
            raise ValueError("tab_switch requires tab_id or index")
        if idx < 0 or idx >= len(self._context.pages):
            raise ValueError(f"Tab index out of range: {idx}")
        page = self._context.pages[idx]
        self._set_active_page(page)
        page.bring_to_front()
        return self._serialize_page_state()

    def tab_close(self, *, tab_id: str | None = None, index: int | None = None) -> dict[str, Any]:
        if self._context is None:
            raise RuntimeError("Browser context missing")
        idx = index
        if idx is None and tab_id:
            tid = str(tab_id).strip().lower()
            if not tid.startswith("tab_"):
                raise ValueError("tab_id format must be tab_N")
            idx = int(tid.split("_", 1)[1]) - 1
        if idx is None:
            page = self._ensure_page()
        else:
            if idx < 0 or idx >= len(self._context.pages):
                raise ValueError(f"Tab index out of range: {idx}")
            page = self._context.pages[idx]
        page.close()
        pages = self._context.pages
        if not pages:
            self._set_active_page(self._context.new_page())
        else:
            self._set_active_page(pages[0])
        return self._serialize_page_state()

    def upload_ref(self, *, ref: str, file_paths: list[str]) -> None:
        if not file_paths:
            raise ValueError("upload_ref requires file_paths")
        paths = [str(Path(p).expanduser().resolve()) for p in file_paths]
        self._resolve_ref(ref).set_input_files(paths)

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> dict[str, Any]:
        page = self._ensure_page()
        if path:
            output_path = Path(path).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            tmpdir = Path(tempfile.mkdtemp(prefix="browser_"))
            output_path = tmpdir / f"screenshot_{int(time.time() * 1000)}.png"
        page.screenshot(path=str(output_path), full_page=bool(full_page))
        return {"path": str(output_path), "full_page": bool(full_page)}


class BrowserTool(Tool):
    """浏览器自动化工具，适合需要点击/输入/页面导航的网页任务。"""

    name = "Browser"
    danger_level = 1
    description = (
        "Native Playwright web automation with snapshot/ref actions for deterministic "
        "LLM-driven browser control. "
        "Convention: treat 'open this site' / 'go to URL' as action=navigate with a full url "
        "when the session already exists (including after session_start returns already_started). "
        "Use session_close then session_start only for a fresh browser, a dead session, after the "
        "user closed the automation window, or when the user asks to reset the session—not to "
        "re-open the same site inside an existing session."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": _BROWSER_ACTIONS,
                "description": ("Open a website = navigate with url once session exists. " "session_close+session_start only for fresh browser or reset."),
            },
            "session": {"type": "string", "description": "Session id, default: default"},
            "headed": {"type": "boolean"},
            "browser_name": {"type": "string", "enum": ["chromium", "webkit"]},
            "browser_channel": {
                "type": "string",
                "description": ("Chromium channel when set (chrome, msedge, chromium). " "If omitted on session_start, order is: msedge, chrome, bundled chromium."),
            },
            "timeout_ms": {"type": "integer"},
            "persistent_profile": {"type": "boolean", "description": "Use persistent profile browser context"},
            "profile_dir": {"type": "string", "description": "Persistent profile directory"},
            "url": {"type": "string"},
            "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle", "commit"]},
            "limit": {"type": "integer", "description": "Snapshot element limit"},
            "ref": {"type": "string"},
            "text": {
                "type": "string",
                "description": "For type_ref/fill_ref: text to enter; if empty, `value` is used as an alias.",
            },
            "submit": {"type": "boolean"},
            "delay_ms": {"type": "integer"},
            "key": {"type": "string"},
            "value": {
                "type": "string",
                "description": "For extract/select_ref etc.; for type_ref/fill_ref, alias when `text` is empty.",
            },
            "label": {"type": "string"},
            "amount": {"type": "integer"},
            "wait_for": {"type": "string", "enum": ["timeout", "text", "selector", "load_state", "stable"]},
            "load_state": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle", "commit"]},
            "retry_count": {"type": "integer", "description": "Transient failure retry count for interactive actions"},
            "retry_backoff_ms": {"type": "integer", "description": "Backoff between retries in milliseconds"},
            "settle_ms": {"type": "integer", "description": "Quiet settle delay after actions"},
            "manual_takeover_check": {"type": "boolean", "description": "Detect verification/captcha and signal manual takeover"},
            "mode": {"type": "string", "enum": ["text", "html", "attribute"]},
            "selector": {"type": "string"},
            "attribute": {"type": "string"},
            "tab_id": {"type": "string"},
            "index": {"type": "integer"},
            "file_paths": {"type": "array", "items": {"type": "string"}},
            "path": {"type": "string"},
            "full_page": {"type": "boolean"},
            "auto_snapshot": {"type": "boolean"},
        },
        "required": ["action"],
    }
    risk_level = "high"
    side_effect = True
    idempotent = False

    _runtimes: dict[str, BrowserRuntime] = {}

    def _get_session_id(self, session: str | None) -> str:
        sid = str(session or "default").strip()
        return sid or "default"

    @classmethod
    def _close_session(cls, sid: str) -> None:
        rt = cls._runtimes.pop(sid, None)
        if rt is None:
            return
        rt.close()

    @classmethod
    def _runtime_for(cls, sid: str) -> BrowserRuntime:
        rt = cls._runtimes.get(sid)
        if rt is None:
            raise ValueError(f"Session not found: {sid}. Call action=session_start first.")
        return rt

    def _check_session_start_capability(self, *, headed: bool) -> ToolResult | None:
        """session_start 前置能力检查，优先返回可行动的失败信息。"""

        if headed and sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return ToolResult.failure(
                "Headed browser session is unavailable on Linux (missing DISPLAY/WAYLAND_DISPLAY).",
                code="CAPABILITY_UNAVAILABLE",
                data={
                    "next_actions": [
                        "Set headed=false for server/headless environments.",
                        "Or run in a desktop session with DISPLAY/WAYLAND_DISPLAY.",
                    ]
                },
            )
        return None

    def _classify_session_start_failures(self, launch_errors: list[str]) -> tuple[str, list[str]]:
        """把浏览器启动失败归类到统一错误码，并提供下一步建议。"""

        lower = " | ".join(launch_errors).lower()
        if "playwright is required" in lower or ("no module named" in lower and "playwright" in lower):
            return "MISSING_DEPENDENCY", ["Install Playwright: pip install playwright", "Install browser binaries: playwright install"]
        if "executable doesn't exist" in lower or "please run the following command" in lower:
            return "MISSING_DEPENDENCY", ["Install browser binaries: playwright install", "If restricted network, install browsers in advance."]
        if "missing display" in lower or "xserver" in lower or "headful" in lower:
            return "CAPABILITY_UNAVAILABLE", ["Set headed=false for headless environments.", "Or run in desktop session with DISPLAY/WAYLAND_DISPLAY."]
        return "ACTION_EXECUTION_FAILED", ["Retry with action=session_start and headed=false.", "If issue persists, run playwright install and retry."]

    def execute(self, action: str, **kwargs: Any) -> ToolResult:
        a = str(action or "").strip().lower()
        sid = self._get_session_id(kwargs.get("session"))
        auto_snapshot = bool(kwargs.get("auto_snapshot", True))
        snapshot_limit = int(kwargs.get("limit", 200))
        retry_count = max(0, int(kwargs.get("retry_count", 1)))
        retry_backoff_ms = max(0, int(kwargs.get("retry_backoff_ms", 260)))
        settle_ms = max(0, int(kwargs.get("settle_ms", 220)))
        manual_takeover_check = bool(kwargs.get("manual_takeover_check", True))
        try:
            if a == "session_start":
                if sid in self._runtimes:
                    return ToolResult.success(
                        {
                            "session": sid,
                            "status": "already_started",
                            "hint": (
                                "Session is active in memory only; the target page is not opened by this call. "
                                "Use action=navigate with a full url to open a site. "
                                "Use session_close then session_start only when you need a fresh browser or reset."
                            ),
                        }
                    )
                profile_dir = kwargs.get("profile_dir")
                persistent_pf = bool(kwargs.get("persistent_profile", True))
                if persistent_pf and not profile_dir:
                    profile_dir = str((Path.cwd() / ".browser_profiles" / sid).resolve())
                browser_channel = kwargs.get("browser_channel")
                browser_name_normalized = str(kwargs.get("browser_name", "chromium")).strip().lower()
                explicit_channel = browser_channel is not None and str(browser_channel).strip() != ""

                rt = None
                launch_errors = []
                launch_fallbacks_tried = []
                headed = bool(kwargs.get("headed", True))
                timeout_ms = int(kwargs.get("timeout_ms", 15000))

                capability_error = self._check_session_start_capability(headed=headed)
                if capability_error is not None:
                    return capability_error

                if browser_name_normalized == "chromium" and not explicit_channel:
                    channels = _DEFAULT_SESSION_CHROMIUM_CHANNELS
                elif browser_name_normalized == "chromium":
                    channels = (str(browser_channel).strip().lower(),)
                else:
                    channels = (str(browser_channel).strip().lower(),) if explicit_channel else (None,)

                for ch in channels:
                    label = f"{browser_name_normalized}:{ch or 'bundled'}"
                    launch_fallbacks_tried.append(label)
                    try:
                        rt = BrowserRuntime.create(
                            headed=headed,
                            browser_name=browser_name_normalized,
                            timeout_ms=timeout_ms,
                            persistent_profile=persistent_pf,
                            profile_dir=profile_dir,
                            browser_channel=ch,
                        )
                        break
                    except Exception as e:  # noqa: BLE001
                        launch_errors.append(f"{label} -> {type(e).__name__}: {e}")

                if rt is None:
                    code, next_actions = self._classify_session_start_failures(launch_errors)
                    return ToolResult.failure(
                        "session_start failed. " + " | ".join(launch_errors[-6:]),
                        code=code,
                        data={
                            "launch_fallbacks_tried": launch_fallbacks_tried,
                            "next_actions": next_actions,
                        },
                    )
                self._runtimes[sid] = rt
                return ToolResult.success(
                    {
                        "session": sid,
                        "status": "started",
                        "page": rt._serialize_page_state(),
                        "runtime": rt.runtime_meta(),
                        "launch_fallbacks_tried": launch_fallbacks_tried,
                    }
                )

            if a == "session_close":
                self._close_session(sid)
                return ToolResult.success({"session": sid, "status": "closed"})

            rt = self._runtime_for(sid)
            if a == "navigate":
                url = str(kwargs.get("url", "")).strip()
                if not url:
                    return ToolResult.failure("navigate requires url", code="INVALID_ARGUMENTS")
                state = rt.navigate(
                    url=url,
                    wait_until=str(kwargs.get("wait_until", "domcontentloaded")),
                    timeout_ms=int(kwargs.get("timeout_ms", 30000)),
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "back":
                state = rt.back(retry_count=retry_count, retry_backoff_ms=retry_backoff_ms, settle_ms=settle_ms)
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "forward":
                state = rt.forward(retry_count=retry_count, retry_backoff_ms=retry_backoff_ms, settle_ms=settle_ms)
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "reload":
                state = rt.reload(retry_count=retry_count, retry_backoff_ms=retry_backoff_ms, settle_ms=settle_ms)
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "snapshot":
                out = {"session": sid, "action": a, "snapshot": rt._build_snapshot(limit=snapshot_limit)}
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "click_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("click_ref requires ref", code="INVALID_ARGUMENTS")
                rt.click_ref(
                    ref=ref,
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "type_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("type_ref requires ref", code="INVALID_ARGUMENTS")
                rt.type_ref(
                    ref=ref,
                    text=_text_arg_for_input_actions(kwargs),
                    submit=bool(kwargs.get("submit", False)),
                    delay_ms=int(kwargs.get("delay_ms", 0)),
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "fill_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("fill_ref requires ref", code="INVALID_ARGUMENTS")
                rt.fill_ref(
                    ref=ref,
                    text=_text_arg_for_input_actions(kwargs),
                    submit=bool(kwargs.get("submit", False)),
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "press_key":
                key = str(kwargs.get("key", "")).strip()
                if not key:
                    return ToolResult.failure("press_key requires key", code="INVALID_ARGUMENTS")
                rt.press_key(key=key)
                out = {"session": sid, "action": a, "key": key}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "select_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("select_ref requires ref", code="INVALID_ARGUMENTS")
                result = rt.select_ref(
                    ref=ref,
                    value=kwargs.get("value"),
                    label=kwargs.get("label"),
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "ref": ref, "result": result}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "check_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("check_ref requires ref", code="INVALID_ARGUMENTS")
                rt.check_ref(
                    ref=ref,
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "uncheck_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("uncheck_ref requires ref", code="INVALID_ARGUMENTS")
                rt.uncheck_ref(
                    ref=ref,
                    retry_count=retry_count,
                    retry_backoff_ms=retry_backoff_ms,
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "scroll_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("scroll_ref requires ref", code="INVALID_ARGUMENTS")
                rt.scroll_ref(ref=ref, amount=int(kwargs.get("amount", 500)))
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "scroll_page":
                rt.scroll_page(amount=int(kwargs.get("amount", 700)))
                out = {"session": sid, "action": a}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "wait":
                rt.wait(
                    wait_for=str(kwargs.get("wait_for", "timeout")),
                    value=kwargs.get("value"),
                    timeout_ms=int(kwargs.get("timeout_ms", 10000)),
                    load_state=str(kwargs.get("load_state", "domcontentloaded")),
                    settle_ms=settle_ms,
                )
                out = {"session": sid, "action": a}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "extract":
                data = rt.extract(
                    mode=str(kwargs.get("mode", "text")),
                    ref=kwargs.get("ref"),
                    selector=kwargs.get("selector"),
                    attribute=kwargs.get("attribute"),
                )
                return ToolResult.success({"session": sid, "action": a, "extract": data})
            if a == "tab_list":
                return ToolResult.success({"session": sid, "action": a, "tabs": rt.tabs()})
            if a == "tab_new":
                state = rt.tab_new(url=kwargs.get("url"))
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "tab_switch":
                state = rt.tab_switch(tab_id=kwargs.get("tab_id"), index=kwargs.get("index"))
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "tab_close":
                state = rt.tab_close(tab_id=kwargs.get("tab_id"), index=kwargs.get("index"))
                out = {"session": sid, "action": a, "page": state}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "upload_ref":
                ref = str(kwargs.get("ref", "")).strip()
                if not ref:
                    return ToolResult.failure("upload_ref requires ref", code="INVALID_ARGUMENTS")
                file_paths = kwargs.get("file_paths")
                if not isinstance(file_paths, list):
                    return ToolResult.failure("upload_ref requires file_paths[]", code="INVALID_ARGUMENTS")
                rt.upload_ref(ref=ref, file_paths=[str(p) for p in file_paths])
                out = {"session": sid, "action": a, "ref": ref}
                snap = rt._auto_snapshot(auto_snapshot, snapshot_limit)
                if snap is not None:
                    out["snapshot"] = snap
                if manual_takeover_check:
                    handover = rt.detect_manual_takeover()
                    if handover:
                        out["manual_takeover"] = handover
                return ToolResult.success(out)
            if a == "screenshot":
                data = rt.screenshot(path=kwargs.get("path"), full_page=bool(kwargs.get("full_page", False)))
                return ToolResult.success({"session": sid, "action": a, "screenshot": data})

            return ToolResult.failure(f"unknown action {action!r}", code="INVALID_ARGUMENTS")
        except ValueError as e:
            return ToolResult.failure(str(e), code="INVALID_ARGUMENTS")
        except RuntimeError as e:
            return ToolResult.failure(str(e), code="ACTION_EXECUTION_FAILED")
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="ACTION_EXECUTION_FAILED")


TOOL = BrowserTool
