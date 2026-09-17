"""The js_api bridge for the Web View's injected content.js, which calls these
as window.pywebview.api.*. Everything they do lives in Controller -- the chrome
calls the same object directly. See docs/adr/0010-nicegui-chrome.md.
"""


class Api:
    def __init__(self, controller):
        self._controller = controller

    def get_init_data(self, hostname: str) -> dict:
        return self._controller.get_init_data(hostname)

    def page_loaded(self, url: str, title: str, paragraph_count: int) -> None:
        self._controller.page_loaded(url, title, paragraph_count)

    def chapter_ready(self, paragraphs: list, title: str) -> dict:
        return self._controller.chapter_ready(paragraphs, title)

    def play_pause(self) -> None:
        self._controller.play_pause()

    def skip(self, direction: int) -> None:
        self._controller.skip(direction)
