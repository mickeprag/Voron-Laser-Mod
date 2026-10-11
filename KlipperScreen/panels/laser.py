"""Laser panel for KlipperScreen (port of DrPacemaker/Voron-Laser-Mod to the post-2023 panel API).

Menu items come from [menu __main laser ...] in KlipperScreen.conf. Items whose params contain
"orientation": "left" go in the left column next to the Z jog controls; all others go in the right grid.
"""
import json
import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from ks_includes.KlippyGcodes import KlippyGcodes
from panels.menu import Panel as MenuPanel


class Panel(MenuPanel):
    distances = ['.1', '.5', '1', '5', '10', '25', '50']
    distance = distances[2]

    def __init__(self, screen, title, items=None):
        if items is None:
            items = screen._config.get_menu_items("__main laser")
        self.items_left, self.items_right = self.split_by_orientation(items)
        super().__init__(screen, title, items)
        logging.info("### Making LaserMenu")
        self.dist_buttons = {}
        self.buttons = {}

        grid = Gtk.Grid(row_homogeneous=True, column_homogeneous=True, hexpand=True, vexpand=True)
        grid.attach(self.create_left_panel(), 0, 0, 1, 1)
        if self._screen.vertical_mode:
            grid.attach(self.scroll, 0, 1, 1, 1)
        else:
            grid.attach(self.scroll, 1, 0, 1, 1)
        self.content.add(grid)

    @staticmethod
    def split_by_orientation(items):
        # "orientation" only picks the column; strip it so it isn't sent to Moonraker with the script
        left, right = [], []
        for entry in items:
            item = next(iter(entry.values()))
            try:
                params = json.loads(item['params'])
            except (TypeError, ValueError):
                params = None
            orientation = 'right'
            if isinstance(params, dict):
                orientation = params.pop('orientation', 'right')
                item['params'] = json.dumps(params)
            (left if orientation == 'left' else right).append(entry)
        return left, right

    def activate(self):
        # Re-evaluate enable: conditions (e.g. quad_gantry_level) every time the panel is shown
        self.j2_data = self._printer.get_printer_status_data()
        for child in self.scroll.get_children():
            self.scroll.remove(child)
        columns = 3 if self._screen.vertical_mode else 2
        self.scroll.add(self.arrangeMenuItems(self.items_right, columns, True))
        self.update_button_visibility()

    def update_button_visibility(self):
        for key, button in self.buttons.items():
            visible = self._config.get_config().getboolean(f"graph {self._screen.connected_printer}",
                                                           key, fallback=False)
            button['visible'] = visible
            if visible:
                button['widget'].get_style_context().add_class(button['class'])
            else:
                button['widget'].get_style_context().remove_class(button['class'])

    def toggle_visibility(self, widget, key):
        self.buttons[key]['visible'] ^= True
        section = f"graph {self._screen.connected_printer}"
        if section not in self._config.get_config().sections():
            self._config.get_config().add_section(section)
        self._config.set(section, key, f"{self.buttons[key]['visible']}")
        self._config.save_user_config_options()
        self.update_button_visibility()

    def create_left_panel(self):
        top = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        enabled = [next(iter(entry)) for entry in self.items_left
                   if self.evaluate_enable(next(iter(entry.values()))['enable'])]
        for i, key in enumerate(enabled):
            # graph_label_laser_<n> classes are defined in the laser theme's style.css
            self.buttons[key] = {"widget": self.labels[key], "class": f"graph_label_laser_{i + 2}", "visible": False}
            self.labels[key].connect("clicked", self.toggle_visibility, key)
            top.attach(self.labels[key], i % 2, i // 2, 1, 1)

        zgrid = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        for col, (direction, icon) in enumerate((("+", "z-farther"), ("-", "z-closer"))):
            button = self._gtk.Button(icon, f"Z{direction}", "color3")
            button.connect("clicked", self.move, "Z", direction)
            zgrid.attach(button, col, 0, 1, 1)

        distgrid = Gtk.Grid()
        for j, i in enumerate(self.distances):
            button = self._gtk.Button(label=i)
            button.set_direction(Gtk.TextDirection.LTR)
            button.connect("clicked", self.change_distance, i)
            ctx = button.get_style_context()
            ctx.add_class("horizontal_togglebuttons")
            if i == self.distance:
                ctx.add_class("horizontal_togglebuttons_active")
            distgrid.attach(button, j, 0, 1, 1)
            self.dist_buttons[i] = button

        left = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        left.attach(top, 0, 0, 1, 2)
        left.attach(zgrid, 0, 2, 1, 2)
        left.attach(distgrid, 0, 4, 1, 1)
        return left

    def change_distance(self, widget, distance):
        logging.info(f"### Distance {distance}")
        self.dist_buttons[self.distance].get_style_context().remove_class("horizontal_togglebuttons_active")
        self.dist_buttons[distance].get_style_context().add_class("horizontal_togglebuttons_active")
        self.distance = distance

    def move(self, widget, axis, direction):
        if self._config.get_config()['main'].getboolean(f"invert_{axis.lower()}", False):
            direction = "-" if direction == "+" else "+"

        dist = f"{direction}{self.distance}"
        config_key = "move_speed_z" if axis == "Z" else "move_speed_xy"
        speed = None if self.ks_printer_cfg is None else self.ks_printer_cfg.getint(config_key, None)
        if speed is None:
            speed = self._config.get_config()['main'].getint(config_key, 20)
        speed = 60 * max(1, speed)
        script = f"{KlippyGcodes.MOVE_RELATIVE}\nG0 {axis}{dist} F{speed}"
        if self._printer.get_stat("gcode_move", "absolute_coordinates"):
            script += f"\n{KlippyGcodes.MOVE_ABSOLUTE}"
        self._screen._send_action(widget, "printer.gcode.script", {"script": script})
