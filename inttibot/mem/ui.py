"""Where the app is: screens and the open minigame."""
from .il2cpp import Game


class UI:
    """Where the app is: INTTI's UIManager (screens over the home screen, the side menu) and
    MiniGameManager (the open minigame)."""

    def __init__(self, game=None):
        self.g = game or Game()
        self.ui_k = self.g.find_class("UIManager")
        self.mg_k = self.g.find_class("MiniGameManager")

    def string(self, p):
        if not p:
            return None
        n = self.g.m.i32(p + 0x10)
        return self.g.m.read(p + 0x14, 2 * n).decode("utf-16-le") if 0 <= n < 500 else None

    def minigame(self):
        """The open minigame's gameId ('car_game', 'quiz_game', 'shooter_game', 'clicker_game',
        ...), or None on INTTI's own screens."""
        mm = self.g.static(self.mg_k, "INSTANCE")
        cur = self.g.field(mm, "currentMiniGame")
        return self.string(self.g.field(cur, "gameId")) if cur else None

    def screen(self):
        """The screen over the home screen: 'games' (Pelit), 'date', 'propSelect', 'stats',
        'cateringList', 'calendar', 'social', or None (the home screen itself)."""
        ui = self.g.static(self.ui_k, "INSTANCE")
        cur = self.g.field(ui, "currentActiveScreen")
        if not cur:
            return None
        for name in ("games", "date", "propSelect", "stats", "cateringList", "calendar", "social"):
            if self.g.field(ui, name + "Screen") == cur:
                return name
        return "?"

    def menu_open(self):
        ui = self.g.static(self.ui_k, "INSTANCE")
        return bool(self.g.m.read(ui + self.g.class_fields(self.ui_k)["mainMenuEnabled"][0], 1)[0])
