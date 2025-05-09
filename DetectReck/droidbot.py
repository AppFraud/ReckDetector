# This file contains the main class of droidbot
# It can be used after AVD was started, app was installed, and adb had been set up properly
# By configuring and creating a droidbot instance,
# droidbot will start interacting with Android in AVD like a human
import logging
import os
import socket
import sys
import traceback

import pkg_resources
import shutil
from threading import Timer

from .device import Device
from .app import App
from .env_manager import AppEnvManager
from .input_manager import InputManager


class DroidBot(object):
    """
    The main class of droidbot
    """
    # this is a single instance class
    instance = None

    def __init__(self,
                 app_path=None,
                 device_serial=None,
                 is_emulator=False,
                 output_dir=None,
                 env_policy=None,
                 policy_name=None,
                 random_input=False,
                 script_path=None,
                 event_count=None,
                 event_interval=None,
                 timeout=None,
                 keep_app=None,
                 keep_env=False,
                 cv_mode=False,
                 debug_mode=False,
                 profiling_method=None,
                 grant_perm=False,
                 enable_accessibility_hard=False,
                 master=None,
                 humanoid=None,
                 ignore_ad=False,
                 replay_output=None):
        """
        initiate droidbot with configurations
        :return:
        """
        logging.basicConfig(level=logging.DEBUG if debug_mode else logging.INFO)

        self.logger = logging.getLogger('DroidBot')
        DroidBot.instance = self

        self.output_dir = output_dir
        if output_dir is not None:
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir)
            html_index_path = pkg_resources.resource_filename("DetectReck", "resources/index.html")
            stylesheets_path = pkg_resources.resource_filename("DetectReck", "resources/stylesheets")
            target_stylesheets_dir = os.path.join(output_dir, "stylesheets")
            if os.path.exists(target_stylesheets_dir):
                shutil.rmtree(target_stylesheets_dir)
            shutil.copy(html_index_path, output_dir)
            shutil.copytree(stylesheets_path, target_stylesheets_dir)

        self.timeout = timeout
        self.timer = None
        self.keep_env = keep_env
        self.keep_app = keep_app

        self.device = None
        self.app = None
        self.droidbox = None
        self.env_manager = None
        self.input_manager = None
        self.enable_accessibility_hard = enable_accessibility_hard
        self.humanoid = humanoid
        self.ignore_ad = ignore_ad
        self.replay_output = replay_output

        self.enabled = True

        self.server_sock = None

        try:
            # initialize Device
            self.device = Device(
                device_serial=device_serial,
                is_emulator=is_emulator,
                output_dir=self.output_dir,
                cv_mode=cv_mode,
                grant_perm=grant_perm,
                enable_accessibility_hard=self.enable_accessibility_hard,
                humanoid=self.humanoid,
                ignore_ad=ignore_ad)

            # initialize App
            self.app = App(app_path, output_dir=self.output_dir)

            # initialize AppEnvManager
            self.env_manager = AppEnvManager(
                device=self.device,
                app=self.app,
                env_policy=env_policy)

            # initialize InputManager
            self.input_manager = InputManager(
                device=self.device,
                app=self.app,
                policy_name=policy_name,
                random_input=random_input,
                event_count=event_count,
                event_interval=event_interval,
                script_path=script_path,
                profiling_method=profiling_method,
                master=master,
                replay_output=replay_output)

        except Exception:
            import traceback
            traceback.print_exc()
            self.stop()
            sys.exit(-1)

    @staticmethod
    def get_instance():
        if DroidBot.instance is None:
            print("Error: DroidBot is not initiated!")
            sys.exit(-1)
        return DroidBot.instance

    def start(self):
        """
        start interacting
        :return:
        """
        if not self.enabled:
            return
        self.logger.info("Starting DroidBot")
        try:
            # 如果设置超时关闭则启动计时器
            if self.timeout > 0:
                self.timer = Timer(self.timeout, self.stop)
                self.timer.start()

            # Set connections on this device
            self.device.set_up()

            # Add Socket Server
            import threading
            listen_thread = threading.Thread(target=self.start_socket_server)
            listen_thread.start()

            if not self.enabled:
                return

            # Establish connections on this device
            self.device.connect()

            if not self.enabled:
                return
            # install an app to device
            self.device.install_app(self.app)

            if not self.enabled:
                return
            self.env_manager.deploy()

            if not self.enabled:
                return
            # droidbox前面未实例化（None）
            if self.droidbox is not None:
                self.droidbox.set_apk(self.app.app_path)
                self.droidbox.start_unblocked()
                self.input_manager.start()
                self.droidbox.stop()
                self.droidbox.get_output()
            else:
                # start sending event
                self.input_manager.start()
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt.")
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            self.stop()
            sys.exit(-1)

        self.stop()
        self.logger.info("DroidBot Stopped")

    def stop(self):
        self.enabled = False
        if self.timer and self.timer.isAlive():
            self.timer.cancel()
        if self.env_manager:
            self.env_manager.stop()
        if self.input_manager:
            self.input_manager.stop()
        if self.droidbox:
            self.droidbox.stop()
        if self.device:
            self.device.disconnect()
        if not self.keep_env:
            self.device.tear_down()
        if not self.keep_app:
            self.device.uninstall_app(self.app)
        if hasattr(self.input_manager.policy, "master") and \
                self.input_manager.policy.master:
            import xmlrpc.client
            proxy = xmlrpc.client.ServerProxy(self.input_manager.policy.master)
            proxy.stop_worker(self.device.serial)

        self.server_sock.close()

    def start_socket_server(self):
        print("Start Socket Server...")
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.server_sock.bind(("0.0.0.0", 9999))
            self.server_sock.listen(5)
            # while self.device.connected:
            while self.enabled:
                connection, address = self.server_sock.accept()
                connection.settimeout(5)
                message = connection.recv(2048)
                if not isinstance(message, str):
                    message = message.decode('utf-8', errors='ignore')
                # print(message)

                # Save message to files
                if '#dialog#' in message:
                    with open('DetectReck/output/dialog.txt', "w+", encoding="UTF-8") as f:
                        f.write(message)
                elif '#popup window#' in message:
                    with open('DetectReck/output/popup_window.txt', "w+", encoding="UTF-8") as f:
                        f.write(message)
                elif '#custom popup#' in message:
                    with open('DetectReck/output/custom_popup.txt', "w+", encoding="UTF-8") as f:
                        f.write(message)
                elif '#third-party popup#' in message:
                    with open('DetectReck/output/third-party_popup.txt', "w+", encoding="UTF-8") as f:
                        f.write(message)
                elif '#pop-up image#' in message:
                    with open('DetectReck/output/popup_image_position.txt', "a+", encoding="UTF-8") as f:
                        f.write(message + '\n')
        except socket.error:
            if self.enabled:
                traceback.print_exc()


class DroidBotException(Exception):
    pass
