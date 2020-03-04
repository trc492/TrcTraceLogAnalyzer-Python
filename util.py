import time
import math
import os
import json
import traceback
import numpy as np
from tkinter import messagebox
import xmltodict
from xml.parsers.expat import ExpatError

FIELD_DIMENSIONS = (0, 0)
SCREEN_DIMENSIONS = (0, 0)
BLUE_ORIGIN = (0, 144)
BLUE_X_DIRECTION = 0
RED_ORIGIN = (0, 144)
RED_X_DIRECTION = 0
FIELD_IMAGE = ""
ROBOT_IMAGE = ""
TEXT_COLOR = ""

with open("config.json") as f:
    data = json.load(f)
    data = data[data["game"]] # bruh
    FIELD_DIMENSIONS = data["field_dimensions"]
    SCREEN_DIMENSIONS = data["screen_dimensions"]
    BLUE_ORIGIN = data["blue_origin"]
    BLUE_X_DIRECTION = data["blue_x_direction"]
    RED_ORIGIN = data["red_origin"]
    RED_X_DIRECTION = data["red_x_direction"]
    FIELD_IMAGE = data["field_image"]
    ROBOT_IMAGE = data["robot_image"]
    TEXT_COLOR = data["text_color"]

class ParseError(Exception):
    def __init__(self, message):
        self.message = message

class ConfigError(Exception):
    def __init__(self, message):
        self.message = message

class Stopwatch:
    def __init__(self, max_time=None, start_paused=False):
        self.start_time = time.time()
        self.last_time = 0.0
        self.paused = start_paused
        self.max_time = max_time
    
    def get_time(self):
        if self.paused:
            if self.max_time == None:
                return self.last_time
            else:
                return min(self.last_time, self.max_time)
        else:
            if self.max_time != None and time.time() - self.start_time > self.max_time:
                self.paused = True
                self.last_time = self.max_time
                return self.max_time
            else:
                return time.time() - self.start_time

    def set_time(self, t):
        self.last_time = t
        self.start_time = time.time() - self.last_time

    def reset(self):
        self.start_time = time.time()
        self.last_time = 0.0

    def max(self):
        if self.max_time != None:
            self.start_time = time.time() - self.max_time
            self.last_time = self.max_time

    def pause(self):
        if not self.paused:
            self.last_time = self.get_time()
            self.paused = True

    def start(self):
        if self.paused:
            self.start_time = time.time() - self.last_time
            self.paused = False

    def stop(self):
        self.pause()
        self.reset()

class RobotPose:
    def __init__(self, x, y, heading):
        self.x = float(x)
        self.y = float(y)
        self.heading = float(heading)
        self.pos = (self.x, self.y)
        self.v3 = (self.x, self.y, self.heading)

class Log:
    def __init__(self, time, actual_pos, abs_target, state_name, log_index):
        self.time = time
        self.actual_pos = actual_pos
        self.abs_target = abs_target
        self.state_name = state_name
        self.log_index = log_index

def inside(string, opening, closing):
    inside = ""
    is_inside = False
    for character in string:
        if is_inside:
            if character == closing:
                return inside
            else:
                inside += character
        else:
            if character == opening:
                is_inside = True
    raise ParseError("nothing inside %s and %s: %s" % (opening, closing, string))

def find_var(string, var_name):
    before = ": ([{/|\\,"
    after = " =:("
    var_counter = 0
    for i in range(len(string)):
        # If the characters match and we are at the beginning of the and if the character before, if it exists and is not part of the variable name, is an acceptable before character
        if string[i] == var_name[var_counter] and (var_counter != 0 or (i == 0 or string[i - 1] in before)):
            var_counter += 1
            # If we are at the end of the variable name
            if var_counter == len(var_name):
                # If the character after, if it exists, is an acceptable after character
                if (i == len(string) - 1 or string[i + 1] in after):
                    return string[i+1:]
                else:
                    var_counter = 0
        else:
            var_counter = 0
    raise ParseError("specified variable %s not in string: %s" % (var_name, string))

def str_get_vars(string, *var_names):
    parsed_vars = []
    starters = " =:("
    enders = " ,;\n):"
    for var_name in var_names:
        after = find_var(string, var_name)
        var = ""
        recording = False
        for i in range(len(after)):
            if recording:
                if after[i] in enders:
                    break
                else:
                    var += after[i]
            else:
                if after[i] not in starters:
                    recording = True
                    var += after[i]
        parsed_vars.append(var)
    return parsed_vars

def align_with_origin(point, alliance):
    x_direction = BLUE_X_DIRECTION if "blue" in alliance.lower() else RED_X_DIRECTION
    origin = BLUE_ORIGIN if "blue" in alliance.lower() else RED_ORIGIN
    if x_direction == 0:
        return (origin[0] + point[0], origin[1] + point[1])
    elif x_direction == 1:
        return (origin[0] - point[1], origin[1] + point[0])
    elif x_direction == 2:
        return (origin[0] - point[0], origin[1] - point[1])
    elif x_direction == 3:
        return (origin[0] + point[1], origin[1] - point[0])
    raise ConfigError("invalid x direction")

def apply_x_direction(angle, alliance, degrees=True):
    x_direction = BLUE_X_DIRECTION if "blue" in alliance.lower() else RED_X_DIRECTION
    return -(angle - x_direction * (90 if degrees else (math.pi / 2))) % (360 if degrees else (math.pi * 2))

def v3_align_with_origin(v3, alliance):
    return align_with_origin(v3[0:2], alliance) + (apply_x_direction(v3[2], alliance),)

def flip_y(pos):
    return (pos[0], FIELD_DIMENSIONS[1] - pos[1])

def rotate_vector(v, angle, degrees=False):
    if degrees:
        angle = math.radians(angle)
    rot_matrix = np.array([[math.cos(angle), -math.sin(angle)],
                           [math.sin(angle),  math.cos(angle)]])
    rotated = np.matmul(np.array(v), rot_matrix)
    return tuple(rotated)

def parse_file(fp):
    try:
        lines = fp.readlines()
    except UnicodeDecodeError:
        raise ParseError("the file must be in text format")

    pos_info = []

    last_state = "NONE"
    target_pose = None
    
    match_info = None
    auto_choices = None

    colors = []

    for i, line in enumerate(lines):
        if "_Info" in line:
            xml_str = line.split(": ")[1]
            try:
                xml_data = xmltodict.parse(xml_str)
            except ExpatError:
                colors.append("black")
                continue
            try:
                if "Event" in xml_data.keys():
                    xml_data = xml_data["Event"]
                    if xml_data["@name"] == "StateInfo":
                        last_state = xml_data["@state"]
                        target_pose = RobotPose(xml_data["@xTarget"], xml_data["@yTarget"], xml_data["@headingTarget"])
                        robot_pose = RobotPose(xml_data["@xPos"], xml_data["@yPos"], xml_data["@heading"])
                        pos_info.append(Log(float(xml_data["@time"]), robot_pose, target_pose, last_state, i))
                    elif xml_data["@name"] == "RobotPose": 
                        pose = xml_data["@pose"]
                        x, y, angle = str_get_vars(pose, "x", "y", "angle")
                        robot_pose = RobotPose(x, y, angle)
                        pos_info.append(Log(float(xml_data["@time"]), robot_pose, target_pose, last_state, i))
                elif "Info" in xml_data.keys():
                    xml_data = xml_data["Info"]
                    if xml_data["@name"] == "MatchInfo":
                        match_info = xml_data
                    elif xml_data["@name"] == "AutoChoices":
                        auto_choices = xml_data
                colors.append("red")
                continue
            except KeyError:
                # headers in xml data not valid
                pass
        colors.append("black")

    if len(pos_info) == 0:
        raise ParseError("no position info")
    if match_info == None:
        raise ParseError("no match info found")
    if auto_choices == None:
        raise ParseError("no auto choices found")
    return (match_info, auto_choices, pos_info, lines, colors)