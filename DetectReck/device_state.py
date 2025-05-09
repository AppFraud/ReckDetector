import copy
import math
import os
import shutil
import logging
import re
import numpy
import time
from PIL import Image
from datetime import datetime

from .utg import UTG
from .utils import md5
from .input_event import TouchEvent, LongTouchEvent, ScrollEvent, SetTextEvent, KeyEvent
# Baidu OCR
from .utils import get_client
from .new_input_policy import MIN_NUM_EXPLORE_EVENTS
from .text_similarity import get_sim_score
from sentence_transformers import SentenceTransformer


class DeviceState(object):
    """
    the state of the current device
    """

    def __init__(self, device, views, foreground_activity, activity_stack, background_services,
                 tag=None, screenshot_path=None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.foreground_activity = foreground_activity
        self.activity_stack = activity_stack if isinstance(activity_stack, list) else []
        self.background_services = background_services
        if tag is None:
            tag = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.tag = tag
        self.screenshot_path = screenshot_path
        self.views = self.__parse_views(views)
        self.view_tree = {}
        # Add
        self.enabled_view_ids = self.get_enabled_view_ids()
        self.__assemble_view_tree(self.view_tree, self.views)
        self.__generate_view_strs()

        # update state_str and add state_str_content
        # self.state_str = self.__get_state_str()
        self.state_str = self.__get_content_free_state_str()
        self.state_str_content = self.__get_state_str()

        self.structure_str = self.__get_content_free_state_str()
        self.search_content = self.__get_search_content()
        self.possible_events = None
        self.width = device.get_width(refresh=True)
        self.height = device.get_height(refresh=True)
        # Add
        self.view_file_path = None

    def to_dict(self):
        state = {'tag': self.tag,
                 'state_str': self.state_str_content,
                 'state_str_content_free': self.structure_str,
                 'foreground_activity': self.foreground_activity,
                 'activity_stack': self.activity_stack,
                 'background_services': self.background_services,
                 'width': self.width,
                 'height': self.height,
                 'views': self.views}
        return state

    def to_json(self):
        import json
        return json.dumps(self.to_dict(), indent=2)

    def __parse_views(self, raw_views):
        views = []
        if not raw_views or len(raw_views) == 0:
            return views
        for view_dict in raw_views:
            # # Simplify resource_id
            # resource_id = view_dict['resource_id']
            # if resource_id is not None and ":" in resource_id:
            #     resource_id = resource_id[(resource_id.find(":") + 1):]
            #     view_dict['resource_id'] = resource_id
            views.append(view_dict)
        return views

    def __assemble_view_tree(self, root_view, views):
        if not len(self.view_tree):  # bootstrap
            self.view_tree = copy.deepcopy(views[0])
            self.__assemble_view_tree(self.view_tree, views)
        else:
            children = list(enumerate(root_view["children"]))
            if not len(children):
                return
            for i, j in children:
                root_view["children"][i] = copy.deepcopy(self.views[j])
                self.__assemble_view_tree(root_view["children"][i], views)

    def __generate_view_strs(self):
        for view_dict in self.views:
            # self.__get_view_structure(view_dict)
            self.__get_view_str(view_dict)  # update

    @staticmethod
    def __calculate_depth(views):
        root_view = None
        for view in views:
            if DeviceState.__safe_dict_get(view, 'parent') == -1:
                root_view = view
                break
        DeviceState.__assign_depth(views, root_view, 0)

    @staticmethod
    def __assign_depth(views, view_dict, depth):
        view_dict['depth'] = depth
        for view_id in DeviceState.__safe_dict_get(view_dict, 'children', []):
            DeviceState.__assign_depth(views, views[view_id], depth + 1)

    def __get_state_str(self):
        state_str_raw = self.__get_state_str_raw()
        return md5(state_str_raw)

    def __get_state_str_raw(self):
        # view_signatures = set()
        view_signatures = list()  # update
        for view in self.views:
            view_signature = DeviceState.__get_view_signature(view)
            if view_signature:
                view_signatures.append(view_signature)
        # return "%s{%s}" % (self.foreground_activity, ",".join(sorted(view_signatures)))
        return "%s{%s}" % (self.foreground_activity, ",".join(view_signatures))  # update

    def __get_content_free_state_str(self):
        # Update: set() to list()
        view_signatures = list()
        for view in self.views:
            view_signature = DeviceState.__get_content_free_view_signature(view)
            if view_signature:
                view_signatures.append(view_signature)
        # Update: Cancel sorted()
        state_str = "%s{%s}" % (self.foreground_activity, ",".join(view_signatures))
        import hashlib
        return hashlib.md5(state_str.encode('utf-8')).hexdigest()

    def __get_search_content(self):
        """
        get a text for searching the state
        :return: str
        """
        words = [",".join(self.__get_property_from_all_views("resource_id")),
                 ",".join(self.__get_property_from_all_views("text"))]
        return "\n".join(words)

    def __get_property_from_all_views(self, property_name):
        """
        get the values of a property from all views
        :return: a list of property values
        """
        property_values = set()
        for view in self.views:
            property_value = DeviceState.__safe_dict_get(view, property_name, None)
            if property_value:
                property_values.add(property_value)
        return property_values

    def save2dir(self, output_dir=None):
        try:
            if output_dir is None:
                if self.device.output_dir is None:
                    return
                else:
                    output_dir = os.path.join(self.device.output_dir, "states")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            dest_state_json_path = "%s/state_%s.json" % (output_dir, self.tag)
            if self.device.adapters[self.device.minicap]:
                dest_screenshot_path = "%s/screen_%s.jpg" % (output_dir, self.tag)
            else:
                dest_screenshot_path = "%s/screen_%s.png" % (output_dir, self.tag)
            state_json_file = open(dest_state_json_path, "w")
            state_json_file.write(self.to_json())
            state_json_file.close()
            shutil.copyfile(self.screenshot_path, dest_screenshot_path)
            self.screenshot_path = dest_screenshot_path
            # if isinstance(self.screenshot_path, Image):
            #     self.screenshot_path.save(dest_screenshot_path)
        except Exception as e:
            self.device.logger.warning(e)

    def save_view_img(self, view_dict, output_dir=None):
        try:
            if output_dir is None:
                if self.device.output_dir is None:
                    return 0
                else:
                    output_dir = os.path.join(self.device.output_dir, "views")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            view_str = view_dict['view_str']
            if self.device.adapters[self.device.minicap]:
                view_file_path = "%s/view_%s.jpg" % (output_dir, view_str)
            else:
                view_file_path = "%s/view_%s.png" % (output_dir, view_str)
            # Add
            self.view_file_path = view_file_path
            if os.path.exists(view_file_path):
                return -1
            # Load the original image:
            view_bound = view_dict['bounds']
            original_img = Image.open(self.screenshot_path)
            # view bound should be in original image bound
            view_img = original_img.crop((min(original_img.width - 1, max(0, view_bound[0][0])),
                                          min(original_img.height - 1, max(0, view_bound[0][1])),
                                          min(original_img.width, max(0, view_bound[1][0])),
                                          min(original_img.height, max(0, view_bound[1][1]))))
            view_img.convert("RGB").save(view_file_path)
            return 1
        except Exception as e:
            self.device.logger.warning(e)

    def is_different_from(self, another_state):
        """
        compare this state with another
        @param another_state: DeviceState
        @return: boolean, true if this state is different from other_state
        """
        return self.state_str != another_state.state_str

    @staticmethod
    def __get_view_signature(view_dict):
        """
        get the signature of the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'signature' in view_dict:
            return view_dict['signature']

        view_text = DeviceState.__safe_dict_get(view_dict, 'text', "None")
        if view_text is None or len(view_text) > 50:
            view_text = "None"

        signature = "[class]%s[resource_id]%s[text]%s[%s,%s,%s]" % \
                    (DeviceState.__safe_dict_get(view_dict, 'class', "None"),
                     DeviceState.__safe_dict_get(view_dict, 'resource_id', "None"),
                     view_text,
                     DeviceState.__key_if_true(view_dict, 'enabled'),
                     DeviceState.__key_if_true(view_dict, 'checked'),
                     DeviceState.__key_if_true(view_dict, 'selected'))
        view_dict['signature'] = signature
        return signature

    @staticmethod
    def __get_content_free_view_signature(view_dict):
        """
        get the content-free signature of the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'content_free_signature' in view_dict:
            return view_dict['content_free_signature']
        content_free_signature = "[class]%s[resource_id]%s" % \
                                 (DeviceState.__safe_dict_get(view_dict, 'class', "None"),
                                  DeviceState.__safe_dict_get(view_dict, 'resource_id', "None"))
        view_dict['content_free_signature'] = content_free_signature
        return content_free_signature

    def __get_view_str(self, view_dict):
        """
        get a string which can represent the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'view_str' in view_dict:
            return view_dict['view_str']
        view_signature = DeviceState.__get_view_signature(view_dict)
        parent_strs = []
        for parent_id in self.get_all_ancestors(view_dict):
            parent_strs.append(DeviceState.__get_view_signature(self.views[parent_id]))
        parent_strs.reverse()
        child_strs = []
        for child_id in self.get_all_children(view_dict):
            child_strs.append(DeviceState.__get_view_signature(self.views[child_id]))
        child_strs.sort()
        # view_str = "State:%s\nActivity:%s\nSelf:%s\nParents:%s\nChildren:%s" % \ (
        # self.__get_content_free_state_str(), self.foreground_activity, view_signature, "//".join(parent_strs),
        # "||".join(child_strs))
        # Update view_str
        view_str = "State:%s\nActivity:%s\nSelf:%s\nParents:%s\nChildren:%s" % \
                   (self.__get_content_free_state_str(), self.foreground_activity, view_signature,
                    self.get_all_ancestors(view_dict), self.get_all_children(view_dict))
        import hashlib
        view_str = hashlib.md5(view_str.encode('utf-8')).hexdigest()
        view_dict['view_str'] = view_str
        return view_str

    def __get_view_structure(self, view_dict):
        """
        get the structure of the given view
        :param view_dict: dict, an element of list DeviceState.views
        :return: dict, representing the view structure
        """
        if 'view_structure' in view_dict:
            return view_dict['view_structure']
        width = DeviceState.get_view_width(view_dict)
        height = DeviceState.get_view_height(view_dict)
        class_name = DeviceState.__safe_dict_get(view_dict, 'class', "None")
        children = {}

        root_x = view_dict['bounds'][0][0]
        root_y = view_dict['bounds'][0][1]

        child_view_ids = self.__safe_dict_get(view_dict, 'children')
        if child_view_ids:
            for child_view_id in child_view_ids:
                child_view = self.views[child_view_id]
                child_x = child_view['bounds'][0][0]
                child_y = child_view['bounds'][0][1]
                relative_x, relative_y = child_x - root_x, child_y - root_y
                children["(%d,%d)" % (relative_x, relative_y)] = self.__get_view_structure(child_view)

        view_structure = {
            "%s(%d*%d)" % (class_name, width, height): children
        }
        view_dict['view_structure'] = view_structure
        return view_structure

    @staticmethod
    def __key_if_true(view_dict, key):
        return key if (key in view_dict and view_dict[key]) else ""

    @staticmethod
    def __safe_dict_get(view_dict, key, default=None):
        return view_dict[key] if (key in view_dict) else default

    @staticmethod
    def get_view_center(view_dict):
        """
        return the center point in a view
        @param view_dict: dict, an element of DeviceState.views
        @return: a pair of int
        """
        bounds = view_dict['bounds']
        return (bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2

    @staticmethod
    def get_view_width(view_dict):
        """
        return the width of a view
        @param view_dict: dict, an element of DeviceState.views
        @return: int
        """
        bounds = view_dict['bounds']
        return int(math.fabs(bounds[0][0] - bounds[1][0]))

    @staticmethod
    def get_view_height(view_dict):
        """
        return the height of a view
        @param view_dict: dict, an element of DeviceState.views
        @return: int
        """
        bounds = view_dict['bounds']
        return int(math.fabs(bounds[0][1] - bounds[1][1]))

    def get_all_ancestors(self, view_dict):
        """
        Get temp view ids of the given view's ancestors
        :param view_dict: dict, an element of DeviceState.views
        :return: list of int, each int is an ancestor node id
        """
        result = []
        parent_id = self.__safe_dict_get(view_dict, 'parent', -1)
        if 0 <= parent_id < len(self.views):
            result.append(parent_id)
            result += self.get_all_ancestors(self.views[parent_id])
        return result

    def get_all_children(self, view_dict):
        """
        Get temp view ids of the given view's children
        :param view_dict: dict, an element of DeviceState.views
        :return: set of int, each int is a child node id
        """
        children = self.__safe_dict_get(view_dict, 'children')
        if not children:
            return set()
        children = set(children)
        for child in children:
            children_of_child = self.get_all_children(self.views[child])
            # children.union(children_of_child)
            children = children.union(children_of_child)  # update
        return children

    def get_app_activity_depth(self, app):
        """
        Get the depth of the app's activity in the activity stack
        :param app: App
        :return: the depth of app's activity, -1 for not found
        """
        depth = 0
        for activity_str in self.activity_stack:
            if app.package_name in activity_str:
                return depth
            depth += 1
        return -1

    def get_enabled_view_ids(self):
        """
        Obtain all valid view ids excluding the navigation bar and invalid views with width or height less than or
        equal to 1
        """
        enabled_view_ids = []
        for view_dict in self.views:
            view_size = self.__safe_dict_get(view_dict, 'size').split('*')
            view_w = int(view_size[0])
            view_h = int(view_size[1])
            if self.__safe_dict_get(view_dict, 'enabled') and (view_w > 1 and view_h > 1) and \
                    self.__safe_dict_get(view_dict, 'resource_id') not in \
                    ['android:id/navigationBarBackground', 'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])
        return enabled_view_ids

    def get_nav_ids(self):
        """
        Obtain all navigation button ids (if exists)
        """
        nav_ids = set()
        nav_parent_id = None
        enabled_view_ids = self.enabled_view_ids[:]
        enabled_view_ids.reverse()
        device_height = self.device.get_height()
        for view_id in enabled_view_ids:
            view = self.views[view_id]
            view_class = self.__safe_dict_get(view, 'class')
            nav_class = 'LinearLayout' in view_class or 'TabWidget' in view_class or 'ViewGroup' in view_class \
                        or 'RadioGroup' in view_class or 'RecyclerView' in view_class or 'android.view.View' == \
                        view_class or 'CustomItemLayout' in view_class
            child_count = view['child_count']
            if self.__safe_dict_get(view, 'enabled') and nav_class and child_count >= 2:
                children_id = view['children']
                children_class = []
                children_bound_y1 = set()
                children_bound_y2 = set()
                nav_type = set()
                for child_id in children_id:
                    child_view = self.views[child_id]
                    view_size = child_view['size'].split("*")
                    view_w = int(view_size[0])
                    view_h = int(view_size[1])
                    if view_w <= 1 or view_h <= 1:
                        child_count -= 1
                        continue
                    children_class.append(child_view['class'])
                    children_bound_y1.add(child_view['bounds'][0][1])
                    children_bound_y2.add(child_view['bounds'][1][1])
                    nav_type.add(child_view['class'])
                if child_count == 2 and len(nav_type) == 1:
                    if len(children_bound_y1) == 1 and len(children_bound_y2) == 1:  # Horizontal arrangement
                        if 0 <= device_height - children_bound_y2.pop() <= 200 and \
                                0 <= device_height - children_bound_y1.pop() <= 350:  # Near the bottom of the screen
                            nav_parent_id = view_id
                elif child_count > 2 and len(nav_type) <= 2:
                    if len(children_bound_y1) <= 2 and len(children_bound_y2) <= 2:  # Horizontal arrangement
                        min_len = min(len(children_bound_y1), len(children_bound_y2))
                        for index in range(min_len):
                            if 0 <= device_height - children_bound_y2.pop() <= 200 and 0 <= device_height - \
                                    children_bound_y1.pop() <= 350:  # Near the bottom of the screen
                                nav_parent_id = view_id
                            else:
                                nav_parent_id = None
                                break
            if nav_parent_id:
                break
        if nav_parent_id:
            view_parent = self.views[nav_parent_id]
            all_children_ids = self.get_all_children(view_parent)
            nav_ids = all_children_ids
            nav_ids.add(nav_parent_id)
        return nav_ids

    def get_possible_input(self, explored_states=None):
        """
        Get a list of possible input events for this state
        :return: list of InputEvent
        """
        if self.possible_events:
            return [] + self.possible_events

        possible_events = []
        enabled_view_ids = self.enabled_view_ids
        touch_exclude_view_ids = set()

        # Search for confirmation, close, or red packet activation events
        if explored_states is not None:
            specific_events = self.get_specific_input(explored_states)
            if len(specific_events) > 0:
                return specific_events

        # Explore UI states of the app
        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'scrollable'):
                view_class = self.__safe_dict_get(self.views[view_id], 'class')
                if view_class and 'HorizontalScrollView' not in view_class:
                    possible_events.append(ScrollEvent(view=self.views[view_id], direction="DOWN"))
                    # possible_events.append(ScrollEvent(view=self.views[view_id], direction="UP"))
                    # possible_events.append(ScrollEvent(view=self.views[view_id], direction="RIGHT"))
                    # possible_events.append(ScrollEvent(view=self.views[view_id], direction="LEFT"))
                    break

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'clickable'):
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids = touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'long_clickable'):
                possible_events.append(LongTouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids = touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        # Search other children nodes that are not clickable
        for view_id in enabled_view_ids:
            if view_id in touch_exclude_view_ids:
                continue
            children = self.__safe_dict_get(self.views[view_id], 'children')
            if children and len(children) > 0:
                continue
            possible_events.append(TouchEvent(view=self.views[view_id]))

        # For old Android navigation bars
        # possible_events.append(KeyEvent(name="MENU"))

        self.possible_events = possible_events
        return [] + possible_events

    def get_search_input(self):
        """
        Get a list of clickable events in this state for searching the navigation bar
        :return: list of InputEvent
        """
        possible_events = []
        enabled_view_ids = self.enabled_view_ids
        touch_exclude_view_ids = set()

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'clickable'):
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids = touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        # Search other children nodes that are not clickable
        for view_id in enabled_view_ids:
            if view_id in touch_exclude_view_ids:
                continue
            children = self.__safe_dict_get(self.views[view_id], 'children')
            if children and len(children) > 0:
                continue
            possible_events.append(TouchEvent(view=self.views[view_id]))

        self.possible_events = possible_events
        return possible_events

    def get_specific_input(self, explored_states):
        """
        Get a list of specific input events for this state (confirm, close)
        :return: list of InputEvent
        """
        specific_events = []
        enabled_view_ids = self.enabled_view_ids

        # 1 Search for red packet view in the current state.
        if self.state_str not in explored_states:
            if self.identify_red_packet():
                specific_events.append('red_packet')
                return specific_events

        # Restore to default
        with open('DetectReck/output/dialog.txt', "w+") as f:
            f.write('')
        with open('DetectReck/output/custom_popup.txt', "w+") as f:
            f.write('')
        with open('DetectReck/output/popup_window.txt', "w+") as f:
            f.write('')
        with open('DetectReck/output/third-party_popup.txt', "w+") as f:
            f.write('')
        with open('DetectReck/output/popup_image_position.txt', "w+") as f:
            f.write('')

        # 2 Check the confirmation page
        with open('DetectReck/resources/keywords/confirm.txt', "r+", encoding='UTF-8') as f:
            confirm_buttons = f.read().split('\n')
        for view_id in enabled_view_ids:
            view = self.views[view_id]
            view_text = view['text']
            if view_text:
                import re
                view_text = re.findall('[\u4e00-\u9fa5a-zA-Z]+', view_text, re.S)
                view_text = ''.join(view_text)
                if len(view['children']) == 0 and (view['clickable'] or self.views[view['parent']]['clickable']):
                    if (view_text.find("同意") != -1 and view_text.find('不同意') == -1 or view_text.find("知道") != -1) \
                            and len(view_text) < 8 or view_text in confirm_buttons:
                        self.logger.info("Find the confirmation button (view = %s)." % view['view_str'])
                        specific_events.append('confirm')
                        specific_events.append(TouchEvent(view=view))
                        return specific_events

        # 3 Check the close button of the pop-up or dialog box
        for view_id in enabled_view_ids:
            view = self.views[view_id]
            resource_id = view['resource_id']
            content_desc = view['content_description']
            res_id_status = resource_id is not None and ('close' in resource_id.lower() or 'skip' in resource_id.lower()
                                                         or 'cancel' in resource_id.lower())  # or 'dislike' in resource_id.lower()
            con_desc_status = content_desc is not None and content_desc == '关闭'
            if len(view['children']) == 0 and (res_id_status or con_desc_status):
                self.logger.info("Find the close button (view = %s)." % view['view_str'])
                specific_events.append('close')
                specific_events.append(TouchEvent(view=view))
                return specific_events

        return specific_events

    def get_red_packet_events(self):
        """
        Get a list of related input events that might trigger red packets according to text similarity analysis
        :return: list of InputEvent
        """
        all_possible_events = []
        red_packet_events = []
        other_events = []
        enabled_view_ids = self.enabled_view_ids
        nav_ids = self.get_nav_ids()

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'clickable') and view_id not in nav_ids:
                file_path = 'DetectReck/resources/keywords/red_packet_event.txt'
                with open(file_path, "r+", encoding='UTF-8') as f:
                    event_keywords = f.read().split('\n')
                view_text = self.views[view_id]['text']
                view_desc = self.views[view_id]['content_description']
                if view_text or view_desc:
                    if view_text:
                        text = view_text
                    else:
                        text = view_desc
                else:
                    all_children_ids = self.get_all_children(self.views[view_id])
                    child_text = ''
                    for child_id in all_children_ids:
                        view_text = self.views[child_id]['text']
                        view_desc = self.views[child_id]['content_description']
                        if view_text:
                            child_text += view_text
                        elif view_desc:
                            child_text += view_desc
                    text = child_text

                strs = re.findall('[\u4e00-\u9fa5]', text)
                text = ''.join(strs)
                if text:
                    # print('view %d text:' % view_id, text)
                    match_status = False
                    for word in event_keywords:
                        if word in text:
                            match_status = True
                            red_packet_events.append(TouchEvent(view=self.views[view_id]))
                            break
                    if not match_status:
                        other_events.append(TouchEvent(view=self.views[view_id]))
                else:
                    other_events.append(TouchEvent(view=self.views[view_id]))

        if len(red_packet_events) > MIN_NUM_EXPLORE_EVENTS:  # Return all possible red packet events
            return red_packet_events
        else:
            all_possible_events = red_packet_events + other_events

        if len(all_possible_events) == 0:
            for view_id in enabled_view_ids:
                if view_id in nav_ids:
                    continue
                children = self.__safe_dict_get(self.views[view_id], 'children')
                if children and len(children) > 0:
                    continue
                all_possible_events.append(TouchEvent(view=self.views[view_id]))

        if len(all_possible_events) > MIN_NUM_EXPLORE_EVENTS:  # Return the first MIN_NUM_EXPLORE_EVENTS events
            all_possible_events = all_possible_events[:MIN_NUM_EXPLORE_EVENTS]

        return all_possible_events

    # Identify red packet from all pop-ups
    def identify_red_packet(self):
        # Identify pop-up windows (dialog, popup window, custom popup, third-party popup) via an Android Xposed module.
        with open('DetectReck/output/dialog.txt', 'r', encoding='UTF-8') as f:
            dialog_text = f.read()
        with open('DetectReck/output/custom_popup.txt', 'r', encoding='UTF-8') as f:
            custom_popup_text = f.read()
        with open('DetectReck/output/popup_window.txt', 'r', encoding='UTF-8') as f:
            popup_window_text = f.read()
        with open('DetectReck/output/third-party_popup.txt', 'r', encoding='UTF-8') as f:
            third_popup_text = f.read()
        with open('DetectReck/output/popup_image_position.txt', 'r', encoding='UTF-8') as f:
            popup_image_positions = f.read()

        # Restore to default
        if dialog_text != '':
            with open('DetectReck/output/dialog.txt', "w+") as f:
                f.write('')
        if custom_popup_text != '':
            with open('DetectReck/output/custom_popup.txt', "w+") as f:
                f.write('')
        if popup_window_text != '':
            with open('DetectReck/output/popup_window.txt', "w+") as f:
                f.write('')
        if third_popup_text != '':
            with open('DetectReck/output/third-party_popup.txt', "w+") as f:
                f.write('')
        if popup_image_positions != '':
            with open('DetectReck/output/popup_image_position.txt', "w+") as f:
                f.write('')

        # Identify whether a pop-up view exist in the current state
        if dialog_text != '' and '#dialog#' in dialog_text:
            text = dialog_text.replace('#dialog#\n', '')
            if self.check_popup_view('dialog', text):
                return True

        if custom_popup_text != '' and '#custom popup#' in custom_popup_text:
            text = custom_popup_text.replace('#custom popup#\n', '')
            if self.check_popup_view('custom popup', text):
                return True

        if popup_window_text != '' and '#popup window#' in popup_window_text:
            text = popup_window_text.replace('#popup window#\n', '')
            if self.check_popup_view('popup window', text):
                return True

        if third_popup_text != '' and '#third-party popup#' in third_popup_text:
            text = third_popup_text.replace('#third-party popup#\n', '')
            if self.check_popup_view('third-party popup', text):
                return True

        # If the pop-up is an image
        if popup_image_positions != '' and '#pop-up image#' in popup_image_positions:
            pos_info = popup_image_positions.replace('#pop-up image#:', '').strip()
            if self.check_popup_image('pop-up image', pos_info):
                return True

        # If the current UI is embedded in the WebView
        if self.check_web_view():
            return True

        return False

    # Analyze the text in the WebView ().
    def check_web_view(self):
        enabled_view_ids = self.enabled_view_ids
        for view_id in enabled_view_ids:
            view = self.views[view_id]
            if view['class'] == "android.webkit.WebView" and view['scrollable']:
                # Save the web view locally
                dst_web_path = os.path.join(self.device.output_dir, "candidates/pop-ups/webview-embedded/")
                original_image_path = self.screenshot_path
                # print("########## Screenshot path: ", original_image_path)
                copy_file(original_image_path, dst_web_path)
                # Crop a sub-image from the screenshot
                bounds = view['bounds']
                elems = [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]]
                cropped_image_path = crop_sub_image(elems, original_image_path, dst_web_path)
                # print("########## Cropped image path: ", cropped_image_path)

                # embedded_text = self.extract_webview_text(view)  # Extract text from the UI components
                # print("#All text in the WebView:\n", embedded_text)
                # if check_reck_text(embedded_text):
                #     self.logger.info("Red packet is found.")
                #     # Save the red packet image locally
                #     dst_reck_path = os.path.join(self.device.output_dir, "candidates/red_packets/")
                #     copy_file(cropped_image_path, dst_reck_path)
                #     return True

                words = extract_image_text(cropped_image_path)  # OCR
                if words is not None:
                    # print('Word Results：', words)
                    embedded_text = ''
                    for word in words:
                        embedded_text += word['words'] + '\n'
                    print("#All text in the WebView:\n", embedded_text)

                    if check_reck_text(embedded_text):
                        self.logger.info("Red packet is found.")
                        # Save the red packet locally
                        dst_reck_path = os.path.join(self.device.output_dir, "candidates/red_packets/")
                        copy_file(cropped_image_path, dst_reck_path)
                        return True

                return False

    # Analyze the text in the pop-up view.
    def check_popup_view(self, tag, text):
        is_red_packet = False

        self.logger.info(f'Find a {tag}!')
        # Save the pop-up view locally
        dst_popup_path = os.path.join(self.device.output_dir, "candidates/pop-ups/text-embedded/")
        # print("########## screenshot_path: ", self.screenshot_path)
        copy_file(self.screenshot_path, dst_popup_path)

        self.logger.info(f'Checking whether the {tag} is a red packet...')
        print(f'#Text in the {tag}: {text}')

        if check_reck_text(text):
            is_red_packet = True
            self.logger.info("Red packet is found.")

            # Save the red packet view locally
            dst_reck_path = os.path.join(self.device.output_dir, "candidates/red_packets/")
            copy_file(self.screenshot_path, dst_reck_path)
        else:
            self.logger.info(f'The {tag} is not a red packet.')

        return is_red_packet

    # Extract and analyze the text in the pop-up image.
    def check_popup_image(self, tag, pos_info):
        is_red_packet = False

        self.logger.info(f'Find a {tag}!')
        positions = pos_info.split('\n')
        # print(positions)
        for pos in positions:
            elems = [int(x) for x in pos.split(',')]
            print("Image Coordinates: ", elems)
            # Save the pop-up image locally
            dst_popup_path = os.path.join(self.device.output_dir, "candidates/pop-ups/image-embedded/")
            original_image_path = self.screenshot_path
            # print("########## screenshot_path: ", original_image_path)
            copy_file(original_image_path, dst_popup_path)
            # Crop a sub-image from the screenshot
            cropped_image_path = crop_sub_image(elems, original_image_path, dst_popup_path)
            # print("########## Cropped image path: ", cropped_image_path)
            # Extract text content in the image by OCR
            words = extract_image_text(cropped_image_path)
            if words is not None:
                # print('Word Results：', words)
                image_text = ''
                for word in words:
                    image_text += word['words'] + '\n'
                # print("#All text in the pop-up image:\n", image_text)

                if check_reck_text(image_text):
                    is_red_packet = True
                    self.logger.info("Red packet is found.")

                    # Save the red packet image locally
                    dst_reck_path = os.path.join(self.device.output_dir, "candidates/red_packets/")
                    copy_file(cropped_image_path, dst_reck_path)

                    return is_red_packet
                else:
                    print(f'The {tag} is not a red packet.')
            # time.sleep(1)
        return is_red_packet

    # Extract all text embedded in the WebView.
    def extract_webview_text(self, view):
        children_ids = self.get_all_children(view)
        all_text = ''
        for child_id in children_ids:
            child_view = self.views[child_id]
            if child_view['class'] in ['android.view.View', 'android.widget.TextView'] and child_view['text']:
                text = child_view['text'].strip()
                all_text += (text + '\n')
        return all_text.strip()


# Check whether the text is related to a red packet.
def check_reck_text(text):
    token = text.replace('\n', '').replace(' ', '')
    if token != '':
        # Match the most similar red packet text and get the corresponding score
        model = SentenceTransformer('DetectReck/resources/paraphrase-multilingual-MiniLM-L12-v2')
        max_score, sim_text = get_sim_score(model, token)
        print("Maximum similarity score and most similar red packet text: (%.2f, %s)." % (max_score, sim_text))

        if round(max_score, 2) >= numpy.float32(0.6):
            print("Text matching successful!")
            return True
        else:
            # Match the open button of the red packet if no red packet text exists
            words = text.replace(' ', '').split('\n')
            with open('DetectReck/resources/keywords/red_packet_btn.txt', "r", encoding='UTF-8') as f:
                btn_keywords = f.read().split('\n')
            for word in words:
                if word in btn_keywords:
                    print("The open button matching successful!")
                    return True
    return False


# Copy the file to the specified folder
def copy_file(srcfile, dstpath):
    if not os.path.isfile(srcfile):
        print("Warning: %s not exist!" % srcfile)
    else:
        fpath, fname = os.path.split(srcfile)
        if not os.path.exists(dstpath):
            os.makedirs(dstpath)
        # tag = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        # new_name = 'red-packet-' + tag + '.' + fname.split(".")[-1]
        shutil.copyfile(srcfile, dstpath + fname)


# Crop a sub-image according to coordinate positions.
def crop_sub_image(elems, original_image_path, output_dir):
    original_img = Image.open(original_image_path)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    # tag = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    # cropped_image_path = "%simage_%s.jpg" % (output_dir, tag)
    fpath, fname = os.path.split(original_image_path)
    image_name = fname.replace('screen', 'image')
    cropped_image_path = "%s%s" % (output_dir, image_name)
    x1, y1, x2, y2 = elems[0], elems[1], elems[2], elems[3]
    box = (x1, y1, x2, y2)
    cropped_image = original_img.crop(box)
    cropped_image.convert("RGB").save(cropped_image_path)
    return cropped_image_path


# Extract all text embedded in the image by OCR.
def extract_image_text(image_path):
    with open(image_path, 'rb') as fp:
        image = fp.read()
    words = None
    # OCR API
    result = get_client().basicGeneral(image)
    print("OCR Result: ", result)
    if 'words_result' in result:
        words_num = result['words_result_num']
        if words_num > 0:
            words = result['words_result']
    return words
