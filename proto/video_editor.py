#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频编辑软件 - 主程序
支持视频加载、预览、剪辑、导出等功能
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import threading
import time
from pathlib import Path
import math
from datetime import datetime, timedelta, timezone
import bisect
import subprocess
import shutil
import xml.dom.minidom
import struct
import tempfile
import json
import re
import signal

# 尝试导入numpy用于错误处理
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("警告: 未安装 numpy，某些功能将受限。请运行: pip install numpy")

# 尝试导入视频处理库
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("警告: 未安装 opencv-python，视频播放功能将不可用。请运行: pip install opencv-python")

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("警告: 未安装 Pillow，视频显示功能将受限。请运行: pip install Pillow")

# 尝试导入 matplotlib 用于绘制图表
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("警告: 未安装 matplotlib，速度曲线图将不可用。请运行: pip install matplotlib")

# 设置中文字体支持
import platform
if platform.system() == 'Windows':
    import tkinter.font as tkFont
    default_font = ('Microsoft YaHei', 9)
elif platform.system() == 'Darwin':  # macOS
    default_font = ('PingFang SC', 11)
else:  # Linux
    default_font = ('WenQuanYi Micro Hei', 10)


class VideoEditorApp:
    """视频编辑器主应用类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("视频编辑器")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600)
        
        # 视频相关变量
        self.video_path = None
        self.video_info = {}
        self.video_creation_time = None # 视频创建时间
        self.clips = []  # 剪辑片段列表
        self.timeline_thumbnails = {} # 时间轴缩略图 {time_sec: photo_image}
        self.thumbnail_thread = None # 缩略图生成线程
        
        # GPX 数据
        self.gpx_data = None  # 格式: {'segments': [(start_time, end_time, speed), ...]}
        self.gpx_offset = 0.0  # GPX时间偏移（秒）
        self.track_thumbnail = None # 轨迹缩略图
        self.track_transform = None # 坐标转换参数
        
        # 轨迹预览缩放和平移
        self.align_zoom_scale = 1.0
        self.align_offset_x = 0.0
        self.align_offset_y = 0.0
        self.align_drag_start = None
        
        # 调试信息
        self.debug_info = {}
        
        # 播放相关变量
        self.cap = None  # OpenCV VideoCapture 对象
        self.playing = False  # 是否正在播放
        self.current_frame_pos = 0  # 当前帧位置
        self.total_frames = 0  # 总帧数
        self.current_frame_image = None  # 当前帧图像
        self.play_thread = None  # 播放线程
        self.audio_proc = None
        
        # 拖拽状态变量
        self.is_dragging_progress = False
        self.was_playing_before_drag = False
        
        # 新增：播放控制增强
        self.playback_speed = 1.0  # 播放速度
        self.volume = 1.0  # 音量
        self.is_muted = False  # 是否静音
        self.loop_playback = False  # 是否循环播放
        self.fullscreen_mode = False  # 是否全屏模式
        
        # 性能优化
        self.target_display_size = (640, 360)
        self.last_frame_processing_time = 0.0
        
        # 外部音轨与导出控制
        self.external_audio_path = None
        self.preview_external_audio_var = tk.BooleanVar(value=False)
        self.remove_original_audio_var = tk.BooleanVar(value=False)
        
        # 浮动遥测面板（速度/海拔/坡度）
        self.telemetry_rect_rel = [0.72, 0.72, 0.25, 0.22]  # x_frac, y_frac, w_frac, h_frac
        self.telemetry_dragging = False
        self.telemetry_resizing = False
        self.telemetry_drag_start = None
        self.telemetry_resize_margin = 16
        self.display_frame_rect = None  # (x0, y0, w, h) in canvas px
        
        # 创建GUI
        self.create_menu()
        self.create_toolbar()
        self.create_main_panel()
        self.create_timeline()
        self.create_status_bar()
        
        # 设置样式
        self.setup_styles()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 绑定GPX偏移调整快捷键
        self.root.bind('[', self.decrease_offset)
        self.root.bind(']', self.increase_offset)
        self.root.bind('{', self.decrease_offset_fine) # Shift+[
        self.root.bind('}', self.increase_offset_fine) # Shift+]
    
    def _get_ffprobe_cmd(self):
        """获取ffprobe命令路径"""
        # 1. 检查系统PATH
        if shutil.which('ffprobe'):
            return ['ffprobe']
        env_ffprobe = os.environ.get('FFPROBE')
        if env_ffprobe and os.path.exists(env_ffprobe):
            return [env_ffprobe]
            
        # 2. 检查当前目录
        if os.path.exists('ffprobe.exe'):
            return [os.path.abspath('ffprobe.exe')]
            
        if os.path.exists('ffprobe'):
            return [os.path.abspath('ffprobe')]
            
        # 3. 检查常见子目录
        common_paths = [
            os.path.join('ffmpeg', 'bin', 'ffprobe.exe'),
            os.path.join('bin', 'ffprobe.exe'),
            os.path.join('tools', 'ffprobe.exe'),
            os.path.join('ffmpeg', 'bin', 'ffprobe'),
            os.path.join('bin', 'ffprobe'),
            os.path.join('tools', 'ffprobe'),
            '/usr/local/bin/ffprobe',
            '/opt/homebrew/bin/ffprobe',
            '/usr/bin/ffprobe',
            '/opt/local/bin/ffprobe',
        ]
        
        for p in common_paths:
            if os.path.exists(p):
                return [os.path.abspath(p)]
                
        return None

    def setup_styles(self):
        """设置界面样式"""
        style = ttk.Style()
        style.theme_use('clam')
    
    def create_menu(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="打开视频...", command=self.open_video, accelerator="Ctrl+O")
        file_menu.add_command(label="导入视频...", command=self.import_video)
        file_menu.add_command(label="导入GPX...", command=self.import_gpx)
        file_menu.add_separator()
        file_menu.add_command(label="保存项目...", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="打开项目...", command=self.open_project, accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        file_menu.add_command(label="导出视频...", command=self.export_video, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit, accelerator="Ctrl+Q")
        
        # 编辑菜单
        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="编辑", menu=edit_menu)
        edit_menu.add_command(label="撤销", command=self.undo, accelerator="Ctrl+Z", state="disabled")
        edit_menu.add_command(label="重做", command=self.redo, accelerator="Ctrl+Y", state="disabled")
        edit_menu.add_separator()
        edit_menu.add_command(label="剪切", command=self.cut_clip, accelerator="Ctrl+X")
        edit_menu.add_command(label="复制", command=self.copy_clip, accelerator="Ctrl+C")
        edit_menu.add_command(label="粘贴", command=self.paste_clip, accelerator="Ctrl+V")
        edit_menu.add_separator()
        edit_menu.add_command(label="删除", command=self.delete_clip, accelerator="Del")
        
        # 剪辑菜单
        clip_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="剪辑", menu=clip_menu)
        clip_menu.add_command(label="分割", command=self.split_clip, accelerator="S")
        clip_menu.add_command(label="合并", command=self.merge_clips, accelerator="M")
        clip_menu.add_separator()
        clip_menu.add_command(label="设置入点", command=self.set_in_point, accelerator="I")
        clip_menu.add_command(label="设置出点", command=self.set_out_point, accelerator="O")
        clip_menu.add_separator()
        clip_menu.add_command(label="添加转场效果...", command=self.add_transition, state="disabled")
        clip_menu.add_command(label="添加滤镜...", command=self.add_filter, state="disabled")
        
        # 播放菜单
        play_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="播放", menu=play_menu)
        play_menu.add_command(label="播放/暂停", command=self.toggle_play, accelerator="Space")
        play_menu.add_command(label="停止", command=self.stop_play, accelerator="K")
        play_menu.add_separator()
        play_menu.add_command(label="上一帧", command=self.prev_frame, accelerator="←")
        play_menu.add_command(label="下一帧", command=self.next_frame, accelerator="→")
        play_menu.add_separator()
        play_menu.add_command(label="跳转到开始", command=self.jump_to_start, accelerator="Home")
        play_menu.add_command(label="跳转到结束", command=self.jump_to_end, accelerator="End")
        play_menu.add_separator()
        play_menu.add_checkbutton(label="循环播放", command=self.toggle_loop, 
                                 variable=tk.BooleanVar(value=self.loop_playback))

        # 工具菜单
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="工具", menu=tools_menu)
        tools_menu.add_command(label="手动设置GPX偏移", command=self.set_manual_offset)
        
        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="使用说明", command=self.show_help)
        help_menu.add_command(label="关于", command=self.show_about)
        
        # 绑定快捷键
        self.root.bind('<Control-o>', lambda e: self.open_video())
        self.root.bind('<Control-s>', lambda e: self.save_project())
        self.root.bind('<Control-e>', lambda e: self.export_video())
        self.root.bind('<space>', lambda e: self.toggle_play())
        self.root.bind('<k>', lambda e: self.stop_play())
        
        # 新增快捷键
        self.root.bind('<Left>', lambda e: self.prev_frame())
        self.root.bind('<Right>', lambda e: self.next_frame())
        self.root.bind('<Shift-Left>', lambda e: self.rewind_5s())
        self.root.bind('<Shift-Right>', lambda e: self.forward_5s())
        self.root.bind('<Home>', lambda e: self.jump_to_start())
        self.root.bind('<End>', lambda e: self.jump_to_end())
        self.root.bind('<Delete>', lambda e: self.delete_clip())
        self.root.bind('<s>', lambda e: self.split_clip())
        self.root.bind('<m>', lambda e: self.merge_clips())
        self.root.bind('<i>', lambda e: self.set_in_point())
        self.root.bind('<o>', lambda e: self.set_out_point())
        self.root.bind('<m>', lambda e: self.toggle_mute())
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = ttk.Frame(self.root, relief=tk.RAISED, borderwidth=1)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=2, pady=2)
        
        # 文件操作按钮
        ttk.Button(toolbar, text="打开视频", command=self.open_video, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="导入视频", command=self.import_video, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="导入GPX", command=self.import_gpx, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="导出视频", command=self.export_video, width=12).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # 播放控制按钮
        self.play_btn = ttk.Button(toolbar, text="▶ 播放", command=self.toggle_play, width=10)
        self.play_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="⏹ 停止", command=self.stop_play, width=10).pack(side=tk.LEFT, padx=2)
        
        # 新增：快速跳转按钮
        ttk.Button(toolbar, text="⏮", command=self.jump_to_start, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="⏪", command=self.rewind_5s, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="⏩", command=self.forward_5s, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar, text="⏭", command=self.jump_to_end, width=3).pack(side=tk.LEFT, padx=1)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # 剪辑操作按钮
        ttk.Button(toolbar, text="分割", command=self.split_clip, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="删除", command=self.delete_clip, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="合并", command=self.merge_clips, width=8).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # 缩放控制
        ttk.Label(toolbar, text="缩放:").pack(side=tk.LEFT, padx=2)
        self.zoom_var = tk.StringVar(value="100%")
        zoom_combo = ttk.Combobox(toolbar, textvariable=self.zoom_var, width=8, 
                                  values=["25%", "50%", "75%", "100%", "125%", "150%", "200%"],
                                  state="readonly")
        zoom_combo.pack(side=tk.LEFT, padx=2)
        zoom_combo.bind('<<ComboboxSelected>>', self.on_zoom_change)
    
    def on_canvas_resize(self, event):
        """画布大小改变"""
        if event.width > 1 and event.height > 1:
            self.target_display_size = (event.width, event.height)

    def create_main_panel(self):
        """创建主面板（预览窗口和控制面板）"""
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        left_container = ttk.Frame(main_container)
        main_container.add(left_container, weight=2)
        self.preview_notebook = ttk.Notebook(left_container)
        self.preview_notebook.pack(fill=tk.BOTH, expand=True)
        video_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(video_tab, text="视频")
        # self.align_tab = ttk.Frame(self.preview_notebook)
        # self.preview_notebook.add(self.align_tab, text="轨迹对齐")
        self.video_canvas = tk.Canvas(video_tab, bg="#000000", width=640, height=360, highlightthickness=0, bd=0)
        self.video_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # 绑定画布大小改变事件
        self.video_canvas.bind('<Configure>', self.on_canvas_resize)
        # 绑定浮动面板拖放
        self.video_canvas.bind('<ButtonPress-1>', self.on_video_panel_press)
        self.video_canvas.bind('<B1-Motion>', self.on_video_panel_drag)
        self.video_canvas.bind('<ButtonRelease-1>', self.on_video_panel_release)
        
        self.preview_label = ttk.Label(video_tab, text="📹 未加载视频\n\n点击 文件 -> 打开视频 来加载视频文件", font=default_font, foreground="gray", justify=tk.CENTER)
        self.preview_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        control_frame = ttk.Frame(video_tab)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        self.progress_var = tk.DoubleVar()
        self.progress_scale = ttk.Scale(control_frame, from_=0, to=100, variable=self.progress_var, orient=tk.HORIZONTAL, command=self.on_progress_change)
        self.progress_scale.pack(fill=tk.X, padx=5, pady=2)
        self.progress_scale.bind("<ButtonPress-1>", self.on_progress_press)
        self.progress_scale.bind("<ButtonRelease-1>", self.on_progress_release)
        time_frame = ttk.Frame(control_frame)
        time_frame.pack(fill=tk.X, padx=5)
        self.time_label = ttk.Label(time_frame, text="00:00:00 / 00:00:00", font=default_font)
        self.time_label.pack(side=tk.LEFT)
        control_buttons_frame = ttk.Frame(time_frame)
        control_buttons_frame.pack(side=tk.LEFT, padx=20)
        ttk.Button(control_buttons_frame, text="⏮", command=self.jump_to_start, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(control_buttons_frame, text="⏪", command=self.rewind_5s, width=3).pack(side=tk.LEFT, padx=1)
        self.play_btn = ttk.Button(control_buttons_frame, text="▶", command=self.toggle_play, width=3)
        self.play_btn.pack(side=tk.LEFT, padx=1)
        ttk.Button(control_buttons_frame, text="⏩", command=self.forward_5s, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(control_buttons_frame, text="⏭", command=self.jump_to_end, width=3).pack(side=tk.LEFT, padx=1)
        volume_frame = ttk.Frame(time_frame)
        volume_frame.pack(side=tk.RIGHT, padx=5)
        self.mute_btn = ttk.Button(volume_frame, text="🔊", command=self.toggle_mute, width=3)
        self.mute_btn.pack(side=tk.LEFT, padx=1)
        self.volume_scale = ttk.Scale(volume_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.on_volume_change, length=80)
        self.volume_scale.set(100)
        self.volume_scale.pack(side=tk.LEFT, padx=2)
        speed_frame = ttk.Frame(time_frame)
        speed_frame.pack(side=tk.RIGHT, padx=10)
        ttk.Label(speed_frame, text="速度:", font=default_font).pack(side=tk.LEFT, padx=2)
        self.speed_var = tk.StringVar(value="1.0x")
        speed_combo = ttk.Combobox(speed_frame, textvariable=self.speed_var, width=6, values=["0.25x", "0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"], state="readonly")
        speed_combo.pack(side=tk.LEFT, padx=2)
        speed_combo.bind('<<ComboboxSelected>>', self.on_speed_change)
        # self.init_align_tab(self.align_tab)
        property_frame = ttk.LabelFrame(main_container, text="属性", padding=10, width=250)
        main_container.add(property_frame, weight=1)
        self.create_property_panel(property_frame)
    
    def create_property_panel(self, parent):
        """创建属性面板"""
        # 轨迹预览 (原视频缩略图位置)
        self.align_frame = ttk.LabelFrame(parent, text="轨迹预览", padding=5)
        self.align_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.align_canvas = tk.Canvas(self.align_frame, bg="#1E1E1E", height=200, width=160,
                                          highlightthickness=0, bd=0)
        self.align_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.align_canvas.bind("<Configure>", lambda e: self.update_align_canvas())
        self.align_canvas.bind("<MouseWheel>", self.on_align_zoom) # Windows/MacOS
        self.align_canvas.bind("<Button-4>", self.on_align_zoom)   # Linux Scroll Up
        self.align_canvas.bind("<Button-5>", self.on_align_zoom)   # Linux Scroll Down
        self.align_canvas.bind("<ButtonPress-1>", self.on_align_drag_start)
        self.align_canvas.bind("<B1-Motion>", self.on_align_drag_move)
        self.align_canvas.bind("<ButtonPress-3>", self.on_align_right_click)  # 右键点击定位

        
        # 轨迹对齐控制 (原视频信息位置)
        control_frame = ttk.LabelFrame(parent, text="对齐控制", padding=5)
        control_frame.pack(fill=tk.X, pady=5)
        
        # 控件
        self.align_reverse_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(control_frame, text="反向", variable=self.align_reverse_var, command=self.update_align_canvas).pack(side=tk.TOP, anchor=tk.E, padx=5)
        
        self.align_progress_var = tk.DoubleVar(value=0.0)
        self.align_scale = ttk.Scale(control_frame, from_=0.0, to=0.0, orient=tk.HORIZONTAL, variable=self.align_progress_var, command=self.on_align_progress_change)
        self.align_scale.pack(fill=tk.X, padx=5, pady=5)
        
        # 底部控制栏
        bottom_ctrl_frame = ttk.Frame(control_frame)
        bottom_ctrl_frame.pack(fill=tk.X, padx=5, pady=2)
        
        self.align_time_label = ttk.Label(bottom_ctrl_frame, text="GPX时间:")
        self.align_time_label.pack(side=tk.LEFT, padx=2)
        
        # 微调 Spinbox
        self.align_spinbox = ttk.Spinbox(bottom_ctrl_frame, from_=0.0, to=0.0, increment=0.1, 
                                         textvariable=self.align_progress_var, width=10,
                                         format="%.2f",
                                         command=self.on_align_spinbox_change)
        self.align_spinbox.pack(side=tk.LEFT, padx=2)
        self.align_spinbox.bind('<Return>', self.on_align_spinbox_change)
        self.align_spinbox.bind('<FocusOut>', self.on_align_spinbox_change)
        
        self.align_confirm_btn = ttk.Button(bottom_ctrl_frame, text="确认对齐", command=self.align_confirm)
        self.align_confirm_btn.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(bottom_ctrl_frame, text="重置视图", command=self.reset_align_view, width=8).pack(side=tk.RIGHT, padx=2)
        
        # 提示标签
        tip_label = ttk.Label(control_frame, text="提示: 右键点击地图轨迹可定位到对应时间点", foreground="gray", font=("Arial", 8))
        tip_label.pack(fill=tk.X, padx=5, pady=0)
        
        # 音频控制
        audio_frame = ttk.LabelFrame(parent, text="音频", padding=5)
        audio_frame.pack(fill=tk.X, pady=5)
        ttk.Button(audio_frame, text="导入音轨", command=self.import_audio_track, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(audio_frame, text="预览外部音轨", variable=self.preview_external_audio_var, command=self.on_preview_audio_toggle).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(audio_frame, text="移除原声(导出)", variable=self.remove_original_audio_var).pack(side=tk.LEFT, padx=8)
        self.audio_file_label = ttk.Label(audio_frame, text="未选择音轨")
        self.audio_file_label.pack(side=tk.LEFT, padx=8)
        
        # Init variables
        self.align_track_points = None
        self.align_transform = None
        self.thumbnail_canvas = None # Disable video thumbnail canvas

        # 数据图表 (速度/海拔)
        self.create_data_charts(parent)

        # 剪辑片段列表
        clip_frame = ttk.LabelFrame(parent, text="剪辑片段", padding=5)
        clip_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 片段列表树形视图
        columns = ('名称', '开始时间', '结束时间', '时长')
        self.clip_tree = ttk.Treeview(clip_frame, columns=columns, show='tree headings', height=10)
        
        self.clip_tree.heading('#0', text='#')
        self.clip_tree.heading('名称', text='名称')
        self.clip_tree.heading('开始时间', text='开始时间')
        self.clip_tree.heading('结束时间', text='结束时间')
        self.clip_tree.heading('时长', text='时长')
        
        self.clip_tree.column('#0', width=40)
        self.clip_tree.column('名称', width=100)
        self.clip_tree.column('开始时间', width=80)
        self.clip_tree.column('结束时间', width=80)
        self.clip_tree.column('时长', width=80)
        
        scrollbar = ttk.Scrollbar(clip_frame, orient=tk.VERTICAL, command=self.clip_tree.yview)
        self.clip_tree.configure(yscrollcommand=scrollbar.set)
        
        self.clip_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.clip_tree.bind('<Double-1>', self.on_clip_select)

    def create_data_charts(self, parent):
        """创建数据图表 (速度/海拔)"""
        if not HAS_MATPLOTLIB:
            return
            
        chart_frame = ttk.LabelFrame(parent, text="数据分析 (GPX)", padding=5)
        chart_frame.pack(fill=tk.BOTH, expand=False, pady=5)
        
        # Matplotlib Figure (Two subplots)
        self.chart_fig = Figure(figsize=(3, 3), dpi=100, facecolor='#f0f0f0')
        
        # Speed subplot (top)
        self.speed_ax = self.chart_fig.add_subplot(211)
        self.speed_ax.set_facecolor('#ffffff')
        self.speed_line, = self.speed_ax.plot([], [], color='#1f77b4', linewidth=1)
        self.speed_cursor = self.speed_ax.axvline(x=0, color='red', linestyle='--', linewidth=1)
        self.speed_ax.set_ylabel('Speed (km/h)', fontsize=6)
        self.speed_ax.tick_params(axis='both', which='major', labelsize=6)
        self.speed_ax.grid(True, linestyle=':', alpha=0.5)
        
        # Elevation subplot (bottom, share x)
        self.ele_ax = self.chart_fig.add_subplot(212, sharex=self.speed_ax)
        self.ele_ax.set_facecolor('#ffffff')
        self.ele_line, = self.ele_ax.plot([], [], color='#2ca02c', linewidth=1)
        self.ele_cursor = self.ele_ax.axvline(x=0, color='red', linestyle='--', linewidth=1)
        self.ele_ax.set_xlabel('Time (s)', fontsize=7)
        self.ele_ax.set_ylabel('Ele (m)', fontsize=6)
        self.ele_ax.tick_params(axis='both', which='major', labelsize=6)
        self.ele_ax.grid(True, linestyle=':', alpha=0.5)
        
        self.chart_fig.subplots_adjust(left=0.15, right=0.95, top=0.95, bottom=0.15, hspace=0.3)
        
        self.chart_canvas = FigureCanvasTkAgg(self.chart_fig, master=chart_frame)
        self.chart_canvas.draw()
        self.chart_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def update_data_charts(self):
        """更新图表数据"""
        if not HAS_MATPLOTLIB or not hasattr(self, 'speed_ax'):
            return
            
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data and self.gpx_data['segments']):
            self.speed_line.set_data([], [])
            self.ele_line.set_data([], [])
            self.chart_canvas.draw()
            return
            
        # Extract data
        times = []
        speeds = []
        eles = []
        
        for seg in self.gpx_data['segments']:
            times.append(seg['start'])
            speeds.append(seg['speed'])
            eles.append(seg.get('ele_start', 0))
        
        if self.gpx_data['segments']:
            last = self.gpx_data['segments'][-1]
            times.append(last['end'])
            speeds.append(last['speed'])
            eles.append(last.get('ele_end', 0))

        if times:
            self.speed_line.set_data(times, speeds)
            self.ele_line.set_data(times, eles)
            
            self.speed_ax.relim()
            self.speed_ax.autoscale_view()
            self.ele_ax.relim()
            self.ele_ax.autoscale_view()
            
            self.chart_canvas.draw()
            
    def update_chart_cursors(self, current_gpx_time):
        """更新图表游标位置"""
        if not HAS_MATPLOTLIB or not hasattr(self, 'speed_cursor'):
            return
            
        try:
            self.speed_cursor.set_xdata([current_gpx_time, current_gpx_time])
            self.ele_cursor.set_xdata([current_gpx_time, current_gpx_time])
            self.chart_canvas.draw_idle()
        except Exception:
            pass
    
    # def init_align_tab(self, parent):
    #     self.align_canvas = tk.Canvas(parent, bg="#1E1E1E", height=420, highlightthickness=0, bd=0)
    #     self.align_canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
    #     bottom = ttk.Frame(parent)
    #     bottom.pack(fill=tk.X, padx=6, pady=6)
    #     self.align_reverse_var = tk.BooleanVar(value=False)
    #     ttk.Checkbutton(bottom, text="反向", variable=self.align_reverse_var, command=self.update_align_canvas).pack(side=tk.RIGHT, padx=6)
    #     self.align_progress_var = tk.DoubleVar(value=0.0)
    #     self.align_scale = ttk.Scale(bottom, from_=0.0, to=0.0, orient=tk.HORIZONTAL, variable=self.align_progress_var, command=self.on_align_progress_change)
    #     self.align_scale.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=6)
    #     self.align_time_label = ttk.Label(bottom, text="GPX时间: 0.0s")
    #     self.align_time_label.pack(side=tk.LEFT, padx=8)
    #     self.align_confirm_btn = ttk.Button(bottom, text="确认对齐", command=self.align_confirm)
    #     self.align_confirm_btn.pack(side=tk.RIGHT, padx=6)
    #     self.align_canvas.bind("<Configure>", lambda e: self.update_align_canvas())
    #     self.align_track_points = None
    #     self.align_transform = None
    
    def get_gpx_duration(self):
        if isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data and self.gpx_data['segments']:
            return float(self.gpx_data['segments'][-1]['end'])
        return 0.0
    
    def _get_latlon_at_gpx_time(self, t):
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data):
            return None, None
        segs = self.gpx_data['segments']
        if not segs:
            return None, None
        if t <= segs[0]['start']:
            return segs[0]['lat_start'], segs[0]['lon_start']
        if t >= segs[-1]['end']:
            return segs[-1]['lat_end'], segs[-1]['lon_end']
        low, high = 0, len(segs) - 1
        while low <= high:
            mid = (low + high) // 2
            s = segs[mid]
            if s['start'] <= t <= s['end']:
                ratio = 0.0
                span = s['end'] - s['start']
                if span > 0:
                    ratio = (t - s['start']) / span
                lat = s['lat_start'] + (s['lat_end'] - s['lat_start']) * ratio
                lon = s['lon_start'] + (s['lon_end'] - s['lon_start']) * ratio
                return lat, lon
            if t > s['end']:
                low = mid + 1
            else:
                high = mid - 1
        return None, None
    
    def update_align_controls(self):
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data and self.gpx_data['segments']):
            self.align_scale.config(from_=0.0, to=0.0)
            self.align_progress_var.set(0.0)
            self.align_time_label.config(text="GPX时间: 0.0s")
            self.update_align_canvas()
            return
        duration = max(0.0, self.get_gpx_duration())
        self.align_scale.config(from_=0.0, to=duration)
        if hasattr(self, 'align_spinbox'):
            self.align_spinbox.config(from_=0.0, to=duration)
        
        # 使用当前视频时间对应的GPX时间来初始化控件
        current_video_time = self._current_time()
        gpx_offset = getattr(self, 'gpx_offset', 0.0)
        
        # 计算当前视频时刻应该对应的GPX时刻
        estimated_gpx_time = current_video_time + gpx_offset
        
        # 考虑倒放选项（虽然加载时通常未勾选，但为了严谨）
        if getattr(self, 'align_reverse_var', None) and self.align_reverse_var.get():
             estimated_gpx_time = duration - estimated_gpx_time
             
        # 限制在范围内
        estimated_gpx_time = max(0.0, min(duration, estimated_gpx_time))
        
        self.align_progress_var.set(estimated_gpx_time)
        # self.align_time_label.config(text=f"GPX时间: {estimated_gpx_time:.1f}s")
        self.update_align_canvas()
        
        # 更新速度曲线光标
        if hasattr(self, 'update_chart_cursors'):
            self.update_chart_cursors(estimated_gpx_time)
    
    def reset_align_view(self):
        """重置轨迹预览视图"""
        self.align_zoom_scale = 1.0
        self.align_offset_x = 0.0
        self.align_offset_y = 0.0
        self.update_align_canvas()
        
    def on_align_zoom(self, event):
        """处理轨迹预览缩放"""
        if not self.gpx_data:
            return
            
        # Determine scroll direction
        if event.num == 5 or event.delta < 0:
            scale_factor = 0.9
        else:
            scale_factor = 1.1
            
        # Update zoom scale
        new_zoom = self.align_zoom_scale * scale_factor
        if 0.1 <= new_zoom <= 50.0:
            # Zoom around mouse position
            w = self.align_canvas.winfo_width()
            h = self.align_canvas.winfo_height()
            mx = event.x - w / 2
            my = event.y - h / 2
            
            self.align_offset_x = mx - (mx - self.align_offset_x) * scale_factor
            self.align_offset_y = my - (my - self.align_offset_y) * scale_factor
            
            self.align_zoom_scale = new_zoom
            self.update_align_canvas()
            
    def on_align_spinbox_change(self, event=None):
        """处理 Spinbox 变化"""
        try:
            val = self.align_progress_var.get()
            self.on_align_progress_change(val)
        except Exception:
            pass

    def on_align_drag_start(self, event):
        """开始拖拽轨迹预览"""
        self.align_drag_start = (event.x, event.y)
        
    def on_align_drag_move(self, event):
        """拖拽轨迹预览"""
        if not self.align_drag_start:
            return
            
        dx = event.x - self.align_drag_start[0]
        dy = event.y - self.align_drag_start[1]
        
        self.align_offset_x += dx
        self.align_offset_y += dy
        
        self.align_drag_start = (event.x, event.y)
        self.update_align_canvas()

    def on_align_right_click(self, event):
        """右键点击地图定位时间"""
        if not hasattr(self, 'align_transform_params') or not self.align_transform_params:
            return
            
        # 1. 获取点击坐标并反变换为经纬度
        x, y = event.x, event.y
        params = self.align_transform_params
        
        zoom = params['zoom']
        off_x, off_y = params['off_x'], params['off_y']
        cx, cy = params['cx'], params['cy']
        bb_w, bb_h = params['bb_w'], params['bb_h']
        min_lat, min_lon = params['min_lat'], params['min_lon']
        lon_corr = params['lon_corr']
        lon_range, lat_range = params['lon_range'], params['lat_range']
        
        if zoom == 0 or bb_w == 0 or bb_h == 0 or lon_corr == 0:
            return

        # 反解坐标变换
        # x = cx + x_zoomed + off_x
        x_zoomed = x - cx - off_x
        y_zoomed = y - cy - off_y
        
        # x_zoomed = x_base * zoom
        x_base = x_zoomed / zoom
        y_base = y_zoomed / zoom
        
        # x_base = norm_x * bb_w
        norm_x = x_base / bb_w
        # y_base = -norm_y * bb_h
        norm_y = -y_base / bb_h
        
        # norm_x = ((lon - min_lon) * lon_corr / lon_range) - 0.5
        click_lon = ((norm_x + 0.5) * lon_range / lon_corr) + min_lon
        # norm_y = ((lat - min_lat) / lat_range) - 0.5
        click_lat = ((norm_y + 0.5) * lat_range) + min_lat
        
        # 2. 查找最近的 GPX 点
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data and self.gpx_data['segments']):
            return
            
        segments = self.gpx_data['segments']
        
        min_dist_sq = float('inf')
        best_time = 0.0
        
        # 采样查找
        step = 1
        if len(segments) > 10000:
            step = 5
            
        for i in range(0, len(segments), step):
            s = segments[i]
            d_sq = (s['lat_start'] - click_lat)**2 + (s['lon_start'] - click_lon)**2
            if d_sq < min_dist_sq:
                min_dist_sq = d_sq
                best_time = s['start']
                
        # 3. 更新 UI
        self.align_progress_var.set(best_time)
        self.on_align_progress_change(best_time)
        
        self.update_status(f"定位到 GPX 时间: {best_time:.1f}s")

    def update_align_canvas(self):
        if not hasattr(self, 'align_canvas'):
            return
        self.align_canvas.delete("all")
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data and self.gpx_data['segments']):
            w = self.align_canvas.winfo_width()
            h = self.align_canvas.winfo_height()
            if w > 0 and h > 0:
                self.align_canvas.create_text(w//2, h//2, text="未加载GPX", fill="#999999")
            return
        pts = []
        for s in self.gpx_data['segments']:
            pts.append((s['lat_start'], s['lon_start']))
        if self.gpx_data['segments']:
            last = self.gpx_data['segments'][-1]
            pts.append((last['lat_end'], last['lon_end']))
            
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        if not lats:
            return
            
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        
        w = max(1, self.align_canvas.winfo_width())
        h = max(1, self.align_canvas.winfo_height())
        padding = 20
        
        mid_lat = math.radians((min_lat + max_lat) / 2) if max_lat != min_lat else 0.0
        lon_corr = math.cos(mid_lat) if max_lat != min_lat else 1.0
        
        lat_range = max(1e-9, max_lat - min_lat)
        lon_range = max(1e-9, (max_lon - min_lon) * lon_corr)
        
        # Base scale to fit screen
        scale_x = (w - 2 * padding) / lon_range
        scale_y = (h - 2 * padding) / lat_range
        base_scale = min(scale_x, scale_y)
        
        bb_w = lon_range * base_scale
        bb_h = lat_range * base_scale
        
        cx = w / 2
        cy = h / 2
        
        zoom = getattr(self, 'align_zoom_scale', 1.0)
        off_x = getattr(self, 'align_offset_x', 0.0)
        off_y = getattr(self, 'align_offset_y', 0.0)
        
        def tf(lat, lon):
            norm_x = ((lon - min_lon) * lon_corr / lon_range) - 0.5
            norm_y = ((lat - min_lat) / lat_range) - 0.5
            
            x_base = norm_x * bb_w
            y_base = -norm_y * bb_h
            
            x_zoomed = x_base * zoom
            y_zoomed = y_base * zoom
            
            x = cx + x_zoomed + off_x
            y = cy + y_zoomed + off_y
            return x, y
            
        # 保存变换参数供点击定位使用
        self.align_transform_params = {
            'min_lat': min_lat, 'min_lon': min_lon,
            'lon_corr': lon_corr, 'lon_range': lon_range, 'lat_range': lat_range,
            'bb_w': bb_w, 'bb_h': bb_h, 'cx': cx, 'cy': cy,
            'zoom': zoom, 'off_x': off_x, 'off_y': off_y
        }
            
        screen = [tf(lat, lon) for lat, lon in pts]
        
        # Draw all lines at once
        flat_pts = [coord for pt in screen for coord in pt]
        if len(flat_pts) >= 4:
            self.align_canvas.create_line(flat_pts, fill="#00FF00", width=2, tags="track")
            
        t = self.align_progress_var.get()
        duration = self.get_gpx_duration()
        eff_t = duration - t if self.align_reverse_var.get() else t
        lat, lon = self._get_latlon_at_gpx_time(eff_t)
        
        if lat is not None and lon is not None:
            x, y = tf(lat, lon)
            r = 5
            self.align_canvas.create_oval(x-r, y-r, x+r, y+r, fill="#00BFFF", outline="", tags="cursor")
            # Crosshair
            self.align_canvas.create_line(x-10, y, x+10, y, fill="white", width=1, tags="cursor")
            self.align_canvas.create_line(x, y-10, x, y+10, fill="white", width=1, tags="cursor")
            
        self.align_transform_params = {
            'min_lat': min_lat, 'min_lon': min_lon,
            'lon_corr': lon_corr, 'lon_range': lon_range, 'lat_range': lat_range,
            'bb_w': bb_w, 'bb_h': bb_h, 'cx': cx, 'cy': cy
        }
        self.align_transform = (min_lat, min_lon, base_scale, h, padding, lon_corr)
        self.align_track_points = pts
    
    def update_align_cursor(self, gpx_time):
        """更新对齐视图中的光标位置（优化版，不重绘整个轨迹）"""
        if not hasattr(self, 'align_canvas'):
            return
            
        # 1. 更新滑块和时间标签
        # 注意：align_progress_var 在反向模式下需要反转逻辑
        duration = self.get_gpx_duration()
        slider_val = gpx_time
        
        # 如果当前是反向模式，align_progress_var 应该显示 "倒数" 的时间还是正向时间？
        # 参考 update_align_controls: 
        # if reverse: estimated_gpx_time = duration - estimated_gpx_time
        # self.align_progress_var.set(estimated_gpx_time)
        # 所以 align_progress_var 存储的是 "显示值"
        
        if getattr(self, 'align_reverse_var', None) and self.align_reverse_var.get():
            slider_val = duration - gpx_time
            
        # 更新变量（避免触发 on_align_progress_change 回调导致循环调用，或者接受它）
        # on_align_progress_change 会调用 update_align_canvas 和 update_chart_cursors
        # 我们只想更新 UI 显示，不希望触发重绘
        # 但 Tkinter 的 set() 会触发 trace，这里使用的是 command 回调
        # Scale 的 command 回调只在用户交互时触发吗？通常是的，但在 set() 时不会触发 command
        # 除非绑定了 variable 的 trace。这里使用的是 command=self.on_align_progress_change
        self._is_updating_ui = True
        try:
            self.align_progress_var.set(slider_val)
        finally:
            self._is_updating_ui = False
            
        # self.align_time_label.config(text=f"GPX时间: {gpx_time:.1f}s")
        
        # 2. 更新地图光标
        # 需要变换参数
        if not hasattr(self, 'align_transform_params'):
            return
            
        params = self.align_transform_params
        lat, lon = self._get_latlon_at_gpx_time(gpx_time)
        
        if lat is None or lon is None:
            return
            
        # 计算屏幕坐标
        zoom = getattr(self, 'align_zoom_scale', 1.0)
        off_x = getattr(self, 'align_offset_x', 0.0)
        off_y = getattr(self, 'align_offset_y', 0.0)
        
        min_lon = params['min_lon']
        min_lat = params['min_lat']
        lon_corr = params['lon_corr']
        lon_range = params['lon_range']
        lat_range = params['lat_range']
        bb_w = params['bb_w']
        bb_h = params['bb_h']
        cx = params['cx']
        cy = params['cy']
        
        norm_x = ((lon - min_lon) * lon_corr / lon_range) - 0.5
        norm_y = ((lat - min_lat) / lat_range) - 0.5
        
        x_base = norm_x * bb_w
        y_base = -norm_y * bb_h
        
        x_zoomed = x_base * zoom
        y_zoomed = y_base * zoom
        
        x = cx + x_zoomed + off_x
        y = cy + y_zoomed + off_y
        
        # 移动或创建光标
        self.align_canvas.delete("cursor")
        r = 5
        self.align_canvas.create_oval(x-r, y-r, x+r, y+r, fill="#00BFFF", outline="", tags="cursor")
        # Crosshair
        self.align_canvas.create_line(x-10, y, x+10, y, fill="white", width=1, tags="cursor")
        self.align_canvas.create_line(x, y-10, x, y+10, fill="white", width=1, tags="cursor")

    def on_align_progress_change(self, value):
        if getattr(self, '_is_updating_ui', False):
            return
            
        try:
            v = float(value)
        except:
            v = 0.0
        duration = self.get_gpx_duration()
        eff_v = duration - v if getattr(self, 'align_reverse_var', None) and self.align_reverse_var.get() else v
        # self.align_time_label.config(text=f"GPX时间: {eff_v:.1f}s")
        self.update_align_canvas()
        
        # 更新图表光标
        if hasattr(self, 'update_chart_cursors'):
            self.update_chart_cursors(eff_v)
    
    def align_confirm(self):
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data and self.gpx_data['segments']):
            messagebox.showwarning("提示", "未加载GPX数据")
            return
        current_video_time = self._current_time()
        raw_gpx_time = self.align_progress_var.get()
        duration = self.get_gpx_duration()
        selected_gpx_time = duration - raw_gpx_time if self.align_reverse_var.get() else raw_gpx_time
        self.gpx_offset = selected_gpx_time - current_video_time
        self.update_status(f"设置偏移: {self.gpx_offset:+.2f}s")
        if self.cap is not None:
            # 强制刷新当前帧叠加层（无论是否在播放）
            self.seek_to_frame(self.current_frame_pos)
    
    def create_timeline(self):
        """创建时间轴"""
        timeline_frame = ttk.LabelFrame(self.root, text="时间轴", padding=5)
        timeline_frame.pack(fill=tk.BOTH, expand=False, padx=5, pady=5, side=tk.BOTTOM)
        
        # 创建滚动条
        timeline_scroll = ttk.Scrollbar(timeline_frame, orient=tk.HORIZONTAL)
        timeline_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 定义同步滚动函数
        def sync_scroll(*args):
            self.ruler_canvas.xview(*args)
            self.timeline_canvas.xview(*args)
            
        timeline_scroll.config(command=sync_scroll)
        
        # 时间标尺
        ruler_frame = ttk.Frame(timeline_frame, height=30)
        ruler_frame.pack(fill=tk.X, pady=2)
        
        self.ruler_canvas = tk.Canvas(ruler_frame, height=25, bg="#F0F0F0",
                                      xscrollcommand=timeline_scroll.set)
        self.ruler_canvas.pack(fill=tk.BOTH, expand=True)
        
        # 时间轴轨道
        track_container = ttk.Frame(timeline_frame)
        track_container.pack(fill=tk.BOTH, expand=True)
        
        # 时间轴画布
        self.timeline_canvas = tk.Canvas(track_container, bg="#2B2B2B", height=150,
                                         xscrollcommand=timeline_scroll.set)
        self.timeline_canvas.pack(fill=tk.BOTH, expand=True)
        
        # 绑定事件
        self.timeline_canvas.bind("<Button-1>", self.on_timeline_click)
        self.timeline_canvas.bind("<B1-Motion>", self.on_timeline_click)
        self.ruler_canvas.bind("<Button-1>", self.on_timeline_click)
        self.ruler_canvas.bind("<B1-Motion>", self.on_timeline_click)
        
        # 时间轴控制
        timeline_control = ttk.Frame(timeline_frame)
        timeline_control.pack(fill=tk.X, pady=2)
        
        ttk.Button(timeline_control, text="放大", command=self.timeline_zoom_in, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(timeline_control, text="缩小", command=self.timeline_zoom_out, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(timeline_control, text="适应", command=self.timeline_fit, width=8).pack(side=tk.LEFT, padx=2)
        
        # 时间轴缩放变量
        self.timeline_scale = 1.0  # 像素/秒
    
    def create_status_bar(self):
        """创建状态栏"""
        self.status_bar = ttk.Frame(self.root, relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_label = ttk.Label(self.status_bar, text="就绪", font=default_font)
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        # 分辨率显示
        self.resolution_label = ttk.Label(self.status_bar, text="", font=default_font)
        self.resolution_label.pack(side=tk.RIGHT, padx=5)
        
        # 帧率显示
        self.fps_label = ttk.Label(self.status_bar, text="", font=default_font)
        self.fps_label.pack(side=tk.RIGHT, padx=5)
    
    # ============ 菜单功能实现 ============
    
    def open_video(self):
        """打开视频文件"""
        file_path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.m4v"),
                ("所有文件", "*.*")
            ]
        )
        
        if file_path:
            self.load_video(file_path)
    
    def _parse_to_utc_datetime(self, time_str):
        """解析时间字符串，统一返回带时区的 UTC datetime"""
        if not time_str:
            return None
            
        try:
            # 1. 处理 Z 后缀 (替换为 +00:00 以兼容 fromisoformat)
            if time_str.endswith('Z'):
                time_str = time_str[:-1] + '+00:00'
                
            # 2. 尝试使用 fromisoformat (支持 +HH:MM)
            try:
                dt = datetime.fromisoformat(time_str)
            except ValueError:
                # 尝试处理毫秒过长的情况 (Python只支持6位)
                if '.' in time_str:
                    main_part, rest = time_str.split('.', 1)
                    # 查找时区部分
                    tz_part = ''
                    if '+' in rest:
                        frac, tz_part = rest.split('+', 1)
                        tz_part = '+' + tz_part
                    elif '-' in rest:
                        frac, tz_part = rest.split('-', 1)
                        tz_part = '-' + tz_part
                    else:
                        frac = rest
                    
                    # 截断毫秒到6位
                    if len(frac) > 6:
                        frac = frac[:6]
                    
                    dt = datetime.fromisoformat(f"{main_part}.{frac}{tz_part}")
                else:
                    # 最后的尝试: 常见格式
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']:
                        try:
                            dt = datetime.strptime(time_str, fmt)
                            break
                        except ValueError:
                            continue
                    if 'dt' not in locals():
                        raise ValueError(f"Unknown format: {time_str}")

            # 3. 确保有时区信息 (如果没有，默认为 UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            # 4. 转换为 UTC
            return dt.astimezone(timezone.utc)
            
        except Exception as e:
            print(f"时间解析错误: {time_str}, {e}")
            return None

    def _parse_iso8601(self, time_str):
        """解析ISO8601时间字符串 (兼容旧接口，现代理到 _parse_to_utc_datetime)"""
        return self._parse_to_utc_datetime(time_str)

    def load_video(self, video_path):
        """加载视频"""
        if not HAS_CV2:
            messagebox.showerror("错误", "未安装 opencv-python！\n请运行: pip install opencv-python")
            return
        
        # 关闭之前打开的视频
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        
        self.video_path = video_path
        # 获取视频创建时间
        self.video_creation_time, _ = self._get_video_creation_time(video_path)
        self.update_status(f"正在加载视频: {os.path.basename(video_path)}...")
        
        try:
            # 使用 OpenCV 加载视频
            self.cap = cv2.VideoCapture(video_path)
            
            if not self.cap.isOpened():
                raise Exception("无法打开视频文件")
            
            # 获取视频信息
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            
            # 获取编解码器信息
            fourcc = int(self.cap.get(cv2.CAP_PROP_FOURCC))
            codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
            
            self.video_info = {
                'path': video_path,
                'name': os.path.basename(video_path),
                'duration': duration,
                'fps': fps,
                'width': width,
                'height': height,
                'codec': codec if codec.strip() else 'Unknown',
                'frame_count': frame_count
            }
            
            self.total_frames = frame_count
            self.current_frame_pos = 0
            
            # 更新界面
            self.update_video_info()
            self.update_preview_label("")
            
            # 显示第一帧
            self.seek_to_frame(0)
            
            self.update_status(f"视频加载成功: {self.video_info['name']} ({width}x{height}, {fps:.2f}fps)")
            
            # 初始化剪辑片段列表
            self.clips = [{
                'id': 'clip_0',
                'name': '初始片段',
                'start_frame': 0,
                'end_frame': self.total_frames,
                'source': self.video_path
            }]
            self.update_clip_list()
            
            # 初始化时间轴
            self.timeline_fit()
            # 启动缩略图生成
            self.start_timeline_thumbnail_generation()
            # 加载外部GPX文件（不再从视频中提取GPMD）
            self.load_gpx_data(video_path)
            
        except Exception as e:
            messagebox.showerror("错误", f"加载视频失败:\n{str(e)}")
            self.update_status(f"加载失败: {str(e)}")
            if self.cap is not None:
                self.cap.release()
                self.cap = None
    
    def set_manual_offset(self):
        """手动设置时间偏移"""
        # 创建一个简单的对话框
        offset_str = simpledialog.askstring("手动同步", f"当前偏移: {self.gpx_offset:.2f}秒\n请输入新的偏移量 (秒):", initialvalue=str(self.gpx_offset))
        if offset_str:
            try:
                self.gpx_offset = float(offset_str)
                self.update_status(f"手动设置偏移: {self.gpx_offset:.2f}秒")
                if not self.playing:
                    self.seek_to_frame(self.current_frame_pos)
            except ValueError:
                messagebox.showerror("错误", "无效的数字格式")

    # 已移除：从视频中提取GPMD的逻辑

    # 已移除：_calculate_speeds_from_points（仅用于 GPMD 列表数据）

    def draw_track_thumbnail(self):
        """Draw track thumbnail for internal points"""
        if not hasattr(self, 'gpx_data') or not self.gpx_data:
            return
            
        # Extract lat/lon list from segments
        points = []
        if isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data:
            for s in self.gpx_data['segments']:
                points.append((s['lat_start'], s['lon_start']))
            if self.gpx_data['segments']:
                last = self.gpx_data['segments'][-1]
                points.append((last['lat_end'], last['lon_end']))
            
        if not points:
            return

        # Generate thumbnail
        
        # Calculate bounds
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        
        # Create image
        w, h = 200, 150
        padding = 10
        img = Image.new('RGBA', (w, h), (0, 0, 0, 128)) # Semi-transparent background
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        
        # Scale
        lat_range = max_lat - min_lat
        lon_range = max_lon - min_lon
        
        if lat_range == 0 or lon_range == 0:
            return
            
        scale_x = (w - 2 * padding) / lon_range
        scale_y = (h - 2 * padding) / lat_range
        scale = min(scale_x, scale_y)
        
        # Transform function
        def transform(lat, lon):
            x = padding + (lon - min_lon) * scale
            y = h - (padding + (lat - min_lat) * scale) # Invert Y for screen coords
            return x, y
            
        # Draw track
        screen_points = [transform(lat, lon) for lat, lon in points]
        draw.line(screen_points, fill=(0, 255, 0, 255), width=2)
        
        # Store for overlay (Tkinter)
        self.track_thumbnail_img = ImageTk.PhotoImage(img)
        self.track_transform_func = transform
        self.track_bounds = (min_lat, max_lat, min_lon, max_lon)
        
        # Store for overlay (OpenCV)
        # Convert PIL RGBA to numpy array
        pil_array = np.array(img)
        # Convert RGBA to BGRA for OpenCV
        if HAS_CV2:
            self.track_thumbnail = cv2.cvtColor(pil_array, cv2.COLOR_RGBA2BGRA)
            # Store transform parameters for _draw_overlay_on_frame
            # Format: (min_lat, min_lon, scale, h, padding, lon_correction=1.0)
            self.track_transform = (min_lat, min_lon, scale, h, padding, 1.0)
        
    # 已移除：GPMD 流索引与解析函数（get_gpmd_stream_index / extract_gpmd_data / parse_gpmd_structure）

    def _smooth_gpx_data(self):
        """对GPX数据进行平滑处理 (坐标和航向)"""
        if not self.gpx_data or 'segments' not in self.gpx_data:
            return
            
        segments = self.gpx_data['segments']
        if not segments:
            return
            
        n = len(segments)
        # 提取 lat/lon
        lats = []
        lons = []
        for s in segments:
            lats.append(s['lat_start'])
            lons.append(s['lon_start'])
        # 添加最后一个点
        lats.append(segments[-1]['lat_end'])
        lons.append(segments[-1]['lon_end'])
        
        lats = np.array(lats)
        lons = np.array(lons)
        
        # 1. 坐标平滑 (简单的滑动平均)
        window_size = 5 # 减小窗口以保留转弯细节
        if len(lats) > window_size:
            kernel = np.ones(window_size) / window_size
            pad_width = window_size // 2
            smooth_lats = np.convolve(np.pad(lats, (pad_width, pad_width), mode='edge'), kernel, mode='valid')
            smooth_lons = np.convolve(np.pad(lons, (pad_width, pad_width), mode='edge'), kernel, mode='valid')
            
            # 截断多余的 (如果卷积后长度不一致)
            smooth_lats = smooth_lats[:len(lats)]
            smooth_lons = smooth_lons[:len(lons)]
        else:
            smooth_lats = lats
            smooth_lons = lons
        
        # 2. 计算航向 (Heading)
        headings = []
        for i in range(len(smooth_lats) - 1):
            lat1, lon1 = smooth_lats[i], smooth_lons[i]
            lat2, lon2 = smooth_lats[i+1], smooth_lons[i+1]
            
            dy = (lat2 - lat1)
            dx = (lon2 - lon1) * math.cos(math.radians(lat1))
            
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                h = 0.0 if not headings else headings[-1]
            else:
                h = math.degrees(math.atan2(dx, dy))
                if h < 0: h += 360
            headings.append(h)
            
        # 补全最后一个航向
        if headings:
            headings.append(headings[-1])
        else:
            headings = [0.0] * len(smooth_lats)
            
        # 3. 航向平滑
        if len(headings) > window_size:
            rad_headings = np.radians(headings)
            sin_h = np.sin(rad_headings)
            cos_h = np.cos(rad_headings)
            
            pad_width = window_size // 2
            smooth_sin = np.convolve(np.pad(sin_h, (pad_width, pad_width), mode='edge'), kernel, mode='valid')
            smooth_cos = np.convolve(np.pad(cos_h, (pad_width, pad_width), mode='edge'), kernel, mode='valid')
            
            smooth_headings = np.degrees(np.arctan2(smooth_sin, smooth_cos))
            smooth_headings = (smooth_headings + 360) % 360
            smooth_headings = smooth_headings[:len(headings)]
        else:
            smooth_headings = np.array(headings)
            
        # 保存结果
        smoothed_segments = []
        for i in range(n):
            s = segments[i].copy()
            s['lat'] = smooth_lats[i]
            s['lon'] = smooth_lons[i]
            s['heading'] = smooth_headings[i]
            smoothed_segments.append(s)
            
        self.gpx_data['smoothed_segments'] = smoothed_segments
        
        # 保存平滑后的数组，供快速绘图使用
        self.smooth_lats = smooth_lats
        self.smooth_lons = smooth_lons
        # smooth_lats/lons 长度是 n+1 (包含最后一个点)
        
        self._last_idx = 0

    def _get_smoothed_state(self, t):
        """获取指定时间的平滑状态 (lat, lon, heading)"""
        if not self.gpx_data or 'smoothed_segments' not in self.gpx_data:
            return None
            
        segs = self.gpx_data['smoothed_segments']
        if not segs:
            return None

        # 二分查找
        low, high = 0, len(segs) - 1
        idx = -1
        
        # 优化：从上次索引开始搜索
        if hasattr(self, '_last_idx') and 0 <= self._last_idx < len(segs):
            if segs[self._last_idx]['start'] <= t <= segs[self._last_idx]['end']:
                idx = self._last_idx
        
        if idx == -1:
            while low <= high:
                mid = (low + high) // 2
                s = segs[mid]
                if s['start'] <= t <= s['end']:
                    idx = mid
                    break
                elif t < s['start']:
                    high = mid - 1
                else:
                    low = mid + 1
        
        if idx != -1:
            self._last_idx = idx
            s = segs[idx]
            # 插值
            dur = s['end'] - s['start']
            ratio = 0.0
            if dur > 0.001:
                ratio = (t - s['start']) / dur
            
            # 下一个点
            next_s = segs[idx+1] if idx < len(segs)-1 else s
            
            # 线性插值
            lat = s['lat'] + (next_s['lat'] - s['lat']) * ratio
            lon = s['lon'] + (next_s['lon'] - s['lon']) * ratio
            
            # 航向插值 (处理0/360)
            h1 = s['heading']
            h2 = next_s['heading']
            
            diff = h2 - h1
            if diff > 180: diff -= 360
            elif diff < -180: diff += 360
            
            heading = (h1 + diff * ratio) % 360
            
            return lat, lon, heading
            
        return None

    def _haversine_distance(self, lat1, lon1, lat2, lon2):
        """Calculate haversine distance between two points in meters"""
        R = 6371000 # Earth radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c

    def import_video(self):
        """导入视频（添加到时间轴）"""
        file_path = filedialog.askopenfilename(
            title="导入视频",
            filetypes=[("视频文件", "*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.m4v")]
        )
        
        if file_path:
            # TODO: 添加到剪辑片段列表
            self.update_status(f"导入视频: {os.path.basename(file_path)}")
    
    def import_gpx(self):
        """导入GPX文件"""
        if not self.video_path:
            messagebox.showwarning("警告", "请先加载视频文件！")
            return

        file_path = filedialog.askopenfilename(
            title="导入GPX文件",
            filetypes=[("GPX文件", "*.gpx"), ("所有文件", "*.*")]
        )
        
        if file_path:
            self.load_gpx_data(self.video_path, gpx_path=file_path)

    def load_gpx_data(self, video_path, gpx_path=None):
        """加载对应的GPX数据"""
        try:
            if not gpx_path:
                # 寻找同名GPX文件或ride.gpx
                video_dir = os.path.dirname(video_path)
                
                # 1. 尝试 ride.gpx (优先级最高)
                check_path = os.path.join(video_dir, 'ride.gpx')
                if os.path.exists(check_path):
                    gpx_path = check_path
                
                # 2. 如果没找到，尝试当前目录下的 ride.gpx
                if not gpx_path and os.path.exists('ride.gpx'):
                    gpx_path = 'ride.gpx'
                
                # 3. 尝试同名GPX
                if not gpx_path:
                    base_name = os.path.splitext(os.path.basename(video_path))[0]
                    check_path = os.path.join(video_dir, f"{base_name}.gpx")
                    if os.path.exists(check_path):
                        gpx_path = check_path
                
            if not gpx_path:
                return

            points, name, gpx_start_time = self._parse_gpx_file(gpx_path)
            
            if not points:
                return

            speeds = self._calculate_speeds(points)
            
            # 处理时间并建立查询结构
            segments = []
            
            # 尝试获取视频开始时间以进行同步
            video_start_time, method = self._get_video_creation_time(video_path)
            
            # 计算初始偏移量
            if video_start_time and gpx_start_time:
                # 偏移量 = 视频开始时间 - GPX开始时间
                initial_offset = (video_start_time - gpx_start_time).total_seconds()
                self.gpx_offset = initial_offset
                
                msg = f"自动同步GPX: 偏移 {self.gpx_offset:.2f}秒\n视频时间: {video_start_time} ({method})\nGPX时间: {gpx_start_time}"
                self.update_status(msg)
                print(msg)
                
                # 弹出提示让用户确认时间
                messagebox.showinfo("时间同步信息", msg)
            else:
                self.gpx_offset = 0.0
                
            for i in range(len(speeds)):
                p1 = points[i]
                p2 = points[i+1]
                t1 = p1[3]
                t2 = p2[3]
                
                if t1 and t2:
                    # 计算相对于GPX起点的秒数
                    rel_t1 = (t1 - gpx_start_time).total_seconds()
                    rel_t2 = (t2 - gpx_start_time).total_seconds()
                    
                    # 获取该段的心率（取起点的心率）
                    hr = points[i][4] if len(points[i]) > 4 else 0
                    
                    segments.append({
                        'start': rel_t1,
                        'end': rel_t2,
                        'speed': speeds[i],
                        'hr': hr,
                        'ele_start': points[i][2],
                        'ele_end': points[i+1][2],
                        'lat_start': points[i][0],
                        'lon_start': points[i][1],
                        'lat_end': points[i+1][0],
                        'lon_end': points[i+1][1]
                    })
            
            # 保险起见，按时间排序
            segments.sort(key=lambda s: (s['start'], s['end']))
            
            self.gpx_data = {'segments': segments, 'name': name, 'start_time': gpx_start_time}
            
            # 生成全量轨迹缩略图 (始终显示完整轨迹)
            all_points = []
            for seg in segments:
                all_points.append((seg['lat_start'], seg['lon_start']))
            # 添加最后一点
            if segments:
                all_points.append((segments[-1]['lat_end'], segments[-1]['lon_end']))
                
            self.track_thumbnail, self.track_transform = self.generate_track_thumbnail(all_points)
            
            self.update_status(f"已加载GPX数据: {name}")
            
            # 如果暂停状态，刷新当前帧以显示叠加层
            if not self.playing and self.cap:
                self.seek_to_frame(self.current_frame_pos)
            
            # 更新对齐页控件
            if hasattr(self, 'update_align_controls'):
                self.update_align_controls()
            
            # 平滑GPX数据
            self._smooth_gpx_data()
            
            # 更新速度曲线
            if hasattr(self, 'update_data_charts'):
                self.update_data_charts()
            
        except Exception as e:
            print(f"GPX加载失败: {e}")
            self.update_status(f"GPX加载失败: {e}")

    def _parse_gpx_file(self, gpx_path):
        """解析GPX文件"""
        try:
            dom = xml.dom.minidom.parse(gpx_path)
            gpx = dom.documentElement
            
            # 获取名称
            name = "Unknown"
            trk = gpx.getElementsByTagName('trk')
            if trk:
                name_nodes = trk[0].getElementsByTagName('name')
                if name_nodes and name_nodes[0].firstChild:
                    name = name_nodes[0].firstChild.data
            
            points = []
            
            # 解析轨迹点
            trkpts = gpx.getElementsByTagName('trkpt')
            for trkpt in trkpts:
                lat = float(trkpt.getAttribute('lat'))
                lon = float(trkpt.getAttribute('lon'))
                
                ele = 0.0
                ele_nodes = trkpt.getElementsByTagName('ele')
                if ele_nodes and ele_nodes[0].firstChild:
                    ele = float(ele_nodes[0].firstChild.data)
                
                time_obj = None
                time_nodes = trkpt.getElementsByTagName('time')
                if time_nodes and time_nodes[0].firstChild:
                    time_str = time_nodes[0].firstChild.data
                    time_obj = self._parse_to_utc_datetime(time_str)
                
                hr = 0
                spd_kph = None
                # 尝试获取心率
                extensions = trkpt.getElementsByTagName('extensions')
                if extensions:
                    # 尝试多种常见的命名空间
                    for tag in ['gpxtpx:hr', 'ns3:hr', 'hr']:
                        hr_nodes = extensions[0].getElementsByTagName(tag)
                        if hr_nodes and hr_nodes[0].firstChild:
                            hr = int(hr_nodes[0].firstChild.data)
                            break
                    # 尝试速度 (单位多为 m/s)
                    for tag in ['gpxtpx:speed', 'ns3:speed', 'speed']:
                        sp_nodes = extensions[0].getElementsByTagName(tag)
                        if sp_nodes and sp_nodes[0].firstChild:
                            try:
                                sp_mps = float(sp_nodes[0].firstChild.data)
                                spd_kph = sp_mps * 3.6
                            except:
                                pass
                            break
                
                # points: (lat, lon, ele, time, hr, opt_speed_kph)
                points.append((lat, lon, ele, time_obj, hr, spd_kph))
            
            if not points:
                return None, None, None
                
            # 过滤掉无效时间点
            points = [p for p in points if p[3] is not None]
            
            if not points:
                return None, None, None

            start_time = points[0][3]
            return points, name, start_time
            
        except Exception as e:
            print(f"解析GPX出错: {e}")
            return None, None, None


    def _calculate_speeds(self, points):
        """计算两点之间的速度 (km/h)
        优先使用 GPX 扩展中提供的速度(若存在，取相邻两点速度的平均值)，否则回退为距离/时间计算
        并做轻度平滑
        """
        speeds = []
        # 简单计算每两点间的速度
        raw_speeds = []
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]
            
            # 优先使用扩展速度
            s1 = p1[5] if len(p1) > 5 else None
            s2 = p2[5] if len(p2) > 5 else None
            if s1 is not None and s2 is not None and s1 > 0 and s2 > 0:
                speed_kph = (s1 + s2) / 2.0
            else:
                dist = self._haversine_distance(p1[0], p1[1], p2[0], p2[1])
                time_diff = (p2[3] - p1[3]).total_seconds()
                if time_diff > 0:
                    speed_kph = (dist / time_diff) * 3.6
                else:
                    speed_kph = 0
            raw_speeds.append(speed_kph)
        
        # 平滑处理 (移动平均)
        if len(raw_speeds) > 0:
            # 使用更小的窗口，保留加速/下坡峰值
            window_size = 3
            for i in range(len(raw_speeds)):
                start = max(0, i - window_size // 2)
                end = min(len(raw_speeds), i + window_size // 2 + 1)
                speeds.append(sum(raw_speeds[start:end]) / (end - start))
            return speeds
            
        return []

    def _haversine_distance(self, lat1, lon1, lat2, lon2):
        """计算两点间的距离 (米)"""
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _get_video_creation_time(self, video_path):
        """获取视频创建时间 (尝试返回 UTC 时间)"""
        creation_time = None
        method = "Unknown"
        
        # 1. 尝试使用 ffprobe 获取元数据 (JSON)
        ffprobe_cmd = self._get_ffprobe_cmd()
        if ffprobe_cmd:
            try:
                cmd = ffprobe_cmd + [
                    '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_format',
                    '-show_streams',
                    video_path
                ]
                
                startupinfo = None
                if platform.system() == 'Windows':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                output = subprocess.check_output(cmd, startupinfo=startupinfo).decode('utf-8')
                data = json.loads(output)
                
                # Check format tags
                if 'format' in data and 'tags' in data['format']:
                    tags = data['format']['tags']
                    if 'creation_time' in tags:
                        creation_time = self._parse_iso8601(tags['creation_time'])
                        if creation_time:
                            method = "FFprobe Metadata (JSON)"
                
                # Check stream tags (first video stream) if not found yet
                if not creation_time:
                    for stream in data.get('streams', []):
                        if stream.get('codec_type') == 'video':
                            if 'tags' in stream and 'creation_time' in stream['tags']:
                                 creation_time = self._parse_iso8601(stream['tags']['creation_time'])
                                 if creation_time:
                                     method = "FFprobe Stream Metadata (JSON)"
                                     break
            except Exception as e:
                print(f"ffprobe JSON获取时间失败: {e}")

        # 2. 如果元数据获取失败，回退到文件系统时间
        if not creation_time:
            try:
                # 优先使用修改时间 (mtime)，因为它在复制时通常保持不变
                mtime = os.path.getmtime(video_path)
                # 转换为 UTC 时间 (Aware)
                creation_time = datetime.fromtimestamp(mtime, timezone.utc)
                method = "File System MTime (UTC)"
            except:
                pass
            
        print(f"视频时间检测结果: {creation_time} (Method: {method})")
        return creation_time, method

    def generate_track_thumbnail(self, points):
        """生成轨迹缩略图"""
        if not points:
            return None, None
            
        lats = np.array([p[0] for p in points])
        lons = np.array([p[1] for p in points])
        
        # 数据平滑 (移动平均)
        if len(points) > 10:
            window_size = min(len(points) // 5, 20) # 动态窗口大小，最大20
            if window_size > 2:
                kernel = np.ones(window_size) / window_size
                # 使用 'valid' 模式会减少点数，使用 'same' 模式边缘会有误差
                # 这里我们使用 pad 模式来保持点数并减少边缘效应
                lats = np.convolve(np.pad(lats, (window_size//2, window_size//2), mode='edge'), kernel, mode='valid')
                lons = np.convolve(np.pad(lons, (window_size//2, window_size//2), mode='edge'), kernel, mode='valid')
        
        min_lat, max_lat = np.min(lats), np.max(lats)
        min_lon, max_lon = np.min(lons), np.max(lons)
        
        # 缩略图尺寸
        w, h = 200, 150
        padding = 10
        
        # 计算缩放比例 (引入地理校正)
        mid_lat = np.radians((min_lat + max_lat) / 2)
        lon_correction = np.cos(mid_lat)
        
        lat_range = max_lat - min_lat
        lon_range = (max_lon - min_lon) * lon_correction
        
        if lat_range == 0 or lon_range == 0:
            return None, None
            
        # 保持比例
        scale_x = (w - 2 * padding) / lon_range
        scale_y = (h - 2 * padding) / lat_range
        scale = min(scale_x, scale_y)
        
        # 创建空白图像 (BGRA) - 使用透明背景
        thumbnail = np.zeros((h, w, 4), dtype=np.uint8)
        # 半透明背景 (灰色, alpha=100)
        thumbnail[:] = [50, 50, 50, 100]
        
        # 转换坐标点
        pts = []
        for lat, lon in zip(lats, lons):
            x = int(padding + (lon - min_lon) * lon_correction * scale)
            y = int(h - padding - (lat - min_lat) * scale) # 纬度越高y越小
            pts.append([x, y])
            
        pts = np.array(pts, np.int32)
        pts = pts.reshape((-1, 1, 2))
        
        # 绘制轨迹 (白色)
        cv2.polylines(thumbnail, [pts], False, (255, 255, 255, 255), 2, cv2.LINE_AA)
        
        # 绘制起点(绿色)和终点(红色)
        start_pt = tuple(pts[0][0])
        end_pt = tuple(pts[-1][0])
        cv2.circle(thumbnail, start_pt, 4, (0, 255, 0, 255), -1)
        cv2.circle(thumbnail, end_pt, 4, (0, 0, 255, 255), -1)
        
        return thumbnail, (min_lat, min_lon, scale, h, padding, lon_correction)

    def update_track_thumbnail_by_offset(self):
        """不再根据offset更新缩略图，改为始终显示全量轨迹"""
        # 已改为在 load_gpx_data 中生成全量轨迹缩略图
        pass


    def draw_speed_gauge(self, frame, speed, max_speed=60, center=None, radius=60):
        """绘制模拟速度表盘"""
        if center is None:
            h, w = frame.shape[:2]
            center = (w - radius - 30, h - radius - 30)
        
        x, y = center
        
        # 1. 绘制半透明背景
        overlay = frame.copy()
        cv2.circle(overlay, center, radius, (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        
        # 2. 绘制外圈 (从135度到405度，共270度)
        start_angle = 135
        end_angle = 405
        total_angle = 270
        
        # 绘制刻度
        # 大刻度：每10km/h一个
        for i in range(0, max_speed + 1, 10):
            angle = start_angle + (i / max_speed) * total_angle
            angle_rad = math.radians(angle)
            
            # 大刻度线
            p1_x = int(x + (radius - 15) * math.cos(angle_rad))
            p1_y = int(y + (radius - 15) * math.sin(angle_rad))
            p2_x = int(x + radius * math.cos(angle_rad))
            p2_y = int(y + radius * math.sin(angle_rad))
            
            cv2.line(frame, (p1_x, p1_y), (p2_x, p2_y), (255, 255, 255), 2)
            
            # 数字
            if i % 20 == 0: # 每20显示数字
                text_x = int(x + (radius - 30) * math.cos(angle_rad))
                text_y = int(y + (radius - 30) * math.sin(angle_rad))
                
                # 简单偏移修正文字居中
                text_x -= 8
                text_y += 5
                
                cv2.putText(frame, str(i), (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

        # 3. 绘制指针
        # 限制速度在0-max_speed之间
        disp_speed = max(0, min(speed, max_speed))
        needle_angle = start_angle + (disp_speed / max_speed) * total_angle
        needle_rad = math.radians(needle_angle)
        
        needle_len = radius - 10
        needle_x = int(x + needle_len * math.cos(needle_rad))
        needle_y = int(y + needle_len * math.sin(needle_rad))
        
        cv2.line(frame, center, (needle_x, needle_y), (0, 0, 255), 3)
        
        # 4. 中心圆点
        cv2.circle(frame, center, 5, (255, 0, 0), -1)
        cv2.circle(frame, center, 3, (200, 200, 200), -1)
        
        # 5. 显示当前数字速度 (在下方)
        text_speed = f"{speed:.1f}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size = cv2.getTextSize(text_speed, font, 0.8, 2)[0]
        
        # 在表盘下方中心
        tx = x - text_size[0] // 2
        ty = y + radius // 2 + 10
        
        cv2.putText(frame, text_speed, (tx, ty), font, 0.8, (255, 255, 255), 2)
        
        # 单位
        cv2.putText(frame, "km/h", (x - 15, y + radius // 2 + 25), font, 0.4, (200, 200, 200), 1)

    def get_data_at_time(self, current_seconds):
        """获取指定时间点的GPX数据（速度、心率、经度、纬度）"""
        if not self.gpx_data:
            self.debug_info = {'status': 'No Data'}
            return 0.0, 0, None, None
            
        # 仅处理 GPX 段结构
        if isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data:
            segments = self.gpx_data['segments']
            if not segments:
                return 0.0, 0, None, None
            
            # 应用时间偏移
            target_time = current_seconds + self.gpx_offset
            
            self.debug_info['target_time'] = target_time
            self.debug_info['offset'] = self.gpx_offset
            
            # 二分查找
            low = 0
            high = len(segments) - 1
            
            while low <= high:
                mid = (low + high) // 2
                seg = segments[mid]
                if seg['start'] <= target_time <= seg['end']:
                    # 线性插值计算坐标
                    duration = seg['end'] - seg['start']
                    ratio = 0.0
                    if duration > 0.001:
                        ratio = (target_time - seg['start']) / duration
                        lat = seg['lat_start'] + (seg['lat_end'] - seg['lat_start']) * ratio
                        lon = seg['lon_start'] + (seg['lon_end'] - seg['lon_start']) * ratio
                    else:
                        lat = seg['lat_start']
                        lon = seg['lon_start']
                    
                    self.debug_info['seg_idx'] = mid
                    self.debug_info['seg_start'] = seg['start']
                    self.debug_info['seg_end'] = seg['end']
                    self.debug_info['ratio'] = ratio
                    self.debug_info['lat'] = lat
                    self.debug_info['lon'] = lon
                    
                    return seg['speed'], seg.get('hr', 0), lat, lon
                elif seg['start'] > target_time:
                    high = mid - 1
                else:
                    low = mid + 1
                    
            # 如果超出范围，返回最近的数据或者默认值
            if target_time < segments[0]['start']:
                s = segments[0]
                self.debug_info['status'] = 'Before Start'
                self.debug_info['seg_idx'] = 0
                self.debug_info['lat'] = s.get('lat_start')
                return s['speed'], s.get('hr', 0), s.get('lat_start'), s.get('lon_start')
            if target_time > segments[-1]['end']:
                s = segments[-1]
                self.debug_info['status'] = 'After End'
                self.debug_info['seg_idx'] = len(segments) - 1
                self.debug_info['lat'] = s.get('lat_end')
                return s['speed'], s.get('hr', 0), s.get('lat_end'), s.get('lon_end')
                
            self.debug_info['status'] = 'Not Found'
            return 0.0, 0, None, None
            
        return 0.0, 0, None, None

    def decrease_offset(self, event=None):
        """减少GPX时间偏移"""
        self.gpx_offset -= 1.0
        self.update_status(f"GPX偏移: {self.gpx_offset:+.1f}s")
        # 更新缩略图
        self.update_track_thumbnail_by_offset()
        # 刷新当前帧以更新显示
        if not self.playing:
            self.seek_to_frame(self.current_frame_pos)
            
    def increase_offset(self, event=None):
        """增加GPX时间偏移"""
        self.gpx_offset += 1.0
        self.update_status(f"GPX偏移: {self.gpx_offset:+.1f}s")
        # 更新缩略图
        self.update_track_thumbnail_by_offset()
        if not self.playing:
            self.seek_to_frame(self.current_frame_pos)

    def decrease_offset_fine(self, event=None):
        """减少GPX时间偏移 (0.1s)"""
        self.gpx_offset -= 0.1
        self.update_status(f"GPX偏移: {self.gpx_offset:+.1f}s")
        self.update_track_thumbnail_by_offset()
        if not self.playing:
            self.seek_to_frame(self.current_frame_pos)

    def increase_offset_fine(self, event=None):
        """增加GPX时间偏移 (0.1s)"""
        self.gpx_offset += 0.1
        self.update_status(f"GPX偏移: {self.gpx_offset:+.1f}s")
        self.update_track_thumbnail_by_offset()
        if not self.playing:
            self.seek_to_frame(self.current_frame_pos)

    def save_project(self):
        """保存项目"""
        file_path = filedialog.asksaveasfilename(
            title="保存项目",
            defaultextension=".veproj",
            filetypes=[("视频编辑项目", "*.veproj"), ("所有文件", "*.*")]
        )
        
        if file_path:
            # TODO: 保存项目文件
            self.update_status(f"项目已保存: {file_path}")
            messagebox.showinfo("保存成功", f"项目已保存到:\n{file_path}")
    
    def open_project(self):
        """打开项目"""
        file_path = filedialog.askopenfilename(
            title="打开项目",
            filetypes=[("视频编辑项目", "*.veproj"), ("所有文件", "*.*")]
        )
        
        if file_path:
            # TODO: 加载项目文件
            self.update_status(f"项目已打开: {file_path}")
    
    def export_video(self):
        """导出视频"""
        if not self.video_path:
            messagebox.showwarning("警告", "请先加载视频文件！")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="导出视频",
            defaultextension=".mp4",
            filetypes=[
                ("MP4视频", "*.mp4"),
                ("AVI视频", "*.avi"),
                ("所有文件", "*.*")
            ]
        )
        
        if file_path:
            # 禁用界面交互
            self.root.config(cursor="watch")
            self.update_status(f"正在导出视频: {file_path}...")
            
            # 启动导出线程
            threading.Thread(target=self._export_video_worker, args=(file_path,), daemon=True).start()

    def _export_video_worker(self, output_path):
        """视频导出工作线程"""
        try:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                raise Exception("无法打开源视频")
            
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 使用临时文件存储无音频视频
            temp_video_path = output_path + ".temp.mp4"
            
            # 根据扩展名选择编码器
            ext = os.path.splitext(output_path)[1].lower()
            if ext == '.avi':
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            else:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            
            out = cv2.VideoWriter(temp_video_path, fourcc, fps, (width, height))
            
            if not out.isOpened():
                raise Exception("无法创建输出视频流")
            
            processed_frames = 0
            last_update_time = time.time()
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 叠加GPX
                if self.gpx_data:
                    current_seconds = processed_frames / fps if fps > 0 else 0
                    self._draw_overlay_on_frame(frame, current_seconds)
                
                out.write(frame)
                
                processed_frames += 1
                
                # 更新进度 (每0.5秒)
                if time.time() - last_update_time > 0.5:
                    progress = (processed_frames / total_frames) * 100
                    self.root.after(0, self.update_status, f"导出中: {progress:.1f}%")
                    last_update_time = time.time()
            
            cap.release()
            out.release()
            
            # 检查是否有 ffmpeg
            has_ffmpeg = shutil.which('ffmpeg') is not None
            
            # 合并音频
            if has_ffmpeg: 
                self.root.after(0, self.update_status, "正在合并音频...")
                try:
                    ext_audio = self.external_audio_path if self.external_audio_path and os.path.exists(self.external_audio_path) else None
                    remove_orig = bool(self.remove_original_audio_var.get())
                    if ext_audio and remove_orig:
                        cmd = [
                            'ffmpeg', '-y', '-v', 'error',
                            '-i', temp_video_path,
                            '-i', ext_audio,
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-map', '0:v:0',
                            '-map', '1:a:0',
                            output_path
                        ]
                    elif ext_audio and not remove_orig:
                        cmd = [
                            'ffmpeg', '-y', '-v', 'error',
                            '-i', temp_video_path,
                            '-i', self.video_path,
                            '-i', ext_audio,
                            '-filter_complex', '[1:a][2:a]amix=inputs=2:duration=longest:dropout_transition=2[aout]',
                            '-map', '0:v:0',
                            '-map', '[aout]',
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            output_path
                        ]
                    elif not ext_audio and remove_orig:
                        cmd = [
                            'ffmpeg', '-y', '-v', 'error',
                            '-i', temp_video_path,
                            '-c:v', 'copy',
                            '-an',
                            output_path
                        ]
                    else:
                        cmd = [
                            'ffmpeg', '-y', '-v', 'error',
                            '-i', temp_video_path,
                            '-i', self.video_path,
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-map', '0:v:0',
                            '-map', '1:a:0',
                            output_path
                        ]
                    
                    startupinfo = None
                    if platform.system() == 'Windows':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        
                    subprocess.check_call(cmd, startupinfo=startupinfo)
                    
                    # 删除临时文件
                    if os.path.exists(temp_video_path):
                        os.remove(temp_video_path)
                        
                except Exception as e:
                    print(f"音频合并失败: {e}")
                    # 如果合并失败，保留无音频版本
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(temp_video_path, output_path)
                    self.root.after(0, messagebox.showwarning, "警告", f"音频合并失败，导出的视频将没有声音。\n错误: {e}")
            else:
                if bool(self.remove_original_audio_var.get()):
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(temp_video_path, output_path)
                    self.root.after(0, messagebox.showinfo, "提示", "未检测到FFmpeg，已导出无声视频。")
                else:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(temp_video_path, output_path)
                    self.root.after(0, messagebox.showinfo, "提示", "未检测到FFmpeg，导出的视频将没有声音。")

            self.root.after(0, self.update_status, f"导出完成: {output_path}")
            self.root.after(0, messagebox.showinfo, "成功", "视频导出成功！")
            
        except Exception as e:
            self.root.after(0, self.update_status, f"导出失败: {e}")
            self.root.after(0, messagebox.showerror, "错误", f"导出失败: {e}")
        finally:
            self.root.after(0, self.root.config, {"cursor": ""})
    
    # ============ 编辑功能 ============
    
    def undo(self):
        """撤销"""
        self.update_status("撤销操作")
    
    def redo(self):
        """重做"""
        self.update_status("重做操作")
    
    def cut_clip(self):
        """剪切片段"""
        self.update_status("剪切片段")
    
    def copy_clip(self):
        """复制片段"""
        self.update_status("复制片段")
    
    def paste_clip(self):
        """粘贴片段"""
        self.update_status("粘贴片段")
    
    def delete_clip(self):
        """删除片段"""
        selected = self.clip_tree.selection()
        if selected:
            self.clip_tree.delete(selected)
            self.update_status("删除片段")
        else:
            messagebox.showinfo("提示", "请先选择要删除的片段")
    
    # ============ 剪辑功能 ============
    
    def split_clip(self):
        """分割片段"""
        if not self.video_path:
            messagebox.showwarning("警告", "请先加载视频文件！")
            return
        
        current_time = self.progress_var.get()
        self.update_status(f"在 {self.format_time(current_time)} 处分割")
        messagebox.showinfo("分割", "视频分割功能待实现")
    
    def merge_clips(self):
        """合并片段"""
        selected = self.clip_tree.selection()
        if len(selected) < 2:
            messagebox.showinfo("提示", "请至少选择两个片段进行合并")
            return
        
        self.update_status("合并片段")
        messagebox.showinfo("合并", "片段合并功能待实现")
    
    def set_in_point(self):
        """设置入点"""
        current_time = self.progress_var.get()
        self.update_status(f"设置入点: {self.format_time(current_time)}")
    
    def set_out_point(self):
        """设置出点"""
        current_time = self.progress_var.get()
        self.update_status(f"设置出点: {self.format_time(current_time)}")
    
    def add_transition(self):
        """添加转场效果"""
        messagebox.showinfo("转场", "转场效果功能待实现")
    
    def add_filter(self):
        """添加滤镜"""
        messagebox.showinfo("滤镜", "滤镜功能待实现")
    
    # ============ 播放控制 ============
    
    def toggle_play(self):
        """播放/暂停"""
        if not self.video_path or self.cap is None:
            messagebox.showwarning("警告", "请先加载视频文件！")
            return
        
        if not HAS_CV2:
            messagebox.showwarning("警告", "未安装 opencv-python，无法播放视频！")
            return
        
        if not self.playing:
            # 开始播放
            self.playing = True
            self.play_btn['text'] = "⏸ 暂停"
            self.update_status("播放中...")
            self.start_audio_playback(self._current_time())
            
            # 启动播放线程
            if self.play_thread is None or not self.play_thread.is_alive():
                self.play_thread = threading.Thread(target=self._play_video_loop, daemon=True)
                self.play_thread.start()
        else:
            # 暂停播放
            self.playing = False
            self.play_btn['text'] = "▶ 播放"
            self.update_status("已暂停")
            self.stop_audio_playback()
    
    def _has_ffplay(self):
        return shutil.which('ffplay') is not None
    
    def _current_time(self):
        fps = self.video_info.get('fps', 30.0)
        return self.current_frame_pos / fps if fps > 0 else 0
    
    def start_audio_playback(self, start_time=None):
        if self.is_muted or self.volume <= 0:
            return
        if not self._has_ffplay():
            return
        if start_time is None:
            start_time = self._current_time()
        try:
            self.stop_audio_playback()
            vol = max(0, min(100, int(self.volume * 100)))
            spd = self.playback_speed
            if spd < 0.5:
                spd = 0.5
            elif spd > 2.0:
                spd = 2.0
            use_external = bool(self.preview_external_audio_var.get() and self.external_audio_path and os.path.exists(self.external_audio_path))
            src = self.external_audio_path if use_external else self.video_path
            cmd = ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'error', '-ss', f'{start_time:.3f}', '-i', src, '-volume', str(vol), '-af', f'atempo={spd}']
            if platform.system() == 'Windows':
                creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                self.audio_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
            else:
                self.audio_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            self.audio_proc = None
    
    def stop_audio_playback(self):
        if self.audio_proc is not None:
            try:
                if platform.system() == 'Windows':
                    self.audio_proc.terminate()
                else:
                    try:
                        os.killpg(self.audio_proc.pid, signal.SIGTERM)
                    except Exception:
                        self.audio_proc.terminate()
                try:
                    self.audio_proc.wait(timeout=0.5)
                except Exception:
                    pass
                if self.audio_proc.poll() is None:
                    if platform.system() != 'Windows':
                        try:
                            os.killpg(self.audio_proc.pid, signal.SIGKILL)
                        except Exception:
                            self.audio_proc.kill()
                    else:
                        self.audio_proc.kill()
            except Exception:
                pass
            self.audio_proc = None
    
    def _play_video_loop(self):
        """视频播放循环（在独立线程中运行）"""
        if self.cap is None:
            return
            
        fps = self.video_info.get('fps', 30.0)
        if fps <= 0: fps = 30.0
        
        # 目标帧间隔
        target_interval = 1.0 / (fps * self.playback_speed)
        
        last_display_time = time.time()
        
        # 记录开始播放的时间和帧，用于同步
        start_play_time = time.time()
        start_frame_pos = self.current_frame_pos
        
        while self.playing and self.cap is not None:
            loop_start_time = time.time()
            
            # 重新计算目标间隔（速度可能改变）
            target_interval = 1.0 / (fps * self.playback_speed)
            
            # 1. 检查是否需要跳帧
            # 计算理论上应该播放到的帧
            elapsed_time = loop_start_time - start_play_time
            expected_frame = start_frame_pos + int(elapsed_time * fps * self.playback_speed)
            
            # 获取当前实际帧位置
            current_pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            
            # 如果落后超过5帧，尝试跳帧追赶
            frame_diff = expected_frame - current_pos
            if frame_diff > 5:
                # 一次最多跳10帧，防止卡死
                skip_count = min(frame_diff - 1, 10)
                for _ in range(skip_count):
                    self.cap.grab()
            
            # 2. 读取下一帧
            ret, frame = self.cap.read()
            
            if not ret:
                # 播放结束
                self.playing = False
                # 在主线程更新UI
                self.root.after(0, lambda: self.play_btn.config(text="▶ 播放"))
                self.root.after(0, lambda: self.update_status("播放完成"))
                self.stop_audio_playback()
                break
            
            self.current_frame_pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            
            # 3. 只有当距离上次显示超过一定间隔时才更新UI（避免过度刷新）
            current_time = time.time()
            # 限制UI刷新率，例如最高30fps或60fps
            if current_time - last_display_time >= 0.03: 
                # 预处理：在工作线程中缩放图像
                target_w, target_h = self.target_display_size
                if target_w < 100: target_w = 640
                if target_h < 100: target_h = 360
                
                img_h, img_w = frame.shape[:2]
                
                # 只有当原图比目标大很多时才缩放
                if img_w > target_w * 1.1 or img_h > target_h * 1.1:
                    ratio = min(target_w / img_w, target_h / img_h)
                    new_w = int(img_w * ratio)
                    new_h = int(img_h * ratio)
                    display_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                else:
                    display_frame = frame.copy()
                
                # 传递当前时间点，确保显示准确
                current_seconds = self.current_frame_pos / fps
                self.root.after(0, self._display_frame, display_frame, current_seconds)
                
                # 更新进度条 (每0.5秒更新一次，避免频繁刷新)
                if current_time - last_display_time > 0.5:
                    self.root.after(0, self.progress_var.set, current_seconds)
                    self.root.after(0, self._update_time_display, current_seconds)
                
                last_display_time = current_time
            
            # 4. 帧率控制
            process_time = time.time() - loop_start_time
            sleep_time = target_interval - process_time
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # 如果处理太慢，不需要sleep，下一次循环会通过跳帧逻辑来补偿
                pass
    
    def _display_frame(self, frame, current_seconds=None):
        """显示视频帧"""
        if frame is None:
            return

        # 1. 检查是否需要缩放 (如果传入的是原始大图)
        canvas_width = self.video_canvas.winfo_width()
        canvas_height = self.video_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = 640
            canvas_height = 360
            
        img_h, img_w = frame.shape[:2]
        
        # 如果图像比画布大很多，说明是原始帧，需要缩放
        if img_w > canvas_width * 1.2 or img_h > canvas_height * 1.2:
             ratio = min(canvas_width / img_w, canvas_height / img_h)
             new_w = int(img_w * ratio)
             new_h = int(img_h * ratio)
             frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # 2. 叠加GPX信息
        if self.gpx_data:
            if current_seconds is None:
                fps = self.video_info.get('fps', 30.0)
                current_seconds = self.current_frame_pos / fps if fps > 0 else 0
            self._draw_overlay_on_frame(frame, current_seconds)
            
        # 转换为 RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # 转换为 ImageTk
        img = Image.fromarray(rgb_frame)
        photo = ImageTk.PhotoImage(image=img)
        
        # 更新画布
        self.video_canvas.delete("all")
        # 居中显示
        x_center = canvas_width // 2
        y_center = canvas_height // 2
        self.video_canvas.create_image(x_center, y_center, image=photo, anchor=tk.CENTER)
        self.video_canvas.image = photo # 保持引用防止被垃圾回收
        # 记录当前帧在画布的位置和大小，供鼠标拖放使用
        self.display_frame_rect = (x_center - img.width // 2, y_center - img.height // 2, img.width, img.height)
    
    def _get_telemetry_rect_px(self, frame_w, frame_h):
        x_frac, y_frac, w_frac, h_frac = self.telemetry_rect_rel
        w = max(100, int(w_frac * frame_w))
        h = max(60, int(h_frac * frame_h))
        x = max(0, min(int(x_frac * frame_w), frame_w - w))
        y = max(0, min(int(y_frac * frame_h), frame_h - h))
        return x, y, w, h
    
    def on_video_panel_press(self, event):
        if not self.display_frame_rect:
            return
        fx, fy, fw, fh = self.display_frame_rect
        mx, my = event.x - fx, event.y - fy
        if mx < 0 or my < 0 or mx > fw or my > fh:
            return
        px, py, pw, ph = self._get_telemetry_rect_px(fw, fh)
        if px <= mx <= px+pw and py <= my <= py+ph:
            if (px+pw - mx) <= self.telemetry_resize_margin and (py+ph - my) <= self.telemetry_resize_margin:
                self.telemetry_resizing = True
            else:
                self.telemetry_dragging = True
                self.telemetry_drag_start = (mx - px, my - py)
    
    def on_video_panel_drag(self, event):
        if not self.display_frame_rect:
            return
        if not (self.telemetry_dragging or self.telemetry_resizing):
            return
        fx, fy, fw, fh = self.display_frame_rect
        mx, my = event.x - fx, event.y - fy
        px, py, pw, ph = self._get_telemetry_rect_px(fw, fh)
        if self.telemetry_dragging and self.telemetry_drag_start:
            dx, dy = self.telemetry_drag_start
            new_x = max(0, min(mx - dx, fw - pw))
            new_y = max(0, min(my - dy, fh - ph))
            self.telemetry_rect_rel[0] = new_x / fw
            self.telemetry_rect_rel[1] = new_y / fh
        elif self.telemetry_resizing:
            new_w = max(100, min(max(10, mx - px), fw - px))
            new_h = max(60, min(max(10, my - py), fh - py))
            self.telemetry_rect_rel[2] = new_w / fw
            self.telemetry_rect_rel[3] = new_h / fh
        if not self.playing and self.cap is not None:
            self.seek_to_frame(self.current_frame_pos)
    
    def on_video_panel_release(self, event):
        self.telemetry_dragging = False
        self.telemetry_resizing = False
        self.telemetry_drag_start = None
    
    def _draw_overlay_on_frame(self, frame, current_seconds):
        """在帧上绘制GPX叠加层"""
        if not self.gpx_data:
            return

        speed, hr, lat, lon = self.get_data_at_time(current_seconds)
        h, w = frame.shape[:2]
        
        # 1. 绘制轨迹 (局部跟随视角)
        self._draw_local_track_view(frame, current_seconds)

        # 2. 绘制浮动遥测面板（速度/海拔/坡度）
        if hasattr(self, '_draw_telemetry_panel'):
            self._draw_telemetry_panel(frame, current_seconds, speed)

        # 4. 显示调试信息 (始终显示在左上角)
        debug_y = 40
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.5, w / 1000.0)
        thickness = max(1, int(font_scale * 2))
        
        # 如果有偏移，优先显示
        if abs(self.gpx_offset) > 0.1:
            text_offset = f"Offset: {self.gpx_offset:+.1f}s"
            cv2.putText(frame, text_offset, (20, debug_y), font, font_scale * 0.8, (0, 0, 0), thickness + 2)
            cv2.putText(frame, text_offset, (20, debug_y), font, font_scale * 0.8, (255, 255, 0), thickness)
            debug_y += 30
        
        if self.debug_info:
            for k, v in self.debug_info.items():
                # 跳过已经显示的offset
                if k == 'offset': continue
                
                if isinstance(v, float):
                    text = f"{k}: {v:.3f}"
                else:
                    text = f"{k}: {v}"
                
                # 黑色描边
                cv2.putText(frame, text, (20, debug_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
                # 红色文字
                cv2.putText(frame, text, (20, debug_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                debug_y += 25

                    
    def _draw_local_track_view(self, frame, current_seconds):
        """绘制局部跟随视角轨迹"""
        if not self.gpx_data or 'smoothed_segments' not in self.gpx_data:
            return

        # 获取当前状态
        # 1. 插值获取当前平滑后的 lat, lon, heading
        t = current_seconds + self.gpx_offset
        state = self._get_smoothed_state(t)
        if not state:
            return
            
        cur_lat, cur_lon, cur_heading = state
        
        # 参数设置
        h, w = frame.shape[:2]
        # 动态调整视图大小
        view_size = min(int(w * 0.3), int(h * 0.4))
        view_size = max(150, min(view_size, 300))
        
        scale = 1.0      # 缩放比例 (像素/米) - 300米高度大约对应 0.5-1.0
        # 300m 高度，假设垂直FOV 60度 -> 地面可见高度 ~346m
        # 如果视图高度200px -> 346m -> scale = 0.58 px/m
        scale = view_size / 350.0 
        
        cam_behind_m = 100.0 # 摄像机在后方100米
        
        # 创建透明图层
        overlay = np.zeros((view_size, view_size, 4), dtype=np.uint8)
        
        # 绘图中心 (摄像机位置)
        # 调整摄像机位置到视图下方，以便看到前方更多路况
        cx, cy = view_size // 2, view_size - 30
        
        # 坐标转换函数: 世界坐标(米) -> 屏幕坐标(像素)
        # 1. 以摄像机为原点 (当前点前100米) -> 世界坐标
        # 2. 旋转 (heading向上)
        # 3. 缩放 + 平移
        
        # 预先筛选附近的点 (比如前后1000米范围)
        # 简单起见，遍历所有点（优化：可以使用空间索引或时间索引）
        # 这里使用时间窗口优化：前后 120秒
        
        segs = self.gpx_data['smoothed_segments']
        
        # 找到当前时间对应的索引附近的点
        # 简单遍历优化：只取当前时间前后N个点
        # 假设1秒1个点，取前后300个点
        
        points_to_draw = []
        
        # 旋转矩阵 (逆时针旋转 -heading + 90? No, heading is usually 0=North, 90=East)
        # 我们希望 Heading 指向 屏幕上方 (-Y)
        # 原始 Heading: 0=N, 90=E. 
        # 屏幕坐标: 0度=右, 90度=下 (通常数学定义)
        # 让我们使用标准变换：
        # dx, dy 是相对于当前点的墨卡托投影距离 (米)
        # 旋转角度 theta = -heading (把当前方向转到正北/正上)
        # 实际上我们希望 Heading 对应屏幕 UP (-y)
        
        rad_heading = math.radians(cur_heading)
        cos_h = math.cos(rad_heading)
        sin_h = math.sin(rad_heading)
        
        # 摄像机位置 (相对于当前点): 位于后方100米
        # 也就是说，摄像机坐标 = 当前点坐标 - 100m * 方向向量
        # 但我们是以摄像机为中心绘图。
        # 所以当前点在摄像机坐标系中的位置是 (0, 100) (假设Y轴向前)
        
        # 使用numpy加速计算
        # 1. 确定索引范围
        start_idx = max(0, self._last_idx - 300)
        end_idx = min(len(segs), self._last_idx + 300)
        
        if start_idx >= end_idx:
            return

        # 检查是否有缓存的numpy数组
        if hasattr(self, 'smooth_lats') and hasattr(self, 'smooth_lons'):
            lats = self.smooth_lats[start_idx:end_idx]
            lons = self.smooth_lons[start_idx:end_idx]
        else:
            # 尝试重新生成平滑数据以获取缓存 (Lazy Init)
            self._smooth_gpx_data()
            if hasattr(self, 'smooth_lats') and hasattr(self, 'smooth_lons'):
                lats = self.smooth_lats[start_idx:end_idx]
                lons = self.smooth_lons[start_idx:end_idx]
            else:
                # 回退到列表推导
                lats = np.array([s['lat'] for s in segs[start_idx:end_idx]])
                lons = np.array([s['lon'] for s in segs[start_idx:end_idx]])
            
        # 向量化计算
        # 1. 相对距离 (米)
        dys = (lats - cur_lat) * 111320
        dxs = (lons - cur_lon) * 111320 * math.cos(math.radians(cur_lat))
        
        # 2. 旋转
        # Local Forward (Y') = dy * cos(h) + dx * sin(h)
        # Local Right (X') = dx * cos(h) - dy * sin(h)
        local_ys = dys * cos_h + dxs * sin_h
        local_xs = dxs * cos_h - dys * sin_h
        
        # 3. 转换为屏幕坐标
        sxs = cx + local_xs * scale
        sys = cy - (local_ys + cam_behind_m) * scale
        
        # 4. 过滤屏幕外的点 (可选优化)
        # margin = 50
        # mask = (sxs >= -margin) & (sxs < view_size + margin) & (sys >= -margin) & (sys < view_size + margin)
        # sxs = sxs[mask]
        # sys = sys[mask]
        
        # 转换并堆叠
        pts_screen = np.stack((sxs, sys), axis=1).astype(np.int32)

        
        # 绘制轨迹
        if len(pts_screen) > 1:
            cv2.polylines(overlay, [pts_screen], False, (0, 255, 0, 200), 2, cv2.LINE_AA)
            
        # 绘制当前点 (实心圆)
        # 当前点在 Local (0,0)
        curr_sx = int(cx)
        curr_sy = int(cy - cam_behind_m * scale)
        cv2.circle(overlay, (curr_sx, curr_sy), 5, (0, 0, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(overlay, (curr_sx, curr_sy), 7, (255, 255, 255, 255), 1, cv2.LINE_AA)
        
        # 叠加到 Frame
        h, w = frame.shape[:2]
        x_offset = w - view_size - 20
        y_offset = 20
        
        roi = frame[y_offset:y_offset+view_size, x_offset:x_offset+view_size]
        
        # 简单 Alpha 混合 (使用整数运算优化)
        # 假设 overlay 是 BGRA
        
        # 分离通道
        ov_bgr = overlay[:, :, :3].astype(np.int32)
        ov_alpha = overlay[:, :, 3].astype(np.int32)[:, :, np.newaxis]
        
        roi_int = roi.astype(np.int32)
        
        # 混合: (src * alpha + dst * (255 - alpha)) / 255
        # 使用位移优化除法 ( >> 8 ) 近似 / 256, 或者直接 / 255
        # 为了准确性使用 / 255
        
        blended = (ov_bgr * ov_alpha + roi_int * (255 - ov_alpha)) // 255
        blended = blended.astype(np.uint8)
        
        frame[y_offset:y_offset+view_size, x_offset:x_offset+view_size] = blended
        
        # 画个边框
        cv2.rectangle(frame, (x_offset, y_offset), (x_offset+view_size, y_offset+view_size), (255, 255, 255), 1)
        cv2.putText(frame, "Follow Cam", (x_offset + 5, y_offset + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    
    def _get_ele_grade_at_time(self, current_seconds):
        if not (isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data):
            return None, None
        segs = self.gpx_data['segments']
        if not segs:
            return None, None
        t = current_seconds + self.gpx_offset
        low, high = 0, len(segs) - 1
        idx = None
        while low <= high:
            mid = (low + high) // 2
            s = segs[mid]
            if s['start'] <= t <= s['end']:
                idx = mid
                break
            if t < s['start']:
                high = mid - 1
            else:
                low = mid + 1
        if idx is None:
            return None, None
        seg = segs[idx]
        dur = seg['end'] - seg['start']
        ratio = 0.0
        if dur > 0.001:
            ratio = (t - seg['start']) / dur
        ele_s = seg.get('ele_start', None)
        ele_e = seg.get('ele_end', None)
        ele = None
        if ele_s is not None and ele_e is not None:
            ele = ele_s + (ele_e - ele_s) * ratio
        # 坡度（%）
        lat1, lon1 = seg.get('lat_start'), seg.get('lon_start')
        lat2, lon2 = seg.get('lat_end'), seg.get('lon_end')
        grade = None
        if None not in (lat1, lon1, lat2, lon2) and ele_s is not None and ele_e is not None:
            dist = self._haversine_distance(lat1, lon1, lat2, lon2)
            if dist > 1:
                grade = (ele_e - ele_s) / dist * 100.0
            else:
                grade = 0.0
        return ele, grade
    
    def _draw_telemetry_panel(self, frame, current_seconds, speed):
        h, w = frame.shape[:2]
        x, y, ww, hh = self._get_telemetry_rect_px(w, h)
        x2 = min(w, x + ww)
        y2 = min(h, y + hh)
        ww = max(0, x2 - x)
        hh = max(0, y2 - y)
        if ww < 10 or hh < 10:
            return
        overlay = frame.copy()
        cv2.rectangle(overlay, (x, y), (x+ww, y+hh), (0, 0, 0), -1)
        alpha = 0.45
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        cv2.rectangle(frame, (x, y), (x+ww, y+hh), (255, 255, 255), 1)
        cv2.rectangle(frame, (x+ww-12, y+hh-12), (x+ww-2, y+hh-2), (200, 200, 200), -1)
        cv2.rectangle(frame, (x+ww-12, y+hh-12), (x+ww-2, y+hh-2), (80, 80, 80), 1)
        ele, grade = self._get_ele_grade_at_time(current_seconds)
        texts = []
        texts.append(f"速度  {speed:5.1f} km/h")
        if ele is not None:
            texts.append(f"海拔  {ele:5.0f} m")
        if grade is not None:
            texts.append(f"坡度  {grade:+4.1f}%")
        try:
            from PIL import Image as PILImage
            from PIL import ImageDraw, ImageFont
            roi = frame[y:y+hh, x:x+ww]
            pil_img = PILImage.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)
            base_size = max(14, min(int(hh * 0.28), int(ww * 0.14)))
            font = None
            font_paths = []
            sysname = platform.system()
            if sysname == 'Darwin':
                font_paths = [
                    '/System/Library/Fonts/PingFang.ttc',
                    '/System/Library/Fonts/STHeiti Light.ttc',
                    '/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',
                ]
            elif sysname == 'Windows':
                font_paths = [
                    'C:\\Windows\\Fonts\\msyh.ttc',
                    'C:\\Windows\\Fonts\\simhei.ttf',
                    'C:\\Windows\\Fonts\\msyh.ttf',
                ]
            else:
                font_paths = [
                    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                    '/usr/share/fonts/truetype/arphic/ukai.ttc',
                    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
                ]
            for p in font_paths:
                if os.path.exists(p):
                    try:
                        font = ImageFont.truetype(p, base_size)
                        break
                    except Exception:
                        pass
            if font is None:
                try:
                    font = ImageFont.load_default()
                except Exception:
                    font = None
            ty = 8
            for t in texts:
                if font:
                    draw.text((12+1, ty+1), t, font=font, fill=(0, 0, 0, 255))
                    draw.text((12, ty), t, font=font, fill=(255, 255, 255, 255))
                else:
                    draw.text((12+1, ty+1), t, fill=(0, 0, 0, 255))
                    draw.text((12, ty), t, fill=(255, 255, 255, 255))
                ty += int(base_size * 1.1)
            new_roi = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            frame[y:y+hh, x:x+ww] = new_roi
        except Exception:
            pass

    def _update_time_display(self, current_time):
        """更新时间显示（在主线程中调用）"""
        duration = self.video_info.get('duration', 0)
        self.time_label.config(text=f"{self.format_time(current_time)} / {self.format_time(duration)}")
        
        # 更新播放头位置
        self.draw_playhead(current_time)
        
        # 更新图表光标
        if self.gpx_data and hasattr(self, 'update_chart_cursors'):
            gpx_offset = getattr(self, 'gpx_offset', 0.0)
            gpx_time = current_time + gpx_offset
            
            # 处理反向
            if getattr(self, 'align_reverse_var', None) and self.align_reverse_var.get():
                gpx_duration = self.get_gpx_duration()
                gpx_time = gpx_duration - gpx_time
            
            self.update_chart_cursors(gpx_time)
            
            # 更新对齐视图光标（如果在播放时也想看到地图上的点移动）
            if hasattr(self, 'update_align_cursor'):
                self.update_align_cursor(gpx_time)
    
    def seek_to_frame(self, frame_number):
        """跳转到指定帧"""
        if self.cap is None:
            return
        
        try:
            # 确保帧数在有效范围内
            frame_number = max(0, min(frame_number, max(0, self.total_frames - 1)))
            
            # 尝试设置帧位置
            success = self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            
            if not success:
                # 如果直接设置失败，尝试从开头读取到目标位置
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                for _ in range(frame_number):
                    ret, _ = self.cap.read()
                    if not ret:
                        break
            
            self.current_frame_pos = frame_number
            
            # 读取并显示该帧
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self._display_frame(frame)
                
                # 更新进度条
                fps = self.video_info.get('fps', 30.0)
                current_time = frame_number / fps if fps > 0 else 0
                self.progress_var.set(current_time)
                self._update_time_display(current_time)
            else:
                # 如果读取失败，尝试显示一个黑色帧
                width = self.video_info.get('width', 640)
                height = self.video_info.get('height', 480)
                black_frame = np.zeros((height, width, 3), dtype=np.uint8)
                self._display_frame(black_frame)
                
        except Exception as e:
            print(f"跳转帧时出错: {e}")
            self.update_status(f"跳转帧失败: {str(e)}")
            # 尝试显示错误信息
            width = self.video_info.get('width', 640)
            height = self.video_info.get('height', 480)
            error_frame = np.zeros((height, width, 3), dtype=np.uint8)
            # 这里可以添加错误文本显示
            self._display_frame(error_frame)
    
    def stop_play(self):
        """停止播放"""
        self.playing = False
        self.play_btn['text'] = "▶ 播放"
        if self.cap is not None:
            self.seek_to_frame(0)
        self.update_status("已停止")
        self.stop_audio_playback()
    
    def prev_frame(self):
        """上一帧"""
        if self.cap is None:
            return
        
        fps = self.video_info.get('fps', 30.0)
        frame_step = max(1, int(fps * 0.033))  # 大约一帧
        new_frame = max(0, self.current_frame_pos - frame_step)
        self.seek_to_frame(new_frame)
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def next_frame(self):
        """下一帧"""
        if self.cap is None:
            return
        
        fps = self.video_info.get('fps', 30.0)
        frame_step = max(1, int(fps * 0.033))  # 大约一帧
        new_frame = min(self.total_frames - 1, self.current_frame_pos + frame_step)
        self.seek_to_frame(new_frame)
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def jump_to_start(self):
        """跳转到开始"""
        if self.cap is not None:
            self.seek_to_frame(0)
        else:
            self.progress_var.set(0)
        self.update_status("跳转到开始")
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def jump_to_end(self):
        """跳转到结束"""
        if self.cap is not None and self.total_frames > 0:
            self.seek_to_frame(self.total_frames - 1)
        else:
            duration = self.video_info.get('duration', 100)
            self.progress_var.set(duration)
        self.update_status("跳转到结束")
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def rewind_5s(self):
        """后退5秒"""
        if self.cap is not None and self.total_frames > 0:
            current_time = self.current_frame_pos / self.video_info.get('fps', 30.0)
            new_time = max(0, current_time - 5)
            new_frame = int(new_time * self.video_info.get('fps', 30.0))
            self.seek_to_frame(new_frame)
            self.update_status("后退5秒")
            if self.playing:
                self.stop_audio_playback()
                self.start_audio_playback(self._current_time())
    
    def forward_5s(self):
        """前进5秒"""
        if self.cap is not None and self.total_frames > 0:
            current_time = self.current_frame_pos / self.video_info.get('fps', 30.0)
            duration = self.video_info.get('duration', 0)
            new_time = min(duration, current_time + 5)
            new_frame = int(new_time * self.video_info.get('fps', 30.0))
            self.seek_to_frame(new_frame)
            self.update_status("前进5秒")
            if self.playing:
                self.stop_audio_playback()
                self.start_audio_playback(self._current_time())
    
    def toggle_mute(self):
        """切换静音"""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.mute_btn.config(text="🔇")
            self.volume_scale.set(0)
        else:
            self.mute_btn.config(text="🔊")
            self.volume_scale.set(100)
        self.update_status("静音" if self.is_muted else "取消静音")
        if self.playing:
            if self.is_muted:
                self.stop_audio_playback()
            else:
                self.stop_audio_playback()
                self.start_audio_playback(self._current_time())

    def import_audio_track(self):
        file_path = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=[("音频文件", "*.mp3 *.wav *.m4a *.aac *.flac"), ("所有文件", "*.*")]
        )
        if not file_path:
            return
        self.external_audio_path = file_path
        name = os.path.basename(file_path)
        if hasattr(self, 'audio_file_label'):
            self.audio_file_label.config(text=name)
        self.update_status(f"已选择音轨: {name}")
        if self.playing and bool(self.preview_external_audio_var.get()):
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())

    def on_preview_audio_toggle(self):
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def on_volume_change(self, value):
        """音量改变"""
        self.volume = float(value) / 100.0
        if self.volume == 0:
            self.mute_btn.config(text="🔇")
            self.is_muted = True
        else:
            self.mute_btn.config(text="🔊")
            self.is_muted = False
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def on_speed_change(self, event):
        """播放速度改变"""
        speed_str = self.speed_var.get()
        self.playback_speed = float(speed_str.replace('x', ''))
        self.update_status(f"播放速度: {speed_str}")
        if self.playing:
            self.stop_audio_playback()
            self.start_audio_playback(self._current_time())
    
    def toggle_loop(self):
        """切换循环播放"""
        self.loop_playback = not self.loop_playback
        status = "开启" if self.loop_playback else "关闭"
        self.update_status(f"循环播放已{status}")
    
    def update_clip_list(self):
        """更新剪辑片段列表"""
        # 清空现有列表
        for item in self.clip_tree.get_children():
            self.clip_tree.delete(item)
            
        # 添加片段
        fps = self.video_info.get('fps', 30.0)
        for clip in self.clips:
            start_time = clip['start_frame'] / fps
            end_time = clip['end_frame'] / fps
            duration = end_time - start_time
            
            self.clip_tree.insert('', 'end', values=(
                clip['name'],
                self.format_time(start_time),
                self.format_time(end_time),
                f"{duration:.2f}s"
            ))
            
        # 更新时间轴上的片段显示
        self.draw_timeline_tracks()

    def split_clip(self):
        """分割当前片段"""
        if not self.video_info or not self.clips:
            return
            
        current_frame = self.current_frame_pos
        
        # 查找当前时间点所在的片段
        target_clip = None
        target_index = -1
        
        for i, clip in enumerate(self.clips):
            if clip['start_frame'] < current_frame < clip['end_frame']:
                target_clip = clip
                target_index = i
                break
        
        if target_clip:
            # 创建新片段
            new_clip = target_clip.copy()
            new_clip['id'] = f"clip_{len(self.clips)}"
            new_clip['name'] = f"片段_{len(self.clips) + 1}"
            new_clip['start_frame'] = current_frame
            new_clip['end_frame'] = target_clip['end_frame']
            
            # 修改原片段
            target_clip['end_frame'] = current_frame
            
            # 插入新片段
            self.clips.insert(target_index + 1, new_clip)
            
            # 更新列表
            self.update_clip_list()
            self.update_status(f"已在 {self.format_time(current_frame / self.video_info.get('fps', 30.0))} 处分割片段")
        else:
            self.update_status("当前位置无法分割（不在任何片段中间）")
    
    # ============ UI更新方法 ============
    
    def update_video_info(self):
        """更新视频信息显示"""
        if self.video_info:
            info_text = f"""文件: {self.video_info.get('name', 'N/A')}
分辨率: {self.video_info.get('width', 0)}x{self.video_info.get('height', 0)}
帧率: {self.video_info.get('fps', 0):.2f} fps
时长: {self.format_time(self.video_info.get('duration', 0))}
编码: {self.video_info.get('codec', 'N/A')}"""
            
            # self.info_text.config(state=tk.NORMAL)
            # self.info_text.delete(1.0, tk.END)
            # self.info_text.insert(1.0, info_text)
            # self.info_text.config(state=tk.DISABLED)
            
            # 更新状态栏
            self.resolution_label.config(text=f"{self.video_info.get('width', 0)}x{self.video_info.get('height', 0)}")
            self.fps_label.config(text=f"{self.video_info.get('fps', 0):.1f} fps")
            
            # 更新进度条最大值
            self.progress_scale.config(to=self.video_info.get('duration', 100))
    
    def update_preview_label(self, text):
        """更新预览标签"""
        if self.preview_label:
            display_text = "" if text is None else str(text)
            if display_text.strip():
                self.preview_label.config(text=display_text)
                self.preview_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            else:
                self.preview_label.config(text="")
                self.preview_label.place_forget()
    
    def update_status(self, message):
        """更新状态栏"""
        self.status_label.config(text=message)
    
    def format_time(self, seconds):
        """格式化时间显示"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    # ============ 时间轴相关 ============
    
    def init_timeline(self):
        """初始化时间轴"""
        if not self.video_info:
            return
        
        duration = self.video_info.get('duration', 100)
        self.draw_timeline_ruler(duration)
        self.draw_timeline_tracks()
    
    def draw_timeline_ruler(self, duration):
        """绘制时间标尺"""
        self.ruler_canvas.delete("all")
        
        # 计算总宽度
        total_width = duration * self.timeline_scale
        if total_width < 1:
            total_width = 1
            
        # 更新滚动区域
        self.ruler_canvas.config(scrollregion=(0, 0, total_width, 25))
        self.timeline_canvas.config(scrollregion=(0, 0, total_width, 150))
        
        # 绘制刻度
        # 根据缩放比例决定刻度间隔
        if self.timeline_scale < 1: # 缩小很多，每10秒或更多一个刻度
            step = 60
        elif self.timeline_scale < 5: # 每10秒
            step = 10
        elif self.timeline_scale < 20: # 每5秒
            step = 5
        else: # 每1秒
            step = 1
            
        for second in range(0, int(duration) + 1, step):
            x = second * self.timeline_scale
            self.ruler_canvas.create_line(x, 0, x, 25, fill="#666666", width=1)
            self.ruler_canvas.create_text(x + 2, 12, text=self.format_time(second),
                                         anchor=tk.W, font=("Arial", 8))
    
    def draw_timeline_tracks(self):
        """绘制时间轴轨道"""
        self.timeline_canvas.delete("all")
        
        if not self.video_info:
            return
            
        # 绘制剪辑片段
        fps = self.video_info.get('fps', 30.0)
        track_height = 40
        track_y = 10
        
        # 1. 绘制缩略图背景 (如果有)
        has_thumbs = hasattr(self, 'timeline_thumbnails') and self.timeline_thumbnails
        if has_thumbs:
            # 遍历所有缩略图
            for t_sec, photo in self.timeline_thumbnails.items():
                x = t_sec * self.timeline_scale
                # 绘制图片，垂直居中于轨道
                self.timeline_canvas.create_image(x, track_y + track_height/2, image=photo, anchor=tk.W)
        
        for i, clip in enumerate(self.clips):
            start_time = clip['start_frame'] / fps
            end_time = clip['end_frame'] / fps
            
            x1 = start_time * self.timeline_scale
            x2 = end_time * self.timeline_scale
            
            # 绘制片段矩形
            if has_thumbs:
                # 如果有缩略图，只画边框，以便看到缩略图
                self.timeline_canvas.create_rectangle(x1, track_y, x2, track_y + track_height,
                                                     fill="", outline="#4a90e2", width=2, tags=("clip", clip['id']))
                # 增加一个半透明黑色遮罩来增加文字对比度？(Tkinter不支持)
                # 我们可以画文字背景
            else:
                # 原来的逻辑：实心填充
                color = "#4a90e2" if i % 2 == 0 else "#357abd"
                self.timeline_canvas.create_rectangle(x1, track_y, x2, track_y + track_height,
                                                     fill=color, outline="white", tags=("clip", clip['id']))
            
            # 绘制片段名称
            if x2 - x1 > 20: # 如果够宽才显示文字
                # 添加文字阴影效果以提高可读性
                self.timeline_canvas.create_text(x1 + 6, track_y + track_height/2 + 1,
                                                text=clip['name'], anchor=tk.W, fill="black",
                                                font=("Arial", 9))
                self.timeline_canvas.create_text(x1 + 5, track_y + track_height/2,
                                                text=clip['name'], anchor=tk.W, fill="white",
                                                font=("Arial", 9))
    
    def draw_playhead(self, current_time):
        """绘制播放头"""
        self.timeline_canvas.delete("playhead")
        self.ruler_canvas.delete("playhead")
        
        if self.timeline_scale <= 0:
            return
            
        x = current_time * self.timeline_scale
        
        # 在标尺上绘制
        self.ruler_canvas.create_line(x, 0, x, 25, fill="red", width=2, tags="playhead")
        # 绘制倒三角指示器
        self.ruler_canvas.create_polygon(x-4, 0, x+4, 0, x, 8, fill="red", tags="playhead")
        
        # 在轨道上绘制
        height = 150 # 估计高度
        if self.timeline_canvas.winfo_height() > 1:
            height = self.timeline_canvas.winfo_height()
            
        self.timeline_canvas.create_line(x, 0, x, height, fill="red", width=1, tags="playhead")
    
    def on_timeline_click(self, event):
        """时间轴点击/拖动事件"""
        if not self.video_info:
            return
            
        canvas = event.widget
        # 获取画布坐标（考虑滚动）
        x = canvas.canvasx(event.x)
        
        if self.timeline_scale > 0:
            time = x / self.timeline_scale
            duration = self.video_info.get('duration', 0)
            
            # 限制时间范围
            time = max(0, min(time, duration))
            
            # 立即更新播放头以获得更好响应
            self.draw_playhead(time)
            
            # 跳转视频
            fps = self.video_info.get('fps', 30.0)
            frame = int(time * fps)
            self.seek_to_frame(frame)

    def on_progress_press(self, event):
        """进度条按下事件"""
        self.is_dragging_progress = True
        if self.playing:
            self.was_playing_before_drag = True
            # 暂停播放以避免冲突
            self.playing = False
            self.play_btn['text'] = "▶ 播放"
            self.update_status("暂停(拖动)")
        else:
            self.was_playing_before_drag = False

    def on_progress_release(self, event):
        """进度条释放事件"""
        self.is_dragging_progress = False
        if self.was_playing_before_drag:
            # 恢复播放
            self.toggle_play()

    def on_progress_change(self, value):
        """进度条改变事件"""
        if self.cap is None:
            return
        
        current_time = float(value)
        fps = self.video_info.get('fps', 30.0)
        frame_number = int(current_time * fps)
        
        # 只有在不播放时才允许手动跳转
        if not self.playing:
            self.seek_to_frame(frame_number)
        
        duration = self.video_info.get('duration', 0)
        self.time_label.config(text=f"{self.format_time(current_time)} / {self.format_time(duration)}")
    
    def on_clip_select(self, event):
        """片段选择事件 - 双击跳转"""
        selection = self.clip_tree.selection()
        if selection:
            # 获取选中项的索引
            index = self.clip_tree.index(selection[0])
            if 0 <= index < len(self.clips):
                clip = self.clips[index]
                # 跳转到片段开始位置
                self.seek_to_frame(clip['start_frame'])
                self.update_status(f"跳转到片段: {clip['name']}")
    
    def on_zoom_change(self, event):
        """缩放改变事件"""
        zoom = self.zoom_var.get()
        self.update_status(f"预览缩放: {zoom}")
    
    def timeline_zoom_in(self):
        """时间轴放大"""
        self.timeline_scale *= 1.5
        self.update_timeline()
    
    def timeline_zoom_out(self):
        """时间轴缩小"""
        self.timeline_scale /= 1.5
        self.update_timeline()
    
    def timeline_fit(self):
        """时间轴适应窗口"""
        if self.video_info:
            duration = self.video_info.get('duration', 100)
            width = self.timeline_canvas.winfo_width()
            if width > 0:
                self.timeline_scale = width / duration
                self.update_timeline()

    def start_timeline_thumbnail_generation(self):
        """开始生成时间轴缩略图"""
        if not HAS_CV2 or not HAS_PIL:
            return
            
        # 停止之前的线程（如果可能）
        # Python线程难以强制停止，这里我们通过检查 video_path 是否一致来控制退出
        
        self.timeline_thumbnails = {}
        
        # 启动新线程
        self.thumbnail_thread = threading.Thread(
            target=self._generate_timeline_thumbnails_worker,
            args=(self.video_path,),
            daemon=True
        )
        self.thumbnail_thread.start()
        
    def _generate_timeline_thumbnails_worker(self, current_video_path):
        """生成时间轴缩略图的工作线程"""
        try:
            cap = cv2.VideoCapture(current_video_path)
            if not cap.isOpened():
                return
                
            duration = self.video_info.get('duration', 0)
            if duration <= 0:
                return

            # 根据时长决定采样间隔
            # 目标是生成适量的缩略图，既不影响性能又能覆盖全长
            # 例如每隔一定像素生成一个缩略图
            # 假设缩略图宽度为 60px
            # 但我们在后台生成，不知道当前的 timeline_scale
            # 所以我们可以固定生成一定数量，或者按时间间隔
            
            # 策略：每隔 5-30 秒生成一张，取决于总时长
            # 如果视频短于 1 分钟，每 1 秒一张
            # 如果视频长于 1 小时，每 30 秒一张
            
            if duration < 60:
                interval = 1.0
            elif duration < 600: # 10分钟
                interval = 5.0
            elif duration < 3600: # 1小时
                interval = 10.0
            else:
                interval = 30.0
            
            fps = self.video_info.get('fps', 30.0)
            current_time = 0.0
            
            count = 0
            batch_size = 5 # 每生成5张刷新一次界面
            
            while current_time < duration:
                # 检查是否切换了视频
                if self.video_path != current_video_path:
                    break
                    
                frame_pos = int(current_time * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                ret, frame = cap.read()
                
                if ret:
                    # 调整大小
                    h, w = frame.shape[:2]
                    target_h = 40 # 轨道高度
                    target_w = int(w * (target_h / h))
                    
                    frame_resized = cv2.resize(frame, (target_w, target_h))
                    
                    # 转换为 RGB
                    frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame_rgb)
                    photo = ImageTk.PhotoImage(image)
                    
                    # 存储 (需要在主线程使用，但 ImageTk 对象必须在创建它的线程使用? 不，Tkinter对象通常线程不安全)
                    # ImageTk.PhotoImage 可以在任何线程创建吗？
                    # 文档建议在主线程创建 Tkinter 对象。
                    # 但 Image 对象可以在线程中创建。
                    # 我们可以只存储 Image 对象，在主线程转换为 PhotoImage。
                    # 或者使用 after 将创建操作调度到主线程。
                    
                    # 为了安全，我们将 Image 对象传给主线程
                    count += 1
                    should_refresh = (count % batch_size == 0)
                    self.root.after(0, self._add_thumbnail_to_timeline, current_time, image, should_refresh)
                
                current_time += interval
                time.sleep(0.01) # 避免占用过多CPU
                
            cap.release()
            # 最后确保刷新一次
            self.root.after(0, lambda: self.draw_timeline_tracks())
            
        except Exception as e:
            print(f"生成缩略图出错: {e}")

    def _add_thumbnail_to_timeline(self, time_sec, pil_image, refresh=True):
        """在主线程添加缩略图并刷新"""
        if not HAS_PIL:
            return
            
        try:
            photo = ImageTk.PhotoImage(pil_image)
            self.timeline_thumbnails[time_sec] = photo
            
            # 刷新显示
            # 不要在每次添加都完全重绘，可以分批或者直接绘制这个
            # 但为了简单，我们调用 draw_timeline_tracks
            # 为了避免过于频繁，可以检查是否需要重绘
            if refresh:
                self.draw_timeline_tracks()
        except Exception as e:
            print(f"添加缩略图出错: {e}")

    
    def update_timeline(self):
        """更新时间轴显示"""
        self.init_timeline()
    
    def generate_thumbnail(self):
        """生成视频缩略图"""
        if not HAS_CV2 or self.cap is None:
            return
            
        # 视频缩略图功能已禁用
        return
        
        try:
            # 获取视频中间位置的帧作为缩略图
            middle_frame = max(0, self.total_frames // 2)
            
            # 保存当前位置
            original_pos = self.current_frame_pos
            
            # 尝试跳转到中间帧
            success = self.cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
            if not success:
                # 如果跳转失败，尝试从开头读取
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                # 跳过一些帧到达中间位置
                for _ in range(middle_frame):
                    ret, _ = self.cap.read()
                    if not ret:
                        break
            
            ret, frame = self.cap.read()
            
            if ret and frame is not None:
                # 调整帧大小以适应缩略图显示区域
                canvas_width = self.thumbnail_canvas.winfo_width()
                canvas_height = self.thumbnail_canvas.winfo_height()
                
                if canvas_width > 1 and canvas_height > 1:  # 确保画布已经显示
                    # 计算缩放比例，保持宽高比
                    frame_height, frame_width = frame.shape[:2]
                    scale = min(canvas_width / frame_width, canvas_height / frame_height)
                    
                    new_width = int(frame_width * scale)
                    new_height = int(frame_height * scale)
                    
                    # 调整帧大小
                    resized_frame = cv2.resize(frame, (new_width, new_height))
                    
                    # 转换颜色格式
                    rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
                    
                    # 创建PIL图像
                    if HAS_PIL:
                        pil_image = Image.fromarray(rgb_frame)
                        self.thumbnail_image = ImageTk.PhotoImage(pil_image)
                        
                        # 清空画布并显示图像
                        self.thumbnail_canvas.delete("all")
                        x = (canvas_width - new_width) // 2
                        y = (canvas_height - new_height) // 2
                        self.thumbnail_canvas.create_image(x, y, anchor=tk.NW, image=self.thumbnail_image)
                    
        except Exception as e:
            print(f"生成缩略图失败: {e}")
        finally:
            # 恢复原始帧位置
            if self.cap is not None:
                try:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_pos)
                except:
                    # 如果恢复失败，至少尝试回到开头
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    # ============ 帮助功能 ============
    
    def show_help(self):
        """显示帮助"""
        help_window = tk.Toplevel(self.root)
        help_window.title("使用说明")
        help_window.geometry("700x500")
        
        # 创建主框架
        main_frame = ttk.Frame(help_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建标签页
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # 基本操作标签页
        basic_frame = ttk.Frame(notebook)
        notebook.add(basic_frame, text="基本操作")
        
        basic_text = tk.Text(basic_frame, wrap=tk.WORD, font=default_font, padx=10, pady=10)
        basic_text.pack(fill=tk.BOTH, expand=True)
        
        basic_content = """视频编辑器基本操作说明

1. 文件操作:
   • 文件 -> 打开视频: 加载视频文件 (Ctrl+O)
   • 文件 -> 导入视频: 添加更多视频到项目
   • 文件 -> 保存项目: 保存当前编辑进度 (Ctrl+S)
   • 文件 -> 导出视频: 导出最终视频 (Ctrl+E)

2. 播放控制:
   • 播放/暂停: 空格键或播放按钮
   • 停止: K键或停止按钮
   • 上一帧: ← 键
   • 下一帧: → 键
   • 后退5秒: Shift+← 或 ⏪ 按钮
   • 前进5秒: Shift+→ 或 ⏩ 按钮
   • 跳转到开始: Home 键或 ⏮ 按钮
   • 跳转到结束: End 键或 ⏭ 按钮

3. 音量控制:
   • 静音切换: 点击音量图标
   • 音量调节: 拖动音量滑块

4. 播放速度:
   • 速度调节: 选择播放速度 (0.25x - 2.0x)
   • 循环播放: 在播放菜单中开启/关闭"""
        
        basic_text.insert(1.0, basic_content)
        basic_text.config(state=tk.DISABLED)
        
        # 快捷键标签页
        shortcut_frame = ttk.Frame(notebook)
        notebook.add(shortcut_frame, text="快捷键")
        
        shortcut_text = tk.Text(shortcut_frame, wrap=tk.WORD, font=default_font, padx=10, pady=10)
        shortcut_text.pack(fill=tk.BOTH, expand=True)
        
        shortcut_content = """视频编辑器快捷键大全

文件操作:
• Ctrl+O: 打开视频文件
• Ctrl+S: 保存项目
• Ctrl+Shift+O: 打开项目
• Ctrl+E: 导出视频
• Ctrl+Q: 退出程序

播放控制:
• 空格键: 播放/暂停
• K: 停止播放
• ←: 上一帧
• →: 下一帧
• Shift+←: 后退5秒
• Shift+→: 前进5秒
• Home: 跳转到开始
• End: 跳转到结束

剪辑操作:
• S: 分割片段
• M: 合并片段
• Del: 删除选中片段
• I: 设置入点
• O: 设置出点

编辑操作:
• Ctrl+Z: 撤销 (待实现)
• Ctrl+Y: 重做 (待实现)
• Ctrl+X: 剪切
• Ctrl+C: 复制
• Ctrl+V: 粘贴"""
        
        shortcut_text.insert(1.0, shortcut_content)
        shortcut_text.config(state=tk.DISABLED)
        
        # 剪辑功能标签页
        clip_frame = ttk.Frame(notebook)
        notebook.add(clip_frame, text="剪辑功能")
        
        clip_text = tk.Text(clip_frame, wrap=tk.WORD, font=default_font, padx=10, pady=10)
        clip_text.pack(fill=tk.BOTH, expand=True)
        
        clip_content = """视频编辑器剪辑功能说明

1. 分割片段:
   • 在时间轴上选择分割位置
   • 点击"分割"按钮或按S键
   • 视频将在当前位置分割成两个片段

2. 合并片段:
   • 选择多个相邻的片段
   • 点击"合并"按钮或按M键
   • 选中的片段将合并为一个片段

3. 删除片段:
   • 在时间轴或片段列表中选择要删除的片段
   • 点击"删除"按钮或按Del键
   • 选中的片段将被删除

4. 设置入点/出点:
   • 播放视频到想要设置入点的位置
   • 按I键设置入点
   • 播放视频到想要设置出点的位置
   • 按O键设置出点
   • 可以基于入点和出点创建新片段

5. 时间轴操作:
   • 放大/缩小: 使用时间轴控制按钮
   • 适应窗口: 自动调整时间轴显示
   • 拖动片段: 在时间轴上拖动片段调整位置"""
        
        clip_text.insert(1.0, clip_content)
        clip_text.config(state=tk.DISABLED)
    
    def show_about(self):
        """显示关于"""
        about_text = """视频编辑器 v1.0

基于Python和Tkinter开发的视频编辑软件

功能:
- 视频加载和预览
- 基本剪辑操作
- 时间轴编辑
- 视频导出

开发中..."""
        messagebox.showinfo("关于", about_text)
    
    def cleanup(self):
        """清理资源"""
        # 停止播放
        self.playing = False
        self.stop_audio_playback()
        
        # 等待播放线程结束
        if self.play_thread is not None and self.play_thread.is_alive():
            time.sleep(0.1)  # 等待一小段时间让线程结束
        
        # 释放视频资源
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def on_closing(self):
        """窗口关闭事件"""
        self.cleanup()
        self.root.destroy()


def main():
    """主函数"""
    try:
        root = tk.Tk()
        app = VideoEditorApp(root)
        root.mainloop()
    except KeyboardInterrupt:
        print("\n程序已停止 (KeyboardInterrupt)")
        # 尝试清理资源
        try:
            # 获取 app 实例并清理 (如果存在)
            # 由于 app 是局部变量，这里可能无法直接访问，
            # 但通常 Tkinter 应用会在窗口关闭时调用 cleanup
            pass
        except:
            pass
        
        # 确保退出
        import sys
        sys.exit(0)


if __name__ == "__main__":
    main()
