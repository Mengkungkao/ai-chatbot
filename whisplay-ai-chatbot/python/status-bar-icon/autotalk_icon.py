from icon_constants import STATUS_ICON_HEIGHT


class AutoTalkStatusIcon:
    """Little LED showing whether she may start conversations on her own.

    Drawn rather than loaded from a PNG so there is no asset to ship. Filled
    green means auto-talk is on; a hollow grey ring means it is off, so the
    indicator is always present and the two states cannot be confused with the
    icon simply being missing.
    """

    ON_COLOR = (90, 225, 130, 255)
    OFF_COLOR = (95, 95, 95, 255)

    def __init__(self, status_font_size, enabled):
        self.status_font_size = status_font_size
        self.icon_height = STATUS_ICON_HEIGHT
        self.enabled = bool(enabled)
        self.diameter = max(6, self.icon_height - 5)
        self.icon_width = self.diameter

    def measure(self):
        return (self.icon_width, self.icon_height)

    def get_top_y(self):
        return self.status_font_size // 2

    def render(self, draw, x, y):
        top = y + (self.icon_height - self.diameter) // 2
        box = [x, top, x + self.diameter, top + self.diameter]
        if self.enabled:
            draw.ellipse(box, fill=self.ON_COLOR, outline=self.ON_COLOR)
        else:
            draw.ellipse(box, fill=None, outline=self.OFF_COLOR, width=2)
