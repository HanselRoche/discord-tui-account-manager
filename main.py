"""Entry point: python main.py"""
from src.tui.app import ManagerApp


def run() -> None:
    ManagerApp().run()


if __name__ == "__main__":
    run()
