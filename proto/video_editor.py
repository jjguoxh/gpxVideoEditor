#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频编辑软件 - 主程序
支持视频加载、预览、剪辑、导出等功能
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
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
        
        # GPX 数据
        self.gpx_data = None  # 格式: {'segments': [(start_time, end_time, speed), ...]}
        self.gpx_offset = 0.0  # GPX时间偏移（秒）
        self.track_thumbnail = None # 轨迹缩略图
        self.track_transform = None # 坐标转换参数
        
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
    
    def create_main_panel(self):
        """创建主面板（预览窗口和控制面板）"""
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：视频预览区域
        preview_frame = ttk.LabelFrame(main_container, text="视频预览", padding=10)
        main_container.add(preview_frame, weight=2)
        
        # 视频显示区域
        self.video_canvas = tk.Canvas(preview_frame, bg="#000000", width=640, height=360,
                                      highlightthickness=0, bd=0)
        self.video_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 预览信息标签
        self.preview_label = ttk.Label(preview_frame, text="📹 未加载视频\n\n点击 文件 -> 打开视频 来加载视频文件", 
                                       font=default_font, foreground="gray", justify=tk.CENTER)
        self.preview_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # 播放控制面板
        control_frame = ttk.Frame(preview_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # 播放进度条
        self.progress_var = tk.DoubleVar()
        self.progress_scale = ttk.Scale(control_frame, from_=0, to=100, 
                                        variable=self.progress_var, orient=tk.HORIZONTAL,
                                        command=self.on_progress_change)
        self.progress_scale.pack(fill=tk.X, padx=5, pady=2)
        
        # 绑定鼠标事件以支持拖拽跳转
        self.progress_scale.bind("<ButtonPress-1>", self.on_progress_press)
        self.progress_scale.bind("<ButtonRelease-1>", self.on_progress_release)
        
        # 时间显示和播放控制
        time_frame = ttk.Frame(control_frame)
        time_frame.pack(fill=tk.X, padx=5)
        
        self.time_label = ttk.Label(time_frame, text="00:00:00 / 00:00:00", font=default_font)
        self.time_label.pack(side=tk.LEFT)
        
        # 播放控制按钮组
        control_buttons_frame = ttk.Frame(time_frame)
        control_buttons_frame.pack(side=tk.LEFT, padx=20)
        
        # 播放控制按钮
        ttk.Button(control_buttons_frame, text="⏮", command=self.jump_to_start, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(control_buttons_frame, text="⏪", command=self.rewind_5s, width=3).pack(side=tk.LEFT, padx=1)
        self.play_btn = ttk.Button(control_buttons_frame, text="▶", command=self.toggle_play, width=3)
        self.play_btn.pack(side=tk.LEFT, padx=1)
        ttk.Button(control_buttons_frame, text="⏩", command=self.forward_5s, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(control_buttons_frame, text="⏭", command=self.jump_to_end, width=3).pack(side=tk.LEFT, padx=1)
        
        # 音量控制
        volume_frame = ttk.Frame(time_frame)
        volume_frame.pack(side=tk.RIGHT, padx=5)
        
        self.mute_btn = ttk.Button(volume_frame, text="🔊", command=self.toggle_mute, width=3)
        self.mute_btn.pack(side=tk.LEFT, padx=1)
        
        self.volume_scale = ttk.Scale(volume_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                                     command=self.on_volume_change, length=80)
        self.volume_scale.set(100)
        self.volume_scale.pack(side=tk.LEFT, padx=2)
        
        # 播放速度控制
        speed_frame = ttk.Frame(time_frame)
        speed_frame.pack(side=tk.RIGHT, padx=10)
        
        ttk.Label(speed_frame, text="速度:", font=default_font).pack(side=tk.LEFT, padx=2)
        self.speed_var = tk.StringVar(value="1.0x")
        speed_combo = ttk.Combobox(speed_frame, textvariable=self.speed_var, width=6,
                                   values=["0.25x", "0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"],
                                   state="readonly")
        speed_combo.pack(side=tk.LEFT, padx=2)
        speed_combo.bind('<<ComboboxSelected>>', self.on_speed_change)
        
        # 右侧：属性面板
        property_frame = ttk.LabelFrame(main_container, text="属性", padding=10, width=250)
        main_container.add(property_frame, weight=1)
        
        # 创建属性面板内容
        self.create_property_panel(property_frame)
    
    def create_property_panel(self, parent):
        """创建属性面板"""
        # 视频缩略图预览
        thumbnail_frame = ttk.LabelFrame(parent, text="视频缩略图", padding=5)
        thumbnail_frame.pack(fill=tk.X, pady=5)
        
        self.thumbnail_canvas = tk.Canvas(thumbnail_frame, bg="#2B2B2B", height=120, width=160,
                                          highlightthickness=0, bd=0)
        self.thumbnail_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 视频信息
        info_frame = ttk.LabelFrame(parent, text="视频信息", padding=5)
        info_frame.pack(fill=tk.X, pady=5)
        
        self.info_text = tk.Text(info_frame, height=8, wrap=tk.WORD, font=default_font,
                                 state=tk.DISABLED, relief=tk.FLAT)
        self.info_text.pack(fill=tk.BOTH, expand=True)
        
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
    
    def _parse_iso8601(self, time_str):
        """解析ISO8601时间字符串"""
        try:
            # 处理 '2023-10-01T12:00:00.000000Z'
            if time_str.endswith('Z'):
                time_str = time_str[:-1]
            # 处理可能的毫秒
            if '.' in time_str:
                # 截断到6位微秒，因为Python只支持6位
                main, frac = time_str.split('.')
                frac = frac[:6]
                time_str = f"{main}.{frac}"
            return datetime.fromisoformat(time_str)
        except Exception as e:
            print(f"时间解析错误: {time_str}, {e}")
            return None

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
            
            # 生成缩略图
            self.generate_thumbnail()
            
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
            
            # 优先检查GoPro GPS数据 (GPMD)
            # 如果存在GPMD流，直接使用它，不再尝试加载外部GPX文件
            # 这样可以保证最佳的时间同步
            gpmd_info = self.get_gpmd_stream_index(video_path)
            
            if gpmd_info is not None:
                self.update_status("检测到GoPro GPS数据，正在自动导入...")
                # 自动导入，不询问用户
                self.import_gopro_gps(auto=True)
            else:
                # 否则尝试加载外部GPX文件
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

    def import_gopro_gps(self, auto=False):
        """导入GoPro GPS数据
        :param auto: 是否为自动导入（不显示成功弹窗）
        """
        if not self.video_path:
            messagebox.showinfo("提示", "请先打开一个视频文件")
            return
            
        stream_info = self.get_gpmd_stream_index(self.video_path)
        if stream_info is None:
            messagebox.showinfo("提示", "未在视频中找到GoPro GPS数据 (GPMD流)")
            return
            
        stream_index, start_time = stream_info
            
        self.update_status("正在提取GoPro GPS数据...")
        
        def _process():
            try:
                raw_data = self.extract_gpmd_data(self.video_path, stream_index)
                if not raw_data:
                    self.root.after(0, lambda: messagebox.showerror("错误", "提取数据失败"))
                    return
                    
                points = self.parse_gpmd_structure(raw_data)
                
                if not points:
                    self.root.after(0, lambda: messagebox.showinfo("提示", "未解析到有效的GPS点"))
                    return
                
                # Normalize time_offset by subtracting stream start time if available
                # This handles cases where pts_time is absolute or offset by start_time
                if start_time is not None and start_time > 0:
                    for p in points:
                        p['time_offset'] -= start_time
                
                # Assign timestamps based on GPMD timing
                # Use the time_offset (derived from pts_time) to set the datetime
                if self.video_creation_time:
                    for p in points:
                        # Ensure time_offset is non-negative for datetime calculation?
                        # Actually if pts < start_time, it might be negative.
                        # But usually pts >= start_time.
                        offset = max(0, p['time_offset'])
                        p['time'] = self.video_creation_time + timedelta(seconds=offset)
                else:
                    # Fallback if no video creation time
                    for p in points:
                        p['time'] = datetime.utcfromtimestamp(max(0, p['time_offset']))
                
                # Update data
                self.gpx_data = points
                self.gpx_start_time = points[0]['time']
                self.gpx_end_time = points[-1]['time']
                self.gpx_offset = 0.0 # Perfectly synced by definition
                
                # Recalculate speeds
                self._calculate_speeds_from_points(points)
                
                # Update UI
                self.root.after(0, lambda: self.update_status(f"已导入GoPro GPS数据 ({len(points)}点)"))
                self.root.after(0, self.draw_track_thumbnail)
                
                if not auto:
                    self.root.after(0, lambda: messagebox.showinfo("成功", f"成功导入 {len(points)} 个GPS点\n已自动同步"))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"解析失败: {str(e)}"))

        threading.Thread(target=_process).start()

    def check_and_import_gopro_gps(self):
        """检查并导入GoPro GPS数据（手动菜单调用）"""
        stream_info = self.get_gpmd_stream_index(self.video_path)
        if stream_info is not None:
            if messagebox.askyesno("GoPro GPS", "检测到视频包含GoPro GPS数据，是否导入？\n(这将覆盖当前的GPX数据)"):
                self.import_gopro_gps()
        else:
            messagebox.showinfo("提示", "未检测到GoPro GPS数据流")

    def _calculate_speeds_from_points(self, points):
        """Recalculate speeds and distances for internal point structure"""
        if not points or len(points) < 2:
            return

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]
            
            # Calculate distance
            dist = self._haversine_distance(p1['lat'], p1['lon'], p2['lat'], p2['lon'])
            
            # Calculate time diff
            t1 = p1['time']
            t2 = p2['time']
            dt = (t2 - t1).total_seconds()
            
            speed = 0.0
            if dt > 0:
                speed = (dist / 1000.0) / (dt / 3600.0) # km/h
                
            p1['speed'] = speed
            p1['dist_to_next'] = dist
            
        # Last point speed same as previous
        points[-1]['speed'] = points[-2]['speed']
        points[-1]['dist_to_next'] = 0.0

    def draw_track_thumbnail(self):
        """Draw track thumbnail for internal points"""
        if not hasattr(self, 'gpx_data') or not self.gpx_data:
            return
            
        # Extract lat/lon list
        points = []
        if isinstance(self.gpx_data, list):
            # Internal point structure
            points = [(p['lat'], p['lon']) for p in self.gpx_data]
        elif isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data:
            # Old segment structure
            seg_points = []
            for s in self.gpx_data['segments']:
                seg_points.append((s['lat_start'], s['lon_start']))
            if self.gpx_data['segments']:
                 last = self.gpx_data['segments'][-1]
                 seg_points.append((last['lat_end'], last['lon_end']))
            points = seg_points
            
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
        
    def get_gpmd_stream_index(self, video_path):
        """获取GoPro GPMD流索引
        :return: (index, start_time) or None
        """
        ffprobe_cmd = self._get_ffprobe_cmd()
        if not ffprobe_cmd:
            return None

        try:
            cmd = ffprobe_cmd + [
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                video_path
            ]
            
            startupinfo = None
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            output = subprocess.check_output(cmd, startupinfo=startupinfo).decode('utf-8')
            data = json.loads(output)
            
            for stream in data.get('streams', []):
                # 检查 codec_tag_string 或 handler_name
                is_gpmd = False
                if stream.get('codec_tag_string') == 'gpmd':
                    is_gpmd = True
                
                tags = stream.get('tags', {})
                if 'GoPro MET' in tags.get('handler_name', ''):
                    is_gpmd = True
                
                if is_gpmd:
                    index = stream['index']
                    start_time = None
                    if 'start_time' in stream:
                        try:
                            start_time = float(stream['start_time'])
                        except:
                            pass
                    return index, start_time
                    
        except Exception as e:
            print(f"查找GPMD流失败: {e}")
        return None

    def extract_gpmd_data(self, video_path, stream_index):
        """提取GPMD数据包"""
        ffprobe_cmd = self._get_ffprobe_cmd()
        if not ffprobe_cmd:
            return None

        try:
            # 使用 ffprobe 获取包含数据的包信息
            cmd = ffprobe_cmd + [
                '-v', 'quiet',
                '-select_streams', str(stream_index),
                '-show_packets',
                '-show_data',
                '-print_format', 'json',
                video_path
            ]
            
            startupinfo = None
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            # 注意：对于大文件，这可能会产生大量输出
            # 我们可能需要限制读取量，或者分块读取
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                print(f"提取GPMD数据失败: {stderr}")
                return None
                
            return json.loads(stdout.decode('utf-8'))
        except Exception as e:
            print(f"提取GPMD数据异常: {e}")
            return None

    def parse_gpmd_structure(self, packet_data):
        """解析GPMD数据结构"""
        if not packet_data or 'packets' not in packet_data:
            return []
            
        points = []
        
        for packet in packet_data['packets']:
            if 'data' not in packet or 'pts_time' not in packet:
                continue
                
            pts_time = float(packet['pts_time'])
            hex_data = packet['data'].strip()
            
            try:
                # 将 hex 转换为 bytes
                data = bytes.fromhex(hex_data)
            except:
                continue
                
            # 解析 payload
            offset = 0
            length = len(data)
            
            while offset < length - 8:
                try:
                    # 检查是否是 GPS5
                    if data[offset:offset+4] == b'GPS5':
                        count = struct.unpack('>H', data[offset+6:offset+8])[0]
                        data_start = offset + 8
                        
                        # GPS5 包含 5 个 int32: lat, lon, alt, speed2d, speed3d
                        num_samples = count // 5
                        if num_samples > 0:
                            fmt = f'>{count}i'
                            try:
                                values = struct.unpack(fmt, data[data_start:data_start + count*4])
                                
                                for i in range(num_samples):
                                    idx = i * 5
                                    lat = values[idx] / 10000000.0
                                    lon = values[idx+1] / 10000000.0
                                    alt = values[idx+2] / 1000.0
                                    # speed3d = values[idx+4] / 1000.0 
                                    
                                    # 计算该点的时间
                                    # 假设 18Hz 采样率 (GoPro 标准)
                                    point_time = pts_time + i * (1.0/18.0)
                                    
                                    points.append({
                                        'lat': lat,
                                        'lon': lon,
                                        'ele': alt,
                                        'speed': 0, # 将由 _calculate_speeds_from_points 计算
                                        'time': datetime.utcfromtimestamp(point_time),
                                        'time_offset': point_time
                                    })
                            except struct.error:
                                pass
                                
                        # 跳过已处理的块 (4字节对齐)
                        block_size = 8 + count * 4
                        if block_size % 4 != 0:
                            block_size += (4 - (block_size % 4))
                        offset += block_size
                    else:
                        offset += 4
                except Exception:
                    offset += 1
                    
        return points

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
                        'lat_start': points[i][0],
                        'lon_start': points[i][1],
                        'lat_end': points[i+1][0],
                        'lon_end': points[i+1][1]
                    })
            
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
                    time_obj = self._parse_time(time_str)
                
                hr = 0
                # 尝试获取心率
                extensions = trkpt.getElementsByTagName('extensions')
                if extensions:
                    # 尝试多种常见的命名空间
                    for tag in ['gpxtpx:hr', 'ns3:hr', 'hr']:
                        hr_nodes = extensions[0].getElementsByTagName(tag)
                        if hr_nodes and hr_nodes[0].firstChild:
                            hr = int(hr_nodes[0].firstChild.data)
                            break
                
                points.append((lat, lon, ele, time_obj, hr))
            
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

    def _parse_time(self, t_str):
        """解析时间字符串，统一返回 UTC datetime"""
        if not t_str: return None
        
        # 统一处理 Z 和 T
        t_str = t_str.replace('Z', '').replace('T', ' ')
        
        # 处理时区偏移 (简单去掉 +08:00 等，假定为 UTC)
        if '+' in t_str:
            t_str = t_str.split('+')[0]
        
        dt = None
        try:
            if '.' in t_str:
                main_part, frac_part = t_str.split('.')
                if len(frac_part) > 6:
                    frac_part = frac_part[:6]
                t_str = f"{main_part}.{frac_part}"
                dt = datetime.strptime(t_str, '%Y-%m-%d %H:%M:%S.%f')
            else:
                dt = datetime.strptime(t_str, '%Y-%m-%d %H:%M:%S')
        except:
            try:
                 dt = datetime.strptime(t_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
            except:
                return None
        
        # 假定解析出来的是 UTC 时间 (naive)
        return dt

    def _calculate_speeds(self, points):
        """计算两点之间的速度 (km/h)"""
        speeds = []
        # 简单计算每两点间的速度
        raw_speeds = []
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]
            
            dist = self._haversine_distance(p1[0], p1[1], p2[0], p2[1])
            time_diff = (p2[3] - p1[3]).total_seconds()
            
            if time_diff > 0:
                speed_kph = (dist / time_diff) * 3.6
            else:
                speed_kph = 0
            raw_speeds.append(speed_kph)
        
        # 平滑处理 (移动平均)
        if len(raw_speeds) > 0:
            window_size = 5
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
                # 转换为 UTC 时间 (Naive)
                # datetime.utcfromtimestamp is deprecated
                creation_time = datetime.fromtimestamp(mtime, timezone.utc).replace(tzinfo=None)
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
            
        # 1. 处理 GPMD 格式 (列表)
        if isinstance(self.gpx_data, list):
            points = self.gpx_data
            if not points:
                return 0.0, 0, None, None
                
            target_time = current_seconds + self.gpx_offset
            
            # 手动二分查找 (points sorted by time_offset)
            low = 0
            high = len(points) - 1
            
            # 边界检查
            if target_time < points[0]['time_offset']:
                p = points[0]
                return p['speed'], 0, p['lat'], p['lon']
            if target_time > points[-1]['time_offset']:
                p = points[-1]
                return p['speed'], 0, p['lat'], p['lon']
            
            while low <= high:
                mid = (low + high) // 2
                p = points[mid]
                p_time = p['time_offset']
                
                if p_time <= target_time:
                    if mid == len(points) - 1 or points[mid+1]['time_offset'] > target_time:
                        # Found the interval [mid, mid+1]
                        # Interpolate
                        p1 = points[mid]
                        if mid == len(points) - 1:
                            return p1['speed'], 0, p1['lat'], p1['lon']
                            
                        p2 = points[mid+1]
                        t1 = p1['time_offset']
                        t2 = p2['time_offset']
                        
                        ratio = 0.0
                        if t2 > t1:
                            ratio = (target_time - t1) / (t2 - t1)
                            
                        lat = p1['lat'] + (p2['lat'] - p1['lat']) * ratio
                        lon = p1['lon'] + (p2['lon'] - p1['lon']) * ratio
                        speed = p1['speed'] + (p2['speed'] - p1['speed']) * ratio
                        
                        return speed, 0, lat, lon
                    else:
                        low = mid + 1
                else:
                    high = mid - 1
            
            return 0.0, 0, None, None

        # 2. 处理 GPX 格式 (字典)
        elif isinstance(self.gpx_data, dict) and 'segments' in self.gpx_data:
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
                    # ffmpeg -i temp.mp4 -i source.mp4 -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 output.mp4
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
                # 没有ffmpeg，直接重命名
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
            vol = max(0, min(100, int(self.volume * 100)))
            spd = self.playback_speed
            if spd < 0.5:
                spd = 0.5
            elif spd > 2.0:
                spd = 2.0
            cmd = [
                'ffplay',
                '-nodisp',
                '-autoexit',
                '-loglevel', 'error',
                '-ss', f'{start_time:.3f}',
                '-i', self.video_path,
                '-volume', str(vol),
                '-af', f'atempo={spd}'
            ]
            self.audio_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self.audio_proc = None
    
    def stop_audio_playback(self):
        if self.audio_proc is not None:
            try:
                self.audio_proc.terminate()
            except Exception:
                pass
            self.audio_proc = None
    
    def _play_video_loop(self):
        """视频播放循环（在独立线程中运行）"""
        if self.cap is None:
            return
            
        fps = self.video_info.get('fps', 30.0)
        # 目标帧间隔
        target_interval = 1.0 / (fps * self.playback_speed)
        
        last_frame_time = time.time()
        
        # 记录上一帧的显示时间，用于计算延迟
        last_display_time = time.time()
        
        while self.playing and self.cap is not None:
            loop_start_time = time.time()
            
            # 1. 读取下一帧
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
            
            # 2. 只有当距离上次显示超过一定间隔时才更新UI（避免过度刷新）
            # 限制最高刷新率为 30fps，或者原视频帧率（取较小值）
            current_time = time.time()
            if current_time - last_display_time >= 0.033: # 约30fps
                # 复制帧数据传递给UI线程，避免冲突
                display_frame = frame.copy()
                self.root.after(0, self._display_frame, display_frame)
                
                # 更新进度条 (每0.5秒更新一次，避免频繁刷新)
                if current_time - last_display_time > 0.5:
                    current_video_time = self.current_frame_pos / fps if fps > 0 else 0
                    self.root.after(0, self.progress_var.set, current_video_time)
                    self.root.after(0, self._update_time_display, current_video_time)
                
                last_display_time = current_time
            
            # 3. 帧率控制
            process_time = time.time() - loop_start_time
            sleep_time = target_interval - process_time
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # 如果处理太慢，不需要sleep，甚至可能需要跳帧（这里暂不实现跳帧）
                pass
    
    def _display_frame(self, frame):
        """显示视频帧"""
        if frame is None:
            return
            
        # 叠加GPX信息
        if self.gpx_data:
            fps = self.video_info.get('fps', 30.0)
            current_seconds = self.current_frame_pos / fps if fps > 0 else 0
            self._draw_overlay_on_frame(frame, current_seconds)
            
        # 调整大小以适应画布
        canvas_width = self.video_canvas.winfo_width()
        canvas_height = self.video_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = 640
            canvas_height = 360
            
        # 保持宽高比
        img_h, img_w = frame.shape[:2]
        
        # 优化：如果图像尺寸与画布差异不大，不缩放
        if abs(img_w - canvas_width) > 10 or abs(img_h - canvas_height) > 10:
            ratio = min(canvas_width / img_w, canvas_height / img_h)
            new_w = int(img_w * ratio)
            new_h = int(img_h * ratio)
            resized_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            resized_frame = frame
        
        # 转换为 RGB
        rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
        
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
    
    def _draw_overlay_on_frame(self, frame, current_seconds):
        """在帧上绘制GPX叠加层"""
        if not self.gpx_data:
            return

        speed, hr, lat, lon = self.get_data_at_time(current_seconds)
        h, w = frame.shape[:2]
        
        # 1. 绘制轨迹缩略图 (右上角)
        if self.track_thumbnail is not None and self.track_transform is not None:
            thumb_h, thumb_w = self.track_thumbnail.shape[:2]
            
            # 确保缩略图不比视频大且位置合理
            if thumb_h < h and thumb_w < w:
                # 位置：右上角，边距20
                x_offset = w - thumb_w - 20
                y_offset = 20
                
                # 提取ROI
                roi = frame[y_offset:y_offset+thumb_h, x_offset:x_offset+thumb_w]
                
                # Alpha混合
                thumb_bgr = self.track_thumbnail[:, :, :3]
                thumb_alpha = self.track_thumbnail[:, :, 3] / 255.0
                thumb_alpha_3ch = cv2.merge([thumb_alpha, thumb_alpha, thumb_alpha])
                
                blended = (thumb_bgr * thumb_alpha_3ch + roi * (1.0 - thumb_alpha_3ch)).astype(np.uint8)
                frame[y_offset:y_offset+thumb_h, x_offset:x_offset+thumb_w] = blended
                
                # 绘制当前位置 (闪烁蓝点)
                if lat is not None and lon is not None:
                    # 解包变换参数 (支持旧版和新版)
                    if len(self.track_transform) == 5:
                        min_lat, min_lon, scale, t_h, padding = self.track_transform
                        lon_correction = 1.0
                    else:
                        min_lat, min_lon, scale, t_h, padding, lon_correction = self.track_transform
                    
                    # 计算坐标
                    pt_x = int(padding + (lon - min_lon) * lon_correction * scale)
                    pt_y = int(t_h - padding - (lat - min_lat) * scale)
                    
                    # 转换为屏幕坐标
                    screen_x = x_offset + pt_x
                    screen_y = y_offset + pt_y
                    
                    # 闪烁效果 (每秒闪烁约2次)
                    if int(time.time() * 4) % 2 == 0:
                        cv2.circle(frame, (screen_x, screen_y), 6, (255, 0, 0), -1) # 蓝色实心圆
                        cv2.circle(frame, (screen_x, screen_y), 8, (255, 255, 255), 1) # 白色描边

        # 2. 绘制速度表盘
        gauge_radius = 70
        gauge_center = (w - gauge_radius - 20, h - gauge_radius - 20)
        self.draw_speed_gauge(frame, speed, max_speed=60, center=gauge_center, radius=gauge_radius)
        
        # 3. 添加文字 (心率) - 如果有心率数据
        if hr > 0:
            text_hr = f"{hr} bpm"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.5, w / 1000.0)
            thickness = max(1, int(font_scale * 2))
            
            text_size_hr = cv2.getTextSize(text_hr, font, font_scale, thickness)[0]
            # 显示在表盘上方中心
            text_x_hr = gauge_center[0] - text_size_hr[0] // 2
            text_y_hr = gauge_center[1] - gauge_radius - 15
            
            cv2.putText(frame, text_hr, (text_x_hr, text_y_hr), font, font_scale, (0, 0, 0), thickness + 2)
            cv2.putText(frame, text_hr, (text_x_hr, text_y_hr), font, font_scale, (0, 0, 255), thickness)
            
            # 添加心形图标 (简单的圆)
            cv2.circle(frame, (text_x_hr - 15, text_y_hr - 5), 6, (0, 0, 255), -1)

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

    def _update_time_display(self, current_time):
        """更新时间显示（在主线程中调用）"""
        duration = self.video_info.get('duration', 0)
        self.time_label.config(text=f"{self.format_time(current_time)} / {self.format_time(duration)}")
        
        # 更新播放头位置
        self.draw_playhead(current_time)
    
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
            
            self.info_text.config(state=tk.NORMAL)
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(1.0, info_text)
            self.info_text.config(state=tk.DISABLED)
            
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
        
        for i, clip in enumerate(self.clips):
            start_time = clip['start_frame'] / fps
            end_time = clip['end_frame'] / fps
            
            x1 = start_time * self.timeline_scale
            x2 = end_time * self.timeline_scale
            
            # 绘制片段矩形
            # 使用不同颜色区分相邻片段
            color = "#4a90e2" if i % 2 == 0 else "#357abd"
            
            self.timeline_canvas.create_rectangle(x1, track_y, x2, track_y + track_height,
                                                 fill=color, outline="white", tags=("clip", clip['id']))
            
            # 绘制片段名称
            if x2 - x1 > 20: # 如果够宽才显示文字
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
    
    def update_timeline(self):
        """更新时间轴显示"""
        self.init_timeline()
    
    def generate_thumbnail(self):
        """生成视频缩略图"""
        if not HAS_CV2 or self.cap is None:
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
