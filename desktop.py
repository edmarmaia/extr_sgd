"""Inicializa a interface React no desktop Windows."""

import logging
import os
from pathlib import Path
import sys


def main():
    import webview
    from desktop_api import DesktopAPI

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    index = root / "frontend" / "dist" / "index.html"
    icon = root / "icon.ico"
    if not index.is_file():
        raise RuntimeError("Interface nao compilada. Execute npm ci e npm run build na pasta frontend.")
    if not icon.is_file():
        raise RuntimeError("Icone do aplicativo nao encontrado: icon.ico.")

    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ExtratorSGD.Desktop")

    profile = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "ExtratorSGD"
    profile.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=profile / "desktop.log", level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8", force=True)
    api = DesktopAPI()
    # A ponte publica somente operacoes da aplicacao.
    class Bridge:
        def get_state(self):
            return api.get_state()

        def select_input(self):
            return api.select_input()

        def start_job(self, options):
            return api.start_job(options)

        def cancel_job(self):
            return api.cancel_job()

        def export_results(self):
            return api.export_results()

    build_url = f"{index}?build={index.stat().st_mtime_ns}"
    window = webview.create_window(
        "Extrator SGD | Central de operacoes", build_url, js_api=Bridge(),
        width=1360, height=900, min_size=(800, 600), background_color="#f6f7f9",
    )
    api.set_window(window)

    def closing():
        state = api.get_state()
        # O worker pode estar salvando resultados parciais durante o cancelamento.
        if api._active():
            if api._dialog("create_confirmation_dialog", "Operacao em andamento",
                           "Cancelar a operacao? Aguarde o cancelamento e feche a janela novamente."):
                api.cancel_job()
            return False
        if state["rows"]:
            return api._dialog("create_confirmation_dialog", "Fechar aplicativo?",
                               "Confira se exportou os resultados desejados. "
                               "Lotes e monitoramento possuem copia automatica indicada no registro de atividade. "
                               "Deseja fechar?")
        return True

    window.events.closing += closing
    webview.start(gui="edgechromium", private_mode=False,
                  storage_path=str(profile / "webview"), icon=str(icon))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Falha ao iniciar o desktop")
        if sys.platform == "win32":
            import ctypes
            if "Python.Runtime.Loader.Initialize" in str(exc):
                help_text = (
                    "O Windows nao permitiu carregar uma biblioteca .NET. "
                    "Se o pacote veio da internet, desbloqueie o ZIP em "
                    "Propriedades e extraia-o novamente."
                )
            else:
                help_text = "Verifique as dependencias e o Microsoft Edge WebView2 Runtime."
            ctypes.windll.user32.MessageBoxW(
                0, f"Nao foi possivel iniciar o Extrator SGD.\n\n{exc}\n\n{help_text}",
                "Extrator SGD", 0x10,
            )
        raise
