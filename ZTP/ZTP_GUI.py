import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import sys
import threading
import queue
import os
import logging
import subprocess
import time
import socket
import psutil


# 导入现有的ZTP代码但确保设备映射为空
from ZTP_CONFIG_TEST import (
    DEFAULT_CONFIG as CONFIG_TEMPLATE, logger, ZTPManager, setup_logging,
    normalize_mac_address, get_app_path
)

# 创建自己的DEFAULT_CONFIG
DEFAULT_CONFIG = CONFIG_TEMPLATE.copy()
DEFAULT_CONFIG["device_mapping"] = {}  # 确保设备映射为空

# 创建一个自定义处理程序，将日志重定向到GUI
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)

class ZTPGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("网络设备零配置部署工具")
        self.geometry("900x640")
        self.config(padx=10, pady=10)
        
        # 创建增强样式
        style = ttk.Style()
        style.configure("BigFrame.TLabelframe", borderwidth=3, relief="ridge", padding=15)
        
        # 设置应用图标
        try:
            if getattr(sys, 'frozen', False):
                # 如果是打包后的EXE
                app_path = os.path.dirname(sys.executable)
                icon_path = os.path.join(app_path, 'ztp_icon.ico')
                if os.path.exists(icon_path):
                    self.iconbitmap(icon_path)
        except:
            pass
        
        # 初始化配置 - 确保设备映射为空
        self.config_data = DEFAULT_CONFIG.copy()
        
        # 初始化日志
        self.log_queue = queue.Queue()
        self.setup_logging()
        
        # 创建界面组件
        self.create_widgets()
        
        # 初始化核心变量
        self.ztp_manager = None
        self.services_running = False
        self.services_thread = None
        
        # 初始化TFTP目录
        self.initialize_tftp_dir()
        
        # 程序启动时自动检测IP
        self.after(500, self.detect_ip)
    
    def setup_logging(self):
        """设置日志系统"""
        # 全局日志设置
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # 添加队列处理器
        queue_handler = QueueHandler(self.log_queue)
        queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(queue_handler)
    
    def create_widgets(self):
        """创建GUI组件"""
        # 使用grid布局替代pack，这样可以更精确地控制各部分的位置和大小
        self.grid_rowconfigure(0, weight=1)  # 让主区域可以扩展
        self.grid_columnconfigure(0, weight=1)  # 让主区域可以水平扩展
        
        # 创建主框架 - 使用grid布局
        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # 配置main_frame的行列权重
        main_frame.grid_rowconfigure(0, weight=1)  # notebook行
        main_frame.grid_columnconfigure(0, weight=1)
        
        # 创建选项卡 - 使用grid布局
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        
        # 创建不同的选项卡页面
        self.create_network_tab()
        self.create_device_mapping_tab()
        self.create_log_tab()
        
        # 创建控制按钮区域 - 放在窗口底部，不是main_frame内
        button_frame = ttk.Frame(self)
        button_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        
        # 创建控制按钮
        self.create_control_buttons(button_frame)

    def create_network_tab(self):
        """创建网络配置选项卡"""
        network_tab = ttk.Frame(self.notebook)
        self.notebook.add(network_tab, text="网络配置")
        
        # 修改布局权重，使内容真正居中并能自适应大小
        network_tab.columnconfigure(0, weight=1)
        network_tab.columnconfigure(1, weight=0)
        network_tab.columnconfigure(2, weight=1)
        network_tab.rowconfigure(0, weight=1)  # 上方留白区域
        network_tab.rowconfigure(1, weight=0)  # 内容区域
        network_tab.rowconfigure(2, weight=1)  # 下方留白区域
        
        # 直接在network_tab上创建LabelFrame，简化结构
        settings_frame = ttk.LabelFrame(network_tab, text="网络服务配置")
        # 将组件放在第1行，使其垂直居中
        settings_frame.grid(row=1, column=1, padx=20, pady=20)
        
        # 设置行列的权重
        settings_frame.columnconfigure(0, weight=0)  # 标签列
        settings_frame.columnconfigure(1, weight=1)  # 输入框列 
        settings_frame.columnconfigure(2, weight=0)  # 按钮列
        
        # 为网格布局设置内边距
        row = 0
        
        # 服务器IP配置
        ttk.Label(settings_frame, text="服务器IP:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.server_ip_var = tk.StringVar(value=self.config_data["dhcp_server"]["server_ip"])
        ttk.Entry(settings_frame, textvariable=self.server_ip_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        
        # 自动检测IP按钮
        ttk.Button(settings_frame, text="自动检测IP", command=self.detect_ip).grid(row=row, column=2, sticky='w', padx=10, pady=5)
        row += 1
        
        # 网关配置
        ttk.Label(settings_frame, text="网关IP:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.gateway_var = tk.StringVar(value=self.config_data["dhcp_server"]["gateway"])
        ttk.Entry(settings_frame, textvariable=self.gateway_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # 子网掩码配置
        ttk.Label(settings_frame, text="子网掩码:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.subnet_var = tk.StringVar(value=self.config_data["dhcp_server"]["subnet_mask"])
        ttk.Entry(settings_frame, textvariable=self.subnet_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # IP池起始地址
        ttk.Label(settings_frame, text="IP池起始地址:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.start_ip_var = tk.StringVar(value=self.config_data["dhcp_server"]["start_ip"])
        ttk.Entry(settings_frame, textvariable=self.start_ip_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # IP池结束地址
        ttk.Label(settings_frame, text="IP池结束地址:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.end_ip_var = tk.StringVar(value=self.config_data["dhcp_server"]["end_ip"])
        ttk.Entry(settings_frame, textvariable=self.end_ip_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # TFTP服务器地址
        ttk.Label(settings_frame, text="TFTP服务器地址:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.tftp_server_var = tk.StringVar(value=self.config_data["dhcp_server"]["options"]["66"])
        ttk.Entry(settings_frame, textvariable=self.tftp_server_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # TFTP根目录
        ttk.Label(settings_frame, text="TFTP根目录:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.tftp_root_var = tk.StringVar(value=self.config_data["tftp_server"]["root_dir"])
        self.tftp_root_entry = ttk.Entry(settings_frame, textvariable=self.tftp_root_var, width=20)  # 改为20
        self.tftp_root_entry.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Button(settings_frame, text="浏览", command=self.select_tftp_dir).grid(row=row, column=2, sticky='w', padx=10, pady=5)
        row += 1

        # 默认配置文件
        ttk.Label(settings_frame, text="默认配置文件:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.default_config_var = tk.StringVar(value=self.config_data["dhcp_server"]["options"]["67"])
        ttk.Entry(settings_frame, textvariable=self.default_config_var, width=20).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # 分隔线
        ttk.Separator(settings_frame, orient='horizontal').grid(row=row, column=0, columnspan=3, sticky='ew', padx=10, pady=10)
        row += 1
        
        # 防火墙配置
        ttk.Label(settings_frame, text="防火墙设置:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.firewall_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(settings_frame, text="添加防火墙规则", variable=self.firewall_var).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # 保存配置按钮居中
        save_frame = ttk.Frame(settings_frame)
        save_frame.grid(row=row, column=0, columnspan=3, pady=15)
        ttk.Button(save_frame, text="应用网络配置", command=self.save_network_config, width=20).pack()
        
        # 添加窗口大小变化的响应函数
        def on_resize(event):
            window_width = event.width
            window_height = event.height
            
            # 计算内容区域宽度 - 根据窗口宽度等比例计算
            content_width = max(600, min(1200, int(window_width * 0.75)))
            
            # 计算内容区域高度 - 适配窗口高度，但保持上下边距
            content_height = max(400, min(800, int(window_height * 0.7)))
            
            # 更新settings_frame宽度和高度
            settings_frame.config(width=content_width, height=content_height)
            
            # 为所有输入框使用相同的宽度计算公式
            entry_width = max(20, int(content_width / 30))
            
            # 动态调整所有输入框的宽度，包括TFTP根目录输入框
            for widget in settings_frame.winfo_children():
                if isinstance(widget, ttk.Entry):
                    widget.config(width=entry_width)
        
        # 绑定窗口大小变化事件
        network_tab.bind("<Configure>", on_resize)
        
        # 初始调用一次以设置正确的初始大小
        network_tab.update_idletasks()
        initial_event = type('Event', (), {'width': network_tab.winfo_width(), 'height': network_tab.winfo_height()})()
        on_resize(initial_event)

    def create_device_mapping_tab(self):
        """创建设备映射选项卡"""
        device_tab = ttk.Frame(self.notebook)
        self.notebook.add(device_tab, text="多设备场景")
        
        # 修改网格布局权重，使内容真正居中
        device_tab.columnconfigure(0, weight=1)
        device_tab.columnconfigure(1, weight=0)
        device_tab.columnconfigure(2, weight=1)
        device_tab.rowconfigure(0, weight=1)
        
        # 直接在device_tab上创建LabelFrame，简化结构
        settings_frame = ttk.LabelFrame(device_tab, text="多设备配置")
        settings_frame.grid(row=0, column=1, sticky="n", padx=20, pady=20)
        
        # 移除外边框
        settings_frame.configure(borderwidth=0)
        
        # 创建内部滚动视图 - 移除所有可能的边框
        canvas_frame = ttk.Frame(settings_frame)
        canvas_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 修改：确保Canvas无边框和高亮
        main_canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)
        
        # 设置scrollable_frame的大小跟踪
        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        # 创建窗口并将scrollable_frame放入其中
        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        # 放置canvas和scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 响应鼠标滚轮
        def _on_mousewheel(event):
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        # 仅当鼠标在canvas上时才绑定滚轮事件
        def _bind_mousewheel(event):
            main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        def _unbind_mousewheel(event):
            main_canvas.unbind_all("<MouseWheel>")
        
        main_canvas.bind("<Enter>", _bind_mousewheel)
        main_canvas.bind("<Leave>", _unbind_mousewheel)
        scrollable_frame.bind("<Enter>", _bind_mousewheel)  # 确保内容区域也能响应滚轮
        
        # 创建扫描设备部分
        scan_frame = ttk.LabelFrame(scrollable_frame, text="扫描网络中的设备")
        scan_frame.pack(fill="x", padx=10, pady=10)
        scan_frame.configure(borderwidth=3, relief="ridge")
        
        # 创建扫描按钮框架
        scan_buttons_frame = ttk.Frame(scan_frame)
        scan_buttons_frame.pack(fill="x", padx=10, pady=5)
        
        # 创建扫描按钮
        self.scan_button = tk.Button(scan_buttons_frame, text="扫描网络中的设备", 
                                    command=self.scan_devices, width=20,
                                    bg="#0078d7", fg="white",
                                    activebackground="#005fa9", activeforeground="white",
                                    relief="raised", font=('Arial', 10, 'bold'), borderwidth=2)
        self.scan_button.grid(row=0, column=0, padx=5, pady=5)
        
        # 创建停止扫描按钮
        self.stop_scan_button = tk.Button(scan_buttons_frame, text="停止扫描", 
                                    command=self.stop_scan, width=20,
                                    bg="#808080", fg="white",  # 灰色背景，白色文字
                                    activebackground="#707070", activeforeground="white",
                                    disabledforeground="white",  # 禁用状态下文字仍为白色
                                    cursor="arrow",  # 正常状态鼠标样式
                                    relief="raised", font=('Arial', 10, 'bold'), borderwidth=2,
                                    state="disabled")  # 初始状态为禁用

        # 将停止扫描按钮添加到布局
        self.stop_scan_button.grid(row=0, column=1, padx=5, pady=5)

        # 初始设置为禁止点击样式
        self.stop_scan_button.config(cursor="no")  # 禁止点击样式
        
        # 添加设备列表
        list_frame = ttk.Frame(scan_frame)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 创建树状视图显示设备
        columns = ('mac', 'client_id', 'ip')
        self.device_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=6)
        
        # 定义列
        self.device_tree.heading('mac', text='MAC地址')
        self.device_tree.heading('client_id', text='DHCP Client ID')
        self.device_tree.heading('ip', text='IP地址')
        
        # 设置列宽度 - 后面会动态调整
        self.device_tree.column('mac', width=150)
        self.device_tree.column('client_id', width=200)
        self.device_tree.column('ip', width=120)
        
        # 添加滚动条
        tree_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscroll=tree_scrollbar.set)
        
        # 放置树状视图和滚动条
        self.device_tree.pack(side="left", fill="both", expand=True)
        tree_scrollbar.pack(side="right", fill="y")
        
        # 添加使用选中设备按钮
        use_button = ttk.Button(scan_frame, text="添加到映射配置中", 
                               command=self.use_selected_device, width=20)
        use_button.pack(pady=5)
        
        # 初始化扫描状态变量
        self.scanning = False
        self.scan_thread = None
        
        # 然后再创建添加映射部分
        mapping_frame = ttk.LabelFrame(scrollable_frame, text="添加多设备配置文件映射")
        mapping_frame.pack(fill="x", padx=10, pady=10)
        mapping_frame.configure(borderwidth=3, relief="ridge")
        
        # 使用Frame将内部控件居中
        inner_frame = ttk.Frame(mapping_frame)
        inner_frame.pack(pady=10, padx=10)
        
        row = 0
        # 映射类型
        ttk.Label(inner_frame, text="映射类型:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.mapping_type = tk.StringVar(value="client_id")
        ttk.Radiobutton(inner_frame, text="设备DHCP标识符(Client ID)", 
                       variable=self.mapping_type, value="client_id", 
                       command=self.update_identifier_label).grid(row=row, column=1, sticky='w')
        row += 1
        
        ttk.Radiobutton(inner_frame, text="设备MAC地址", 
                       variable=self.mapping_type, value="mac", 
                       command=self.update_identifier_label).grid(row=row, column=1, sticky='w')
        row += 1
        
        # 标识符输入 - 使用动态标签
        self.identifier_label = ttk.Label(inner_frame, text="设备DHCP Client ID值:")
        self.identifier_label.grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.identifier_var = tk.StringVar()
        ttk.Entry(inner_frame, textvariable=self.identifier_var, width=30).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # 配置文件输入
        ttk.Label(inner_frame, text="配置文件名:").grid(row=row, column=0, sticky='e', padx=10, pady=5)
        self.config_file_var = tk.StringVar()
        ttk.Entry(inner_frame, textvariable=self.config_file_var, width=30).grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # 添加映射按钮
        ttk.Button(inner_frame, text="添加映射", command=self.add_mapping).grid(row=row, column=0, columnspan=2, pady=10)
        row += 1
        
        # 显示已添加的映射
        mapping_list_frame = ttk.LabelFrame(scrollable_frame, text="已添加的设备映射")
        mapping_list_frame.pack(fill="x", padx=10, pady=10)
        mapping_list_frame.configure(borderwidth=3, relief="ridge")

        # 添加提示标签
        ttk.Label(mapping_list_frame, text="(设备将使用指定的配置文件启动，如果指定的配置文件不存在，则会使用默认配置文件)", 
                 foreground='grey').pack(side='top', padx=10, pady=5)

        # 使用Treeview显示映射
        tree_frame = ttk.Frame(mapping_list_frame)
        tree_frame.pack(fill='both', expand=True, pady=5, padx=10)

        columns = ('identifier', 'config_file')
        self.mapping_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=8)
        self.mapping_tree.heading('identifier', text='设备标识符')
        self.mapping_tree.heading('config_file', text='配置文件')
        self.mapping_tree.column('identifier', width=300)
        self.mapping_tree.column('config_file', width=200)

        # 添加滚动条
        mapping_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.mapping_tree.yview)
        self.mapping_tree.configure(yscrollcommand=mapping_scrollbar.set)

        # 放置树状视图和滚动条
        self.mapping_tree.pack(side="left", fill="both", expand=True)
        mapping_scrollbar.pack(side="right", fill="y")

        # 删除映射按钮
        delete_button = ttk.Button(mapping_list_frame, text="删除选中的映射", 
                                  command=self.delete_mapping, width=20)
        delete_button.pack(pady=10)
        
        # 初始化标签
        self.update_identifier_label()
        
        # 改进的窗口调整函数，实现等比例放大
        def on_resize(event):
            window_width = event.width
            window_height = event.height
            
            # 计算内容区域宽度 - 根据窗口宽度等比例计算
            # 窗口宽度的75%，但最小保持600，最大不超过1200
            content_width = max(600, min(1200, int(window_width * 0.75)))
            
            # 计算内容区域高度 - 根据窗口高度等比例计算
            content_height = int(window_height * 0.85)  # 窗口高度的85%
            
            # 设置主画布尺寸
            main_canvas.config(width=content_width, height=content_height)
            
            # 更新settings_frame宽度以适应内容
            settings_frame.config(width=content_width + 40)  # 加上内边距
            
            # 调整树视图高度
            device_height = max(int(window_height/100), 6)  # 最小6行
            mapping_height = max(int(window_height/100), 8)  # 最小8行
            
            # 调整树视图列宽度
            tree_width = content_width - 80  # 考虑边距和滚动条
            
            try:
                # 设置树视图高度
                self.device_tree.config(height=device_height)
                self.mapping_tree.config(height=mapping_height)
                
                # 设置设备树视图列宽
                self.device_tree.column('mac', width=int(tree_width*0.3))
                self.device_tree.column('client_id', width=int(tree_width*0.45))
                self.device_tree.column('ip', width=int(tree_width*0.25))
                
                # 设置映射树视图列宽
                self.mapping_tree.column('identifier', width=int(tree_width*0.6))
                self.mapping_tree.column('config_file', width=int(tree_width*0.4))
            except Exception as e:
                self.log_message(f"DEBUG - 调整大小时出错: {str(e)}")
            
            # 强制更新滚动区域
            scrollable_frame.update_idletasks()
            main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        
        # 绑定窗口大小变化事件
        device_tab.bind("<Configure>", on_resize)
        
        # 初始调用一次以设置正确的初始大小
        device_tab.update_idletasks()
        # 创建模拟事件对象进行初始调用
        initial_event = type('Event', (), {'width': device_tab.winfo_width(), 'height': device_tab.winfo_height()})()
        on_resize(initial_event)

    def create_log_tab(self):
        """创建日志选项卡"""
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text="服务日志")
        
        # 创建日志显示区域
        log_frame = ttk.LabelFrame(log_tab, text="服务运行日志")
        log_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # 添加日志文本框
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20)
        self.log_text.pack(fill='both', expand=True, padx=5, pady=5)
        self.log_text.config(state='disabled')
        
        # 创建按钮容器框架以实现居中效果
        button_frame = ttk.Frame(log_tab)
        button_frame.pack(fill='x', pady=5)
        
        # 清除日志按钮 - 居中放置
        clear_button = ttk.Button(button_frame, text="清除日志", command=self.clear_log, width=15)
        clear_button.pack(side='top', pady=5, anchor='center')
        
        # 启动日志处理线程
        self.after(100, self.poll_log_queue)

    # 替换控制按钮部分的代码：
    def create_control_buttons(self, parent):
        """创建底部控制按钮"""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill='x', pady=10)
        
        # 将按钮框架分为三列
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=2)
        button_frame.columnconfigure(2, weight=1)
        
        # 状态标签 - 左侧
        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(button_frame, textvariable=self.status_var, font=('', 10, 'bold'))
        status_label.grid(row=0, column=0, sticky='w', padx=10)
        
        # 启动/停止服务按钮 - 居中放置
        button_center = ttk.Frame(button_frame)
        button_center.grid(row=0, column=1)
        
        # 使用tk.Button替代ttk.Button获得更好的颜色控制
        self.start_button = tk.Button(button_center, text="启动ZTP服务", 
                                  command=self.toggle_services,
                                  width=20,
                                  bg="#2e7d32",  # 深绿色背景
                                  fg="white",    # 白色文字
                                  activebackground="#43a047",  # 鼠标悬停时的颜色
                                  activeforeground="white",
                                  relief="raised",
                                  font=('Arial', 10, 'bold'),
                                  borderwidth=2)
        self.start_button.pack(pady=5)
        
        # 退出按钮 - 右下角
        exit_button = tk.Button(button_frame, text="退出程序", command=self.confirm_exit,
                               bg="#f0f0f0",  # 系统默认背景色
                               fg="#505050",   # 深灰色文字
                               activebackground="#e0e0e0", # 鼠标悬停时稍微暗一点
                               activeforeground="#505050",
                               relief="ridge",  # 更平滑的边框样式
                               font=('Arial', 10),  # 移除bold使其不那么显眼
                               borderwidth=1)   # 更小的边框
        exit_button.grid(row=0, column=2, sticky='e', padx=10)

    # 功能方法
    def detect_ip(self):
        """自动检测本机IP地址"""
        import socket
        try:
            # 基本方法获取IP
            hostname = socket.gethostname()
            host_info = socket.gethostbyname_ex(hostname)
            for ip in host_info[2]:
                if not ip.startswith("127."):
                    selected_ip = ip
                    self.server_ip_var.set(selected_ip)
                    self.gateway_var.set(selected_ip)
                    self.tftp_server_var.set(selected_ip)
                    
                    # 修改IP池范围，确保与所选接口在同一网段
                    ip_parts = selected_ip.split('.')
                    network_prefix = '.'.join(ip_parts[0:3])
                    self.start_ip_var.set(f"{network_prefix}.100")
                    self.end_ip_var.set(f"{network_prefix}.200")
                    
                    messagebox.showinfo("IP检测", f"已自动选择IP地址: {selected_ip}")
                    return
            
            # 如果没有找到非回环IP，使用回环地址
            selected_ip = socket.gethostbyname(socket.gethostname())
            self.server_ip_var.set(selected_ip)
            self.gateway_var.set(selected_ip)
            self.tftp_server_var.set(selected_ip)
            messagebox.showinfo("IP检测", f"只找到回环IP: {selected_ip}")
        except Exception as e:
            messagebox.showerror("IP检测失败", f"无法自动检测IP: {str(e)}")

    def select_tftp_dir(self):
        """选择TFTP根目录"""
        directory = filedialog.askdirectory(title="选择TFTP根目录")
        if directory:
            self.tftp_root_var.set(directory)

    def save_network_config(self):
        """保存网络配置"""
        # 更新配置
        try:
            self.config_data["dhcp_server"]["server_ip"] = self.server_ip_var.get()
            self.config_data["dhcp_server"]["gateway"] = self.gateway_var.get()
            self.config_data["dhcp_server"]["subnet_mask"] = self.subnet_var.get()
            self.config_data["dhcp_server"]["start_ip"] = self.start_ip_var.get()
            self.config_data["dhcp_server"]["end_ip"] = self.end_ip_var.get()
            self.config_data["dhcp_server"]["options"]["66"] = self.tftp_server_var.get()
            self.config_data["dhcp_server"]["options"]["67"] = self.default_config_var.get()
            self.config_data["tftp_server"]["server_ip"] = self.server_ip_var.get()
            self.config_data["tftp_server"]["root_dir"] = self.tftp_root_var.get()
            
            # 检查TFTP根目录是否存在，如果不存在则创建
            if not os.path.exists(self.tftp_root_var.get()):
                os.makedirs(self.tftp_root_var.get(), exist_ok=True)
                messagebox.showinfo("创建目录", f"已创建TFTP根目录: {self.tftp_root_var.get()}")
                
            messagebox.showinfo("配置已保存", "网络配置已应用")
            self.log_message(f"INFO - 网络配置已更新: 服务器IP={self.server_ip_var.get()}, 网关={self.gateway_var.get()}")
        except Exception as e:
            messagebox.showerror("保存失败", f"配置应用失败: {str(e)}")

    def add_mapping(self):
        """添加设备映射"""
        identifier = self.identifier_var.get().strip()
        config_file = self.config_file_var.get().strip()
        
        if not identifier or not config_file:
            messagebox.showerror("输入错误", "标识符和配置文件名都不能为空")
            return
            
        # 根据映射类型格式化标识符
        if self.mapping_type.get() == "client_id":
            # 智能判断是否需要添加类型字节前缀
            if self._should_add_prefix(identifier):
                if not identifier.startswith("00"):
                    identifier_original = identifier
                    identifier = "00" + identifier
                    self.log_message(f"INFO - 已自动为Client ID添加00前缀: {identifier_original} -> {identifier}")
            
            if not identifier.startswith("client_id:"):
                final_id = f"client_id:{identifier}"
            else:
                final_id = identifier
        else:  # MAC地址处理保持不变
            normalized_mac = normalize_mac_address(identifier)
            if not normalized_mac:
                messagebox.showerror("输入错误", "MAC地址格式无效，请使用正确的MAC地址格式")
                return
            final_id = normalized_mac
        
        # 添加到配置
        self.config_data["device_mapping"][final_id] = {"config_file": config_file}
        
        # 更新树形视图
        self.update_mapping_tree()
        
        # 清空输入框
        self.identifier_var.set("")
        self.config_file_var.set("")
        
        # 记录日志
        id_type = "客户端标识符" if self.mapping_type.get() == "client_id" else "MAC地址"
        self.log_message(f"INFO - 添加了{id_type}映射: {final_id} -> {config_file}")

    def delete_mapping(self):
        """删除选中的设备映射"""
        selected = self.mapping_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的映射")
            return
        
        # 获取选中项
        for item in selected:
            values = self.mapping_tree.item(item, 'values')
            identifier = values[0]
            
            # 从配置中删除
            if identifier in self.config_data["device_mapping"]:
                del self.config_data["device_mapping"][identifier]
                self.log_message(f"INFO - 删除了设备映射: {identifier}")
        
        # 更新树形视图
        self.update_mapping_tree()

    def update_mapping_tree(self):
        """更新映射树"""
        # 清除现有项
        for i in self.mapping_tree.get_children():
            self.mapping_tree.delete(i)
        
        # 添加映射
        for identifier, info in self.config_data["device_mapping"].items():
            self.mapping_tree.insert('', 'end', values=(identifier, info["config_file"]))

    def toggle_services(self):
        """启动或停止服务"""
        if not self.services_running:
            self.start_services()
        else:
            self.stop_services()

    def start_services(self):
        """启动ZTP服务"""
        try:
            # 如果正在进行设备扫描，先停止扫描
            if self.scanning:
                self.log_message("INFO - 启动ZTP服务前自动停止设备扫描")
                self.stop_scan()
                # 添加短暂延迟确保扫描完全停止
                time.sleep(1.0)

                # 再次确保端口已释放
                self.force_release_port(67)
                self.force_release_port(69)
            
            # 检查端口是否可用
            import socket
            ports_to_check = [69, 67]  # TFTP和DHCP端口
            unavailable_ports = []
            
            for port in ports_to_check:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.bind(('0.0.0.0', port))
                    s.close()
                except:
                    unavailable_ports.append(port)
            
            if unavailable_ports:
                error_msg = f"端口 {', '.join(map(str, unavailable_ports))} 已被占用，无法启动服务"
                messagebox.showerror("端口被占用", error_msg)
                self.log_message(f"ERROR - {error_msg}")
                return
                
            # 更新防火墙规则
            if self.firewall_var.get():
                self.update_firewall_rules()
            
            # 创建服务线程
            self.services_thread = threading.Thread(target=self.run_services)
            self.services_thread.daemon = True
            self.services_thread.start()
            
            # 更新UI状态
            self.services_running = True
            self.start_button.config(text="停止ZTP服务")
            self.status_var.set("服务运行中")
            
            # 禁用配置选项卡
            self.notebook.tab(0, state='disabled')
            self.notebook.tab(1, state='disabled')
            
            # 切换到日志选项卡
            self.notebook.select(2)
            
            # 记录日志
            self.log_message("INFO - ZTP服务启动成功")
            
        except Exception as e:
            messagebox.showerror("启动失败", f"启动ZTP服务失败: {str(e)}")
            self.log_message(f"ERROR - 启动ZTP服务失败: {str(e)}")

    def stop_services(self):
        """停止ZTP服务"""
        try:
            # 标记为停止
            self.services_running = False
            
            # 实际停止服务器并释放资源
            if self.ztp_manager:
                # 调用ZTP管理器的停止方法
                if hasattr(self.ztp_manager, 'stop_services'):
                    self.ztp_manager.stop_services()
                    self.log_message("INFO - 已请求ZTP服务停止")
                
                # 等待更长时间让资源释放
                time.sleep(0.5)  # 增加等待时间
                
                # 检查并强制释放端口
                for port in [69, 67]:  # TFTP和DHCP端口
                    try:
                        # 尝试绑定测试是否已释放
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.settimeout(0.1)
                        s.bind(('0.0.0.0', port))
                        s.close()
                        self.log_message(f"INFO - 端口 {port} 已成功释放")
                    except:
                        # 端口仍被占用，尝试强制释放
                        self.log_message(f"WARNING - 端口 {port} 仍被占用，尝试强制释放")
                        if self.force_release_port(port):
                            self.log_message(f"INFO - 已强制释放端口 {port}")
                            time.sleep(0.5)  # 额外等待时间确保释放完成
                
                # 终止可能的子进程
                self.terminate_all_child_processes()
                
                # 确保资源被清理
                self.ztp_manager = None
            
            # 更新UI状态
            self.start_button.config(text="启动ZTP服务")
            self.status_var.set("服务已停止")
            
            # 启用配置选项卡
            self.notebook.tab(0, state='normal')
            self.notebook.tab(1, state='normal')
            
            # 记录日志
            self.log_message("INFO - ZTP服务已停止")
            
        except Exception as e:
            messagebox.showerror("停止失败", f"停止ZTP服务失败: {str(e)}")
            self.log_message(f"ERROR - 停止服务失败: {str(e)}")

    def run_services(self):
        """在线程中运行ZTP服务"""
        try:
            # 获取当前接口IP
            server_ip = self.server_ip_var.get()
            
            # 确保DHCP配置使用相同网段
            ip_parts = server_ip.split('.')
            network_prefix = '.'.join(ip_parts[0:3])
            
            # 强制更新网段相关配置
            self.config_data["dhcp_server"]["server_ip"] = server_ip
            self.config_data["dhcp_server"]["gateway"] = server_ip
            self.config_data["dhcp_server"]["start_ip"] = f"{network_prefix}.100"
            self.config_data["dhcp_server"]["end_ip"] = f"{network_prefix}.200"
            self.config_data["dhcp_server"]["options"]["66"] = server_ip
            
            # 确保TFTP根目录使用绝对路径
            tftp_root = self.tftp_root_var.get()
            if not os.path.isabs(tftp_root):
                # 如果是相对路径，转换为基于当前EXE所在目录的绝对路径
                if getattr(sys, 'frozen', False):
                    base_path = os.path.dirname(sys.executable)
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))
                tftp_root = os.path.join(base_path, tftp_root)
                self.config_data["tftp_server"]["root_dir"] = tftp_root
                    
            # 确保目录存在
            os.makedirs(tftp_root, exist_ok=True)
            self.log_message(f"INFO - 使用TFTP根目录: {tftp_root}")
            
            # 设置TFTP服务器绑定到特定IP而非0.0.0.0
            self.config_data["tftp_server"]["server_ip"] = server_ip  # 使用具体IP
            
            # 检查引导文件是否存在
            bootfile = self.config_data["dhcp_server"]["options"]["67"]
            bootfile_path = os.path.join(tftp_root, bootfile)
            if not os.path.exists(bootfile_path):
                self.log_message(f"WARNING - 引导文件 {bootfile} 不存在于TFTP根目录")
                    
            # 创建ZTP管理器
            self.ztp_manager = ZTPManager(self.config_data)
            
            # 启动服务
            self.ztp_manager.start_services()
            
        except Exception as e:
            self.log_message(f"ERROR - 服务运行时出错: {str(e)}")
            # 如果出错，才自动停止服务
            if self.services_running:
                self.after(0, self.stop_services)

    def update_firewall_rules(self):
        """添加防火墙规则"""
        try:
            import subprocess
            # 创建无窗口进程
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
            # 使用startupinfo参数隐藏命令行窗口
            subprocess.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule', 
                        'name=ZTP_DHCP', 'dir=in', 'action=allow', 
                        'protocol=UDP', 'localport=67,68,69'], 
                        check=False,
                        startupinfo=startupinfo,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
            self.log_message("INFO - 防火墙规则已添加")
        except Exception as e:
            self.log_message(f"WARNING - 添加防火墙规则失败: {str(e)}")

    def force_release_port(self, port):
        """强制释放端口"""
        self.log_message(f"INFO - 尝试强制释放端口 {port}...")
        
        # Windows系统使用taskkill强制释放
        try:
            # 查找占用端口的进程
            find_cmd = f'netstat -ano | findstr :{port}'
            try:
                result = subprocess.check_output(find_cmd, shell=True).decode()
                # 命令成功执行，说明找到了占用端口的进程
                
                # 分析输出找到PID
                import re
                pids = set()
                for line in result.split('\n'):
                    match = re.search(r'\s+(\d+)$', line.strip())
                    if match:
                        pid = match.group(1)
                        # 不要杀死自身进程
                        if int(pid) != os.getpid():
                            pids.add(pid)
                
                # 杀死占用进程
                if pids:
                    for pid in pids:
                        self.log_message(f"INFO - 强制终止进程 PID: {pid}...")
                        subprocess.run(f'taskkill /F /PID {pid}', shell=True, 
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                else:
                    self.log_message(f"INFO - 未找到其他进程占用端口 {port}")
                    return True
                    
            except subprocess.CalledProcessError:
                # 命令返回非零退出码，表示没有找到占用端口的进程
                # 这实际上是好消息，端口是空闲的
                self.log_message(f"INFO - 端口 {port} 未被占用")
                return True
                
        except Exception as e:
            self.log_message(f"ERROR - 检查端口 {port} 状态时出错: {str(e)}")
            return False

    def terminate_all_child_processes(self):
        """终止所有子进程"""
        
        try:
            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            
            for child in children:
                self.log_message(f"INFO - 终止子进程 PID: {child.pid}")
                child.terminate()
                
            # 等待子进程终止
            time.sleep(0.5)
            
            # 强制杀死仍然存在的进程
            for child in children:
                if child.is_running():
                    child.kill()
                    
            self.log_message(f"INFO - 已清理所有子进程")
        except Exception as e:
            self.log_message(f"WARNING - 清理子进程时出错: {str(e)}")

    def poll_log_queue(self):
        """从日志队列中读取并显示日志"""
        try:
            while True:
                record = self.log_queue.get_nowait()
                self.log_message(f"{record.levelname} - {record.getMessage()}")
        except queue.Empty:
            # 队列为空时继续
            pass
        finally:
            # 100毫秒后再次检查
            self.after(100, self.poll_log_queue)

    def log_message(self, message):
        """将消息添加到日志文本框"""
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        formatted_message = f"{current_time} - {message}"
        
        self.log_text.config(state='normal')
        self.log_text.insert('end', formatted_message + '\n')
        self.log_text.see('end')  # 自动滚动到底部
        self.log_text.config(state='disabled')

    def clear_log(self):
        """清除日志文本框"""
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, 'end')
        self.log_text.config(state='disabled')

    def confirm_exit(self):
        """确认退出程序"""
        if self.services_running:
            if messagebox.askyesno("确认退出", "ZTP服务仍在运行，确定要退出吗？"):
                self.stop_services()
                self.destroy()
        else:
            self.destroy()

    def update_identifier_label(self):
        """根据选择的映射类型更新标识符标签"""
        mapping_type = self.mapping_type.get()
        if mapping_type == "client_id":
            self.identifier_label.config(text="设备DHCP Client ID值:")
        else:  # mac
            self.identifier_label.config(text="设备系统MAC地址值:")
        
        # 确保刷新UI
        self.update()
        self.identifier_var.set("")  # 清空输入框

    def initialize_tftp_dir(self):
        """初始化TFTP目录"""
        # 获取EXE所在目录或当前脚本目录
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        # 创建默认TFTP目录
        default_tftp_dir = os.path.join(base_path, "tftpboot")
        os.makedirs(default_tftp_dir, exist_ok=True)
        
        # 设置为默认TFTP根目录
        self.tftp_root_var.set(default_tftp_dir)
        self.config_data["tftp_server"]["root_dir"] = default_tftp_dir
        
        # 创建一个示例配置文件（如果不存在）
        example_config = os.path.join(default_tftp_dir, "startup.cfg")
        if not os.path.exists(example_config):
            try:
                with open(example_config, 'w') as f:
                    f.write("""
#
interface MGE0/0/0
ip address dhcp-alloc
#
local-user admin class manage
password simple h3c.com
service-type ssh
authorization-attribute user-role network-admin
#
ssh server enable
#
line vty 0 63
authentication-mode scheme
user-role network-admin
idle-timeout 0 0
#
"""
                            )
                self.log_message(f"INFO - 已创建示例配置文件: {example_config}")
            except Exception as e:
                self.log_message(f"WARNING - 无法创建示例配置文件: {str(e)}")
        
        self.log_message(f"INFO - TFTP根目录已设置为: {default_tftp_dir}")

    def scan_devices(self):
        """扫描网络中的设备"""
        if self.services_running:
            messagebox.showwarning("警告", "请先停止ZTP服务再执行扫描")
            return
        
        # 清空现有设备列表
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        
        # 标记为扫描中
        self.scanning = True
        self.log_message("INFO - 开始扫描网络设备...")
        
        # 改变按钮文本但保持颜色一致
        self.scan_button.configure(text="扫描中...")
        
        # 启用停止扫描按钮，并改变鼠标样式
        self.stop_scan_button.configure(state="normal", cursor="arrow")  # 恢复普通鼠标样式
        
        # 创建线程执行扫描，避免阻塞GUI
        self.scan_thread = threading.Thread(target=self.run_device_scan)
        self.scan_thread.daemon = True
        self.scan_thread.start()

    def stop_scan(self):
        """停止设备扫描"""
        self.scanning = False
        self.log_message("INFO - 停止扫描设备")
        
        # 等待套接字释放
        time.sleep(1.0)
        
        # 确认端口是否已释放，如果没有则强制释放
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(('0.0.0.0', 67))
            test_sock.close()
            self.log_message("INFO - 端口67已成功释放")
        except:
            self.log_message("WARNING - 端口67仍被占用，尝试强制释放")
            self.force_release_port(67)
        
        # 恢复按钮文本和禁用停止按钮
        self.scan_button.configure(text="扫描网络中的设备")
        # 禁用停止按钮，并改变鼠标样式
        self.stop_scan_button.configure(state="disabled", cursor="no")  # 禁止点击样式

    def run_device_scan(self):
        """在线程中执行设备扫描"""
        try:
            # 创建UDP套接字
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # 绑定到67端口监听DHCP消息
            try:
                sock.bind(('0.0.0.0', 67))
            except OSError as e:
                # 如果绑定失败，尝试使用其他端口
                sock.bind(('0.0.0.0', 6767))
                self.log_message("WARNING - 无法绑定到标准DHCP端口，使用替代端口6767")
            
            sock.settimeout(1.0)  # 设置超时，使循环可以定期检查停止标志
            
            self.log_message("INFO - 监听DHCP请求中，请打开或重启设备触发DHCP请求...")
            
            # 存储已发现的设备
            discovered_devices = {}
            
            # 扫描循环 - 只使用self.scanning标志控制
            while self.scanning:
                try:
                    data, addr = sock.recvfrom(4096)
                    
                    # 解析DHCP消息
                    msg_type, client_mac, client_id, requested_ip = self.parse_dhcp_packet(data)
                    
                    if msg_type and client_mac:
                        # 格式化MAC地址
                        formatted_mac = ':'.join([f'{b:02x}' for b in client_mac])
                        
                        # 避免重复添加
                        if formatted_mac not in discovered_devices:
                            discovered_devices[formatted_mac] = {
                                'mac': formatted_mac,
                                'client_id': client_id or "未检测到",
                                'ip': requested_ip or "未分配"
                            }
                            
                            # 在GUI线程中更新树状视图
                            self.after(0, lambda mac=formatted_mac, dev=discovered_devices[formatted_mac]: 
                                self.device_tree.insert('', 'end', values=(dev['mac'], dev['client_id'], dev['ip'])))
                            
                            self.log_message(f"INFO - 发现设备: MAC={formatted_mac}, Client ID={client_id or '未检测到'}")
                
                except socket.timeout:
                    # 超时继续循环
                    continue
                except Exception as e:
                    self.log_message(f"ERROR - 扫描设备时出错: {str(e)}")
            
        except Exception as e:
            self.log_message(f"ERROR - 扫描过程出错: {str(e)}")
        
        finally:
            # 无论发生什么，确保套接字被关闭
            if sock:
                try:
                    sock.close()
                    self.log_message("INFO - 扫描套接字已关闭")
                except Exception as e:
                    self.log_message(f"ERROR - 关闭套接字时出错: {str(e)}")
            
            self.scanning = False
            # 恢复按钮样式并禁用停止按钮
            self.after(0, lambda: (
                self.scan_button.configure(text="扫描网络中的设备"),
                self.stop_scan_button.configure(state="disabled", cursor="no")
            ))

    def parse_dhcp_packet(self, data):
        """解析DHCP数据包，提取消息类型、客户端MAC、客户端ID和请求IP"""
        # DHCP报文中的固定偏移量
        if len(data) < 240:  # DHCP最小长度
            return None, None, None, None
        
        # 提取操作码 (1=请求, 2=响应)
        op = data[0]
        if op != 1:  # 只处理DHCP请求
            return None, None, None, None
        
        # 提取客户端MAC地址 (字节6-12)
        client_mac = data[28:34]
        
        # 提取客户端请求的IP (如果有)
        requested_ip = None
        if data[12:16] != b'\x00\x00\x00\x00':
            requested_ip = f"{data[12]}.{data[13]}.{data[14]}.{data[15]}"
        
        # 处理DHCP选项来获取更多信息
        options = data[240:]
        client_id = None
        msg_type = None
        
        i = 0
        while i < len(options):
            if options[i] == 255:  # 结束标记
                break
            if options[i] == 0:  # Padding
                i += 1
                continue
            
            opt_code = options[i]
            if i+1 >= len(options):
                break
                
            opt_len = options[i+1]
            if i+2+opt_len > len(options):
                break
                
            # 提取消息类型 (选项53)
            if opt_code == 53 and opt_len == 1:
                msg_type = options[i+2]
                
            # 提取客户端ID (选项61)
            elif opt_code == 61:
                # 检查是否有足够的字节
                if opt_len > 0:
                    # 如果第一个字节是类型字节(通常为0x00或0x01或0x02)
                    # 0x00: 未定义类型, 0x01: 以太网MAC, 0x02: IEEE 802地址
                    if options[i+2] in [0, 1, 2]:
                        # 跳过类型字节，只使用实际的客户端ID部分
                        client_id = ''.join([f'{b:02x}' for b in options[i+3:i+2+opt_len]])
                    else:
                        # 如果没有明确的类型字节，使用全部数据
                        client_id = ''.join([f'{b:02x}' for b in options[i+2:i+2+opt_len]])
                else:
                    client_id = None
            
            i += 2 + opt_len
        
        return msg_type, client_mac, client_id, requested_ip

    def use_selected_device(self):
        """使用选中的设备填充设备映射表单"""
        selected = self.device_tree.selection()
        if not selected:
            messagebox.showwarning("未选择设备", "请先选择一个设备")
            return
            
        # 获取选中设备的信息
        item = self.device_tree.item(selected[0])
        values = item['values']
        
        if len(values) >= 2:
            mac = values[0]
            client_id = values[1]
            
            # 根据当前选择的映射类型填充表单
            if self.mapping_type.get() == "client_id" and client_id != "未检测到":
                # 如果client_id带有前缀，去除前缀再填充
                if client_id.startswith("client_id:"):
                    self.identifier_var.set(client_id[10:])
                else:
                    self.identifier_var.set(client_id)
                self.log_message(f"INFO - 已自动填充Client ID: {client_id}")
            elif self.mapping_type.get() == "mac":
                self.identifier_var.set(mac)
                self.log_message(f"INFO - 已自动填充MAC地址: {mac}")
            else:
                # 如果映射类型与可用标识符不匹配，提示用户
                if client_id == "未检测到" and self.mapping_type.get() == "client_id":
                    messagebox.showinfo("提示", "所选设备没有Client ID，请选择使用MAC地址映射")
                self.log_message("INFO - 请检查映射类型与所选设备标识符是否匹配")

    def _should_add_prefix(self, client_id):
        """判断Client ID是否需要添加00前缀"""
        # 1. 如果是类似06b57cb30900这样的纯MAC地址形式，不需要添加前缀
        if len(client_id) == 12 and all(c in '0123456789abcdefABCDEF' for c in client_id):
            return False
            
        # 2. 如果是长字符串，可能是ASCII编码形式，需要添加前缀
        if len(client_id) > 12:
            # 尝试解码看是否是有意义的ASCII字符串
            try:
                # 检查是否有可能是ASCII编码的十六进制
                hex_bytes = bytes.fromhex(client_id)
                decoded = hex_bytes.decode('ascii', errors='ignore')
                # 如果包含常见的分隔符（点或横线），很可能是需要前缀的编码字符串
                if '.' in decoded or '-' in decoded:
                    return True
            except:
                pass
        
        # 3. 如果原始字符串已经以"00"开头，不需要重复添加
        if client_id.startswith("00"):
            return False
        
        # 4. 其他情况，默认添加前缀（更安全的做法）
        return True

if __name__ == "__main__":
    app = ZTPGUI()
    app.mainloop()