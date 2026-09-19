"""Smoke com WebView2 real: python tests/smoke_desktop.py.

O nome evita que a descoberta do unittest abra uma janela desktop.
"""

from contextlib import ExitStack
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop


def main():
    import webview

    real_start = webview.start
    errors = []
    result = {}

    def worker():
        window = webview.windows[0]
        try:
            if not window.events.loaded.wait(30):
                raise TimeoutError("WebView2 did not load the local DOM in 30s")
            deadline = time.monotonic() + 30

            def wait_js(script, description):
                while time.monotonic() < deadline:
                    value = window.evaluate_js(script)
                    if value:
                        return value
                    time.sleep(0.1)
                raise TimeoutError(f"Timed out waiting for {description}")

            wait_js(
                "document.readyState === 'complete' && "
                "typeof window.pywebview?.api?.get_state === 'function'",
                "DOM and window.pywebview.api",
            )
            renderer = webview.guilib.renderer
            control = str(window.native.webview.GetType().FullName)
            if renderer != "edgechromium" or control != "Microsoft.Web.WebView2.WinForms.WebView2":
                raise AssertionError(f"Not real WebView2: {renderer}, {control}")

            # O retorno imediato de evaluate_js nao representa a Promise resolvida.
            window.evaluate_js("""
                window.__desktopSmoke = null;
                (async () => {
                    try {
                        const state = await window.pywebview.api.get_state();
                        window.__desktopSmoke = {state};
                    } catch (error) {
                        window.__desktopSmoke = {error: String(error)};
                    }
                })();
                null;
            """)
            reply = wait_js("window.__desktopSmoke", "async get_state response")
            if "error" in reply:
                raise AssertionError(f"Bridge rejected get_state: {reply['error']}")
            state = reply["state"]
            if state["status"] != "idle" or state["rows"] != [] or state["input"] is not None:
                raise AssertionError(f"Expected idle state without input/results: {state}")

            ui = wait_js("""
                (() => {
                    const h1 = document.querySelector('h1');
                    const connection = document.querySelector('[data-testid="connection-status"]');
                    const guide = document.querySelector('.file-format');
                    const script = document.querySelector('script[type="module"]');
                    if (!h1?.getClientRects().length ||
                        !guide?.getClientRects().length)
                        return null;
                    if (connection?.innerText.trim() !== 'Desktop conectado') return null;
                    if (!guide.innerText.includes('numero_desligamento')) return null;
                    return {
                        h1: h1.innerText.trim(),
                        connection: connection.innerText.trim(),
                        guide: guide.innerText.trim(),
                        script: script?.src || '',
                        location: window.location.href,
                    };
                })()
            """, "updated desktop interface")
            if ui["h1"] != "Extra\u00e7\u00e3o em lote":
                raise AssertionError(f"Unexpected heading: {ui['h1']!r}")
            window.evaluate_js("document.querySelector('.theme-toggle').click(); null")
            theme = wait_js("""
                (() => {
                    if (document.documentElement.dataset.theme !== 'dark') return null;
                    const saved = JSON.parse(localStorage.getItem('sgd.preferences.v1') || '{}');
                    const background = getComputedStyle(document.body).backgroundColor;
                    if (saved.theme !== 'dark') return null;
                    return {theme: saved.theme, background};
                })()
            """, "persisted dark theme")
            if theme["background"] != "rgb(14, 21, 28)":
                raise AssertionError(f"Unexpected dark background: {theme['background']!r}")
            result.update(renderer=renderer, control=control, state=state, **ui, **theme)
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                window.destroy()
            except BaseException as exc:
                errors.append(exc)

    def start_with_worker(*args, **kwargs):
        if args or kwargs.get("gui") != "edgechromium":
            raise AssertionError("Launcher must explicitly request edgechromium")
        icon = Path(kwargs.get("icon", ""))
        if icon.name != "icon.ico" or not icon.is_file():
            raise AssertionError(f"Launcher must use the bundled icon.ico: {icon}")
        result["icon"] = str(icon)
        return real_start(worker, **kwargs)

    # Isola preferencias, armazenamento do navegador e desktop.log.
    with tempfile.TemporaryDirectory(prefix="sgd-smoke-", ignore_cleanup_errors=True) as profile:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"LOCALAPPDATA": profile}))
            stack.enter_context(patch.object(webview, "start", side_effect=start_with_worker))
            guards = []
            for target in (
                "requests.sessions.Session.send",
                "desktop_api.DesktopAPI.start_job",
                "desktop_api.DesktopAPI.select_input",
                "desktop_api.DesktopAPI.export_results",
                "desktop_api.DesktopAPI.cancel_job",
                "desktop_api.DesktopAPI._dialog",
                "webview.window.Window.create_file_dialog",
                "webview.window.Window.create_confirmation_dialog",
            ):
                guards.append(stack.enter_context(patch(
                    target, side_effect=AssertionError(f"Forbidden in smoke: {target}")
                )))
            try:
                desktop.main()
                if errors:
                    raise RuntimeError("Real WebView2 smoke failed") from errors[0]
                if not result:
                    raise AssertionError("Window closed before smoke completed")
                for guard in guards:
                    guard.assert_not_called()
            finally:
                logging.shutdown()

    print(f"PASS: real WebView2 ({result['renderer']}; {result['control']})")
    print(f"h1={result['h1']!r}; connection={result['connection']!r}")
    print(f"guide={result['guide']!r}")
    print(f"theme={result['theme']!r}; background={result['background']!r}")
    print(f"icon={result['icon']!r}")
    print(f"location={result['location']!r}; script={result['script']!r}")
    print("Async JS -> Python get_state: idle, rows=[], input=None")
    print("Window closed automatically; no jobs, dialogs or requests HTTP calls.")


if __name__ == "__main__":
    main()
