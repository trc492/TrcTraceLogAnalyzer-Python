import pygame
import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import platform
import numpy as np
from zebra_motionworks import ZebraMotionWorks, ZMWError
import util
from util import Stopwatch, ParseError, rotate_vector, parse_file, align_with_origin, flip_y, v3_align_with_origin

class InfoWindow:
    def __init__(self, parent_window, title, start_open=False):
        self.parent = parent_window
        self.root = tk.Tk()
        self.root.title(title)
        self.root.resizable(False, False)
        self.label = tk.Label(self.root, text=self.get_info_text())
        self.label.pack(side=tk.TOP)
        self.open = start_open
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if not start_open:
            self.root.withdraw()

    def update(self):
        self.root.update()
        self.label.configure(text=self.get_info_text())

    def get_info_text(self):
        return ""

    def on_close(self):
        self.open = False
        self.root.withdraw()
    
    def reopen(self):
        if not self.open:
            self.open = True
            self.root.deiconify()
        else:
            self.root.focus_force()

class MatchInfoWindow(InfoWindow):
    def __init__(self, analysis_window):
        self.format_str = "Date: %s\nType: %s\nNumber: %s"
        super().__init__(analysis_window, "Match Info")
    
    def get_info_text(self):
        if self.parent.match_info:
            date = self.parent.match_info["@date"]
            match_type = self.parent.match_info["@type"]
            match_number = self.parent.match_info["@number"]
        else:
            date, match_type, match_number = "", "", ""
        return self.format_str % (date, match_type, match_number)

class AutoChoicesWindow(InfoWindow):
    def __init__(self, analysis_window):
        super().__init__(analysis_window, "Auto Choices")
    
    def get_info_text(self):
        if self.parent.auto_choices:
            return "\n".join(["%s: %s" % (key[1:], val) for key, val in self.parent.auto_choices.items()])
        else:
            return ""

class RawLogWindow(InfoWindow):
    def __init__(self, parent_window, lines, colors, on_change):
        self.parent = parent_window
        self.root = tk.Tk()
        self.root.title("Raw Log Overview")
        button = tk.Button(self.root, text="Jump to current", command=self.jump_to_current)
        button.pack(side=tk.TOP, fill=tk.X)
        self.code_box = tk.Listbox(self.root)
        self.add_lines(lines, colors)
        self.code_box.pack(fill=tk.BOTH, expand=True)
        self.last_selection = -1
        self.on_change = on_change
        self.open = False
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.withdraw()
    
    def update(self):
        self.root.update()
        c_s = self.code_box.curselection()
        if len(c_s) != 0 and c_s[0] != self.last_selection:
            self.on_change(c_s[0])
            self.last_selection = c_s[0]
            return True
        return False

    def add_lines(self, lines, colors):
        for i, l in enumerate(lines):
            self.code_box.insert(i, l)
            self.code_box.itemconfig(i, {"fg": colors[i]})

    def select(self, n):
        self.code_box.selection_clear(0, self.code_box.size())
        self.code_box.selection_set(n)
        self.code_box.see(n)

    def reset(self, lines, colors):
        self.code_box.delete(0, self.code_box.size())
        self.add_lines(lines, colors)

    def jump_to_current(self):
        self.select(self.parent.log_info[self.parent.step].log_index)
          

class AnalysisWindow:
    def __init__(self, screen_dimensions, field_dimensions):
        self.screen_dimensions = screen_dimensions
        self.field_dimensions = field_dimensions
        self.log_name = None
        self.log_info = None
        self.alliance = None
        self.match_info = None
        self.auto_choices = None
        self.extra = False
        self.lines = []
        self.line_colors = []
        self.zmw = None

        self.kill = False
        
        # Need to have this seemingly useless array because otherwise Python garbage collects the images for some reason
        self.images = []

        # Used to prevent setting the slider position from calling an update on the timer value
        self.set_update = False

        self.step = 0

        self.stopwatch = Stopwatch(max_time=30.0, start_paused=True)
        self.root = tk.Tk()
        self.root.title("Tracelog analysis")
        self.root.resizable(False, False)

        self.match_info_window = MatchInfoWindow(self)
        self.auto_choices_window = AutoChoicesWindow(self)
        self.log_window = RawLogWindow(self, self.lines, self.line_colors, self.set_step_from_line)

        self.root.protocol("WM_DELETE_WINDOW", self.prompt_close)

        menu_bar = tk.Menu(self.root)
        menu_bar.add_command(label="Open", command=self.prompt_file)
        menu_bar.add_command(label="Close", command=self.prompt_close)
        info_menu = tk.Menu(menu_bar, tearoff=0)
        info_menu.add_command(label="Match Info", command=self.match_info_window.reopen)
        info_menu.add_command(label="Auto Choices", command=self.auto_choices_window.reopen)
        info_menu.add_command(label="Raw Log XML", command=self.log_window.reopen)
        info_menu.add_command(label="Zebra MotionWorks", command=self.get_zebra_motionworks)

        embed = tk.Frame(self.root, width=self.screen_dimensions[0], height=self.screen_dimensions[1])
        embed.pack(side=tk.TOP)

        self.buttonwin = tk.Frame(self.root, width=100, height=500)
        self.buttonwin.pack(side=tk.TOP)

        sliderwin = tk.Frame(self.root, width=600, height=50)
        sliderwin.pack(side=tk.BOTTOM)

        os.environ["SDL_WINDOWID"] = str(embed.winfo_id())
        if platform.system == "Windows":
            os.environ["SDL_VIDEODRIVER"] = "windib"

        self.screen = pygame.display.set_mode(self.screen_dimensions)
        self.screen.fill(pygame.Color(0, 100, 255))

        pygame.font.init()
        self.timer_font = pygame.font.SysFont("Courier New", 30)
        self.info_font = pygame.font.SysFont("Courier New", 15)
        pygame.display.init()
        pygame.display.update()

        self.robot_surface = pygame.image.load(util.ROBOT_IMAGE).convert_alpha()

        self.background = pygame.image.load(util.FIELD_IMAGE)

        self.add_image_button("assets\\jb_button.png", self.stopwatch.reset)
        self.add_image_button("assets\\b_button.png", self.prev_step)
        self.add_image_button("assets\\f_button.png", self.next_step)
        self.add_image_button("assets\\jf_button.png", self.stopwatch.max)
        self.add_image_button("assets\\play_button.png", self.stopwatch.start)
        self.add_image_button("assets\\pause_button.png", self.stopwatch.pause)
        self.add_image_button("assets\\stop_button.png", self.stopwatch.stop)
        self.add_image_button("assets\\info_button.png", self.toggle_extra)

        self.time_slider = tk.Scale(sliderwin, command=self.slider_update, orient=tk.HORIZONTAL, length=500,
                                    resolution=0.001, from_=0.0, to=30.0, showvalue=False)
        self.time_slider.pack(side=tk.BOTTOM)

        self.root.configure(menu=menu_bar)
        menu_bar.add_cascade(label="Info", menu=info_menu)
        self.root.update()

    def prompt_close(self):
        if messagebox.askokcancel(title="Close window", message="Are you sure you want to close the log analyzer?"):
            self.kill = True

    def toggle_extra(self):
        self.extra = not self.extra

    def add_image_button(self, image_path, command):
        image = tk.PhotoImage(master=self.root, file=image_path)
        self.images.append(image)
        button = tk.Button(self.buttonwin, image=image, command=command)
        button.pack(side=tk.LEFT, padx=(2, 2))

    def prompt_file(self):
        f = filedialog.askopenfile(parent=self.root, mode='r', title='Choose a file', filetypes=(("log files","*.log"),("all files","*.*")))
        if f != None:
            self.reload(f)
            # parse_file handles file closing so we don't have to do that here

    def reload(self, log_file):
        try:
            self.match_info, self.auto_choices, self.log_info, self.lines, self.line_colors = parse_file(log_file)
        except ParseError as e:
            messagebox.showerror("Error", "Something went wrong parsing the file: %s. Make sure the file is a valid autonomous log." % e.message)
            return
        self.alliance = self.auto_choices["@alliance"]
        self.log_name = "%s %s" % (self.match_info["@type"], self.match_info["@number"])
        self.stopwatch.max_time = self.log_info[-1].time
        self.stopwatch.stop()
        self.step = 0
        self.root.title("Tracelog analysis: " + self.log_name)
        self.time_slider.configure(to=self.log_info[-1].time)
        self.log_window.reset(self.lines, self.line_colors)
        self.zmw = None

    def slider_update(self, num):
        if self.set_update:
            self.set_update = False
        else:
            self.stopwatch.set_time(float(num))
            self.update_step()

    def render_text(self, text, x, y, font, spacing=5):
        lines = text.splitlines()
        for i, l in enumerate(lines):
            self.screen.blit(font.render(l, False, tuple(util.TEXT_COLOR)), (x, y + (font.size("|")[1] + spacing)*i))

    def inches_to_pixels(self, coords):
        return (round(coords[0] * (self.screen_dimensions[0] / self.field_dimensions[0])), \
            round(coords[1] * (self.screen_dimensions[1] / self.field_dimensions[1])))

    def update_time_slider(self):
        self.set_update = True
        self.time_slider.set(self.stopwatch.get_time())

    def update_step(self):
        if self.log_info:
            for i in range(len(self.log_info)):
                if self.log_info[i].time > self.stopwatch.get_time():
                    self.step = i - 1 if i != 0 else i
                    return
            self.step = len(self.log_info) - 1
        else:
            self.step = 0
    
    def draw_robot(self):
        x, y, angle = v3_align_with_origin(self.log_info[self.step].actual_pos.v3, self.alliance)
        robot_rect = self.robot_surface.get_rect()
        robot_rect.center = self.inches_to_pixels(flip_y((x, y)))
        self.screen.blit(pygame.transform.rotate(self.robot_surface, angle), robot_rect)

    def draw_robot_error(self):
        robot_pos = self.inches_to_pixels(flip_y(align_with_origin(self.log_info[self.step].actual_pos.pos, self.alliance)))
        target_x, target_y, target_h = v3_align_with_origin(self.log_info[self.step].abs_target.v3, self.alliance)
        target_pos = self.inches_to_pixels(flip_y((target_x, target_y)))
        heading_target_vector = self.inches_to_pixels(rotate_vector((0, 5), target_h + 180, True))
        abs_heading_target = (target_pos[0] + heading_target_vector[0], target_pos[1] + heading_target_vector[1])
        pygame.draw.line(self.screen, (255,0,0), robot_pos, target_pos, 5)
        pygame.draw.line(self.screen, (0, 255, 0), target_pos, abs_heading_target, 5)

    def draw_timer(self):
        text_y = self.screen_dimensions[1] - 70 if self.alliance != None and "blue" in self.alliance.lower() else 40
        self.render_text("Time: %.3f" % self.stopwatch.get_time(), 15, text_y, self.timer_font)

    def draw_robot_info(self):
        last_time = self.log_info[self.step].time
        x, y, angle = self.log_info[self.step].actual_pos.v3
        x_t, y_t, angle_t = self.log_info[self.step].abs_target.v3
        state = self.log_info[self.step].state_name
        text_x = self.screen_dimensions[0] - max(self.info_font.size("state: " + state)[0], 215)
        text_y = self.screen_dimensions[1] - 100 if self.alliance != None and "blue" in self.alliance.lower() else 10
        self.render_text("x: %12.1f/%.1f\ny: %12.1f/%.1f\nheading: %6.1f/%.1f\nlast time: %.3f\nstate: %s" % (x, x_t, y, y_t, angle, angle_t, last_time, state), \
            text_x, text_y, self.info_font, spacing=3)

    def next_step(self):
        if self.step != len(self.log_info) - 1:
            self.step += 1
        self.stopwatch.set_time(self.log_info[self.step].time)
    
    def prev_step(self):
        if self.step == 0:
            self.stopwatch.reset()
            self.update_step()
        else:
            self.step -= 1
            self.stopwatch.set_time(self.log_info[self.step].time)

    def set_step(self, n):
        self.step = n
        self.stopwatch.set_time(self.log_info[self.step].time)
        self.update_time_slider()

    def set_step_from_line(self, l):
        s = 0
        found = False
        while True:
            if l == 0:
                break
            for i, log in enumerate(self.log_info):
                if log.log_index == l:
                    s = i
                    found = True
                    break
            if found:
                break
            l -= 1
        self.set_step(s)

    def get_zebra_motionworks(self):
        # TODO: make this more flexible
        if self.match_info == None:
            messagebox.showerror("Error", "No log file loaded, cannot retrieve Zebra MotionWorks data.")
            return
        failed_error = "Something went wrong downloading Zebra MotionWorks data from TheBlueAlliance: "
        try:
            # for now the year and event identifier are hardcoded, will soon add parsing thing
            self.zmw = ZebraMotionWorks(2020, "wasno", self.match_info["@type"], self.match_info["@number"])
        except ZMWError as e:
            messagebox.showerror("Error", failed_error + e.message)
            return
        except json.decoder.JSONDecodeError:
            messagebox.showerror("Error", failed_error + "invalid JSON data")
            return
        except KeyError:
            messagebox.showerror("Error", failed_error + "missing JSON content")
            return
        messagebox.showinfo("Success", "Zebra MotionWorks data successfully retrieved.")

    def display_zebra_motionworks(self):
        data = self.zmw.data
        index = self.zmw.closest_time_index(self.stopwatch.get_time())
        robots = []
        for alliance, teams in data.items():
            robots.extend([(alliance, team, coords_list[index]) for team, coords_list in teams.items()])
        for robot in robots:
            color = (255, 0, 0) if robot[0] == "red" else (0, 0, 255)
            try:
                pygame.draw.circle(self.screen, color, self.inches_to_pixels(flip_y([(coord * 12) for coord in robot[2]])), 7)
            except TypeError:
                pass

    def main_loop(self):
        while(1):
            if self.kill:
                exit()
            self.screen.blit(self.background, (0,0))
            if self.log_name != None and self.log_info != None and self.alliance != None:
                self.update_step()
                self.update_time_slider()
                self.draw_robot()
                if self.extra:
                    self.draw_robot_error()
                self.draw_robot_info()
                if self.match_info_window.open:
                    self.match_info_window.update()
                if self.auto_choices_window.open:
                    self.auto_choices_window.update()
                if self.log_window.open:
                    self.log_window.update()
                if self.zmw:
                    self.display_zebra_motionworks()

            self.draw_timer()
            try:
                self.root.update()
            except tk.TclError:
                break
            pygame.display.update()