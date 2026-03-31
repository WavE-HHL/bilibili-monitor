"""
Kivy版本的B站评论监控器
适配Android系统，提供图形界面
"""
import json
import os
import threading
import logging
from datetime import datetime
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.switch import Switch
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.metrics import dp

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入核心模块
from config_manager import load_config, save_config_json, validate_config
from monitor import check_once, run_scheduler
from state_store import reset_state, get_all_last_rpid

# 配置文件路径（适配Android）
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


class BilibiliMonitorApp(App):
    """B站评论监控器Kivy应用"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = load_config()
        self.monitor_thread = None
        self.monitoring = False
        self.log_content = []
        self.log_scroll = None

    def build(self):
        """构建应用界面"""
        # 设置窗口大小（桌面端）
        Window.size = (dp(400), dp(700))

        # 主布局
        main_layout = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(10))

        # 标题
        title = Label(
            text='B站评论监控器',
            size_hint_y=None,
            height=dp(50),
            font_size=dp(24),
            bold=True
        )
        main_layout.add_widget(title)

        # 配置区域
        config_layout = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(300))
        main_layout.add_widget(config_layout)

        # Server酱配置
        serverchan_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40))
        serverchan_label = Label(text='Server酱SendKey:', size_hint_x=0.4, font_size=dp(14))
        self.sendkey_input = TextInput(
            text=self.config.get('sendkey', ''),
            multiline=False,
            font_size=dp(14),
            password=True
        )
        serverchan_layout.add_widget(serverchan_label)
        serverchan_layout.add_widget(self.sendkey_input)
        config_layout.add_widget(serverchan_layout)

        # 检查间隔
        interval_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40))
        interval_label = Label(text='检查间隔(分钟):', size_hint_x=0.4, font_size=dp(14))
        self.interval_input = TextInput(
            text=str(self.config.get('interval_minutes', 30)),
            multiline=False,
            font_size=dp(14)
        )
        interval_layout.add_widget(interval_label)
        interval_layout.add_widget(self.interval_input)
        config_layout.add_widget(interval_layout)

        # 视频配置区域
        video_label = Label(
            text='视频配置 (BV号 | 标题 | UP主名称 | UP主UID)',
            size_hint_y=None,
            height=dp(30),
            font_size=dp(16),
            bold=True
        )
        config_layout.add_widget(video_label)

        self.video_inputs = []
        videos = self.config.get('videos', [])
        for i, video in enumerate(videos[:2], 1):  # 最多2个视频
            video_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40), spacing=dp(5))
            bvid_input = TextInput(
                text=video.get('bvid', ''),
                multiline=False,
                hint_text=f'视频{i} BV号',
                font_size=dp(10),
                size_hint_x=0.3
            )
            title_input = TextInput(
                text=video.get('title', f'视频{i}'),
                multiline=False,
                hint_text='标题',
                font_size=dp(10),
                size_hint_x=0.2
            )
            upname_input = TextInput(
                text=video.get('up_name', ''),
                multiline=False,
                hint_text='UP主名称',
                font_size=dp(10),
                size_hint_x=0.25
            )
            uid_input = TextInput(
                text=video.get('up_uid', ''),
                multiline=False,
                hint_text='UP主UID',
                font_size=dp(10),
                size_hint_x=0.25
            )
            video_layout.add_widget(bvid_input)
            video_layout.add_widget(title_input)
            video_layout.add_widget(upname_input)
            video_layout.add_widget(uid_input)
            config_layout.add_widget(video_layout)
            self.video_inputs.append((bvid_input, title_input, upname_input, uid_input))

        # 按钮区域
        button_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(10))

        self.save_btn = Button(text='保存配置', font_size=dp(16))
        self.save_btn.bind(on_press=self.save_config)
        button_layout.add_widget(self.save_btn)

        self.monitor_btn = Button(text='开始监控', font_size=dp(16))
        self.monitor_btn.bind(on_press=self.toggle_monitor)
        button_layout.add_widget(self.monitor_btn)

        self.check_btn = Button(text='立即检查', font_size=dp(16))
        self.check_btn.bind(on_press=self.check_once)
        button_layout.add_widget(self.check_btn)

        main_layout.add_widget(button_layout)

        # 状态显示区域
        self.status_label = Label(
            text='状态: 未启动',
            size_hint_y=None,
            height=dp(30),
            font_size=dp(14)
        )
        main_layout.add_widget(self.status_label)

        # 日志区域
        log_label = Label(
            text='运行日志',
            size_hint_y=None,
            height=dp(30),
            font_size=dp(16),
            bold=True
        )
        main_layout.add_widget(log_label)

        self.log_text = TextInput(
            text='',
            readonly=True,
            font_size=dp(11),
            background_color=(0.95, 0.95, 0.95, 1)
        )
        log_scroll = ScrollView()
        log_scroll.add_widget(self.log_text)
        main_layout.add_widget(log_scroll)
        self.log_scroll = log_scroll

        # 重置按钮
        reset_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40), spacing=dp(10))
        reset_state_btn = Button(text='重置监控记录', font_size=dp(14))
        reset_state_btn.bind(on_press=self.reset_monitor_state)
        reset_layout.add_widget(reset_state_btn)

        view_state_btn = Button(text='查看监控记录', font_size=dp(14))
        view_state_btn.bind(on_press=self.view_state)
        reset_layout.add_widget(view_state_btn)

        main_layout.add_widget(reset_layout)

        # 启动日志更新定时器
        Clock.schedule_interval(self.update_log_display, 1.0)

        return main_layout

    def save_config(self, instance):
        """保存配置"""
        try:
            # 收集配置
            config = {
                'sendkey': self.sendkey_input.text.strip(),
                'interval_minutes': int(self.interval_input.text),
                'cookie': self.config.get('cookie', ''),
                'max_pages_per_check': self.config.get('max_pages_per_check', 5),
                'notify_on_start': self.config.get('notify_on_start', True),
                'videos': []
            }

            # 收集视频配置
            for bvid_input, title_input, upname_input, uid_input in self.video_inputs:
                bvid = bvid_input.text.strip()
                if bvid:
                    config['videos'].append({
                        'bvid': bvid,
                        'title': title_input.text.strip() or bvid,
                        'up_name': upname_input.text.strip() or '未命名UP主',
                        'up_uid': uid_input.text.strip()
                    })

            # 验证配置
            errors = validate_config(config)
            if errors:
                self.show_popup('配置错误', '\n'.join(errors))
                return

            # 保存配置
            if save_config_json(config):
                self.config = config
                self.add_log('✅ 配置已保存')
                self.show_popup('成功', '配置保存成功！')
            else:
                self.show_popup('错误', '配置保存失败')
        except ValueError:
            self.show_popup('错误', '检查间隔必须是数字')
        except Exception as e:
            self.add_log(f'❌ 保存配置失败: {e}')
            self.show_popup('错误', f'保存配置失败: {e}')

    def toggle_monitor(self, instance):
        """切换监控状态"""
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        """开始监控"""
        try:
            # 验证配置
            errors = validate_config(self.config)
            if errors:
                self.show_popup('配置错误', '\n'.join(errors))
                return

            self.monitoring = True
            self.monitor_btn.text = '停止监控'
            self.status_label.text = '状态: 监控中...'

            # 在后台线程运行监控
            def run():
                try:
                    run_scheduler()
                except Exception as e:
                    self.add_log(f'❌ 监控异常: {e}')
                    self.monitoring = False
                    self.monitor_btn.text = '开始监控'
                    self.status_label.text = '状态: 已停止'

            self.monitor_thread = threading.Thread(target=run, daemon=True)
            self.monitor_thread.start()

            self.add_log('🚀 监控已启动')
        except Exception as e:
            self.add_log(f'❌ 启动监控失败: {e}')
            self.show_popup('错误', f'启动监控失败: {e}')

    def stop_monitor(self):
        """停止监控"""
        self.monitoring = False
        self.monitor_btn.text = '开始监控'
        self.status_label.text = '状态: 已停止'
        self.add_log('⏹️ 监控已停止')

    def check_once(self, instance):
        """执行一次检查"""
        try:
            # 验证配置
            errors = validate_config(self.config)
            if errors:
                self.show_popup('配置错误', '\n'.join(errors))
                return

            self.add_log('🔍 开始检查...')
            check_once()
            self.add_log('✅ 检查完成')
        except Exception as e:
            self.add_log(f'❌ 检查失败: {e}')
            self.show_popup('错误', f'检查失败: {e}')

    def reset_monitor_state(self, instance):
        """重置监控记录"""
        try:
            reset_state()
            self.add_log('🗑️ 监控记录已重置')
            self.show_popup('成功', '监控记录已重置！\n下次监控将重新开始计数。')
        except Exception as e:
            self.add_log(f'❌ 重置失败: {e}')
            self.show_popup('错误', f'重置失败: {e}')

    def view_state(self, instance):
        """查看监控记录"""
        try:
            state = get_all_last_rpid()
            if not state:
                msg = '暂无监控记录'
            else:
                lines = ['当前监控记录:']
                for bvid, rpid in state.items():
                    lines.append(f'{bvid}: {rpid}')
                msg = '\n'.join(lines)
            self.show_popup('监控记录', msg)
        except Exception as e:
            self.add_log(f'❌ 查看记录失败: {e}')
            self.show_popup('错误', f'查看记录失败: {e}')

    def add_log(self, message):
        """添加日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_content.append(f'[{timestamp}] {message}')
        if len(self.log_content) > 100:  # 限制日志条数
            self.log_content = self.log_content[-100:]

    def update_log_display(self, dt):
        """更新日志显示"""
        if self.log_content:
            self.log_text.text = '\n'.join(self.log_content)
            # 自动滚动到底部
            if hasattr(self.log_text, 'cursor):
                self.log_text.cursor = (len(self.log_text.text), 0)

    def show_popup(self, title, content):
        """显示弹窗"""
        popup = Popup(
            title=title,
            content=Label(text=content, font_size=dp(14)),
            size_hint=(0.8, 0.5)
        )
        popup.open()

    def on_stop(self):
        """应用停止时的清理"""
        if self.monitoring:
            self.stop_monitor()


if __name__ == '__main__':
    BilibiliMonitorApp().run()
