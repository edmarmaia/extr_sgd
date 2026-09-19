"""Inicializa a versao desktop compilada com Cython."""

import logging
import sys

from desktop_native import main


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
                help_text = "Verifique o Microsoft Edge WebView2 Runtime."
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Nao foi possivel iniciar o Extrator SGD.\n\n{exc}\n\n{help_text}",
                "Extrator SGD",
                0x10,
            )
        raise
