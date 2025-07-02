#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ZTP_CONFIG_TEST.py - H3C设备零配置开局(ZTP)工具

功能：
1. 启动 DHCP 服务器，分配 IP 地址并提供配置文件路径。
2. 启动 TFTP 服务器，提供配置文件下载。
3. 设备通过 DHCP 获取地址和配置文件路径信息。
"""

import os
import sys
import threading
import time
import logging
import socket
import struct
import ipaddress
import random
import socketserver
import os.path
import subprocess

# 全局配置
DEFAULT_CONFIG = {
    "dhcp_server": {
        "enabled": True,
        "server_ip": "192.168.55.1",
        "start_ip": "192.168.55.100",
        "end_ip": "192.168.55.200",
        "subnet_mask": "255.255.255.0",
        "gateway": "192.168.55.1",
        "dns_servers": ["8.8.8.8", "114.114.114.114"],
        "lease_time": 86400,  # 24小时
        "options": {
            "66": "192.168.55.1",  # TFTP服务器地址
            "67": "startup.cfg"   # 配置文件路径
        }
    },
    "tftp_server": {
        "enabled": True,
        "server_ip": "192.168.55.1",
        "root_dir": "./tftpboot"
    },
    "device_mapping": {
        # MAC地址映射
        "00:11:22:33:44:55": {
            "hostname": "SW-ACCESS-01",
            "config_file": "SW-ACCESS-01.cfg"
        },
        # Client ID映射（格式：client_id:xxxxxx）
        "client_id:abc123def456": {
            "hostname": "SW-ACCESS-02",
            "config_file": "SW-ACCESS-02.cfg"
        },
        # 序列号映射（格式：sn:xxxxxx）
        "sn:210235A1234": {
            "hostname": "SW-CORE-01",
            "config_file": "SW-CORE-01.cfg"
        }
    }
}

# 设置日志格式
def setup_logging(log_level="DEBUG"):
    """配置日志系统"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=getattr(logging, log_level), format=log_format)
    return logging.getLogger('ZTP')

logger = setup_logging()

# 简单TFTP服务器实现 - Windows兼容
class TFTPHandler(socketserver.BaseRequestHandler):
    """处理TFTP请求的处理器类"""
    
    def handle(self):
        """处理TFTP请求"""
        data, server_socket = self.request
        
        # TFTP操作码
        OP_RRQ = 1    # 读请求
        OP_WRQ = 2    # 写请求
        OP_DATA = 3   # 数据
        OP_ACK = 4    # 确认
        OP_ERROR = 5  # 错误
        
        # 读取操作码
        opcode = struct.unpack('!H', data[:2])[0]
        
        # 创建新的套接字进行响应
        response_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        response_socket.settimeout(5)  # 5秒超时
        
        try:
            if opcode == OP_RRQ:  # 读请求
                # 解析请求
                request_parts = data[2:].split(b'\0')
                filename = request_parts[0].decode('utf-8')
                mode = request_parts[1].decode('utf-8').lower()
                
                logger.info(f"收到TFTP读请求: {filename}, 模式: {mode}")
                
                # 修改点：始终先查找设备特定配置映射，无论请求的文件是否存在
                mapped_file = self.get_device_specific_file(filename)
                
                if mapped_file:
                    # 使用设备映射的配置文件
                    mapped_path = os.path.join(self.server.root_dir, mapped_file)
                    if os.path.exists(mapped_path):
                        logger.info(f"找到设备映射配置: {mapped_file}")
                        filepath = mapped_path
                        is_fallback = False  # 标记是否使用了回退配置
                    else:
                        logger.error(f"映射的配置文件 {mapped_file} 不存在")
                        # 尝试使用原始请求的文件
                        filepath = os.path.join(self.server.root_dir, filename)
                        is_fallback = True  # 标记使用了回退配置
                        fallback_from = mapped_file  # 记录原映射配置
                        if not os.path.exists(filepath):
                            error_msg = f"文件 {filename} 不存在".encode('utf-8')
                            error_packet = struct.pack('!HH', OP_ERROR, 1) + error_msg + b'\0'
                            response_socket.sendto(error_packet, self.client_address)
                            return
                else:
                    # 没有找到映射，使用原始请求的文件
                    filepath = os.path.join(self.server.root_dir, filename)
                    is_fallback = False  # 直接使用请求的文件，不是回退
                    if not os.path.exists(filepath):
                        logger.error(f"找不到设备映射，且请求的文件 {filename} 不存在")
                        error_msg = f"文件 {filename} 不存在".encode('utf-8')
                        error_packet = struct.pack('!HH', OP_ERROR, 1) + error_msg + b'\0'
                        response_socket.sendto(error_packet, self.client_address)
                        return
                
                # 打开文件并发送
                try:
                    with open(filepath, 'rb') as file:
                        # 初始化块号
                        block_number = 1
                        
                        # 获取实际传输的文件名(而非请求的文件名)
                        actual_filename = os.path.basename(filepath)
                        
                        while True:
                            # 读取一块数据 (最大512字节)
                            block_data = file.read(512)
                            
                            # 构造数据包
                            data_packet = struct.pack('!HH', OP_DATA, block_number) + block_data
                            
                            # 发送数据
                            response_socket.sendto(data_packet, self.client_address)
                            
                            # 等待确认
                            try:
                                ack_data, client_addr = response_socket.recvfrom(4)
                                ack_opcode = struct.unpack('!H', ack_data[:2])[0]
                                ack_block = struct.unpack('!H', ack_data[2:4])[0]
                                
                                if ack_opcode != OP_ACK or ack_block != block_number:
                                    logger.error(f"TFTP传输错误: 预期确认块 {block_number}, 收到 {ack_block}")
                                    break
                                    
                                # 文件结束检查
                                if len(block_data) < 512:
                                    # 使用实际文件名记录日志，根据是否回退提供不同提示
                                    actual_filename = os.path.basename(filepath)
                                    if is_fallback:
                                        logger.info(f"映射的配置文件 {fallback_from} 不存在，使用默认配置文件 {actual_filename} 完成传输")
                                    else:
                                        logger.info(f"TFTP文件 {actual_filename} 传输完成")
                                    break
                                    
                                # 下一个块
                                block_number += 1
                                if block_number > 65535:  # 块号超出范围
                                    block_number = 0
                            except socket.timeout:
                                logger.error(f"等待ACK超时，重试...")
                                continue
                                
                except Exception as e:
                    logger.error(f"TFTP文件传输错误: {str(e)}")
                    error_msg = f"传输错误: {str(e)}".encode('utf-8')
                    error_packet = struct.pack('!HH', OP_ERROR, 0) + error_msg + b'\0'
                    response_socket.sendto(error_packet, self.client_address)
            elif opcode == OP_WRQ:  # 写请求
                # 解析请求
                request_parts = data[2:].split(b'\0')
                filename = request_parts[0].decode('utf-8')
                mode = request_parts[1].decode('utf-8').lower()
                
                logger.info(f"收到TFTP写请求: {filename}, 模式: {mode}")
                
                # 安全处理: 确保文件名不包含目录遍历尝试
                safe_filename = os.path.basename(filename)
                
                # 创建上传目录(如果不存在)
                upload_dir = os.path.join(self.server.root_dir, "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                
                # 为避免覆盖同名文件，添加时间戳
                timestamp = time.strftime("%Y%m%d%H%M%S")
                filepath = os.path.join(upload_dir, f"{timestamp}_{safe_filename}")
                
                try:
                    with open(filepath, 'wb') as file:
                        # 发送初始ACK，块号为0
                        ack_packet = struct.pack('!HH', OP_ACK, 0)
                        response_socket.sendto(ack_packet, self.client_address)
                        
                        block_number = 1
                        while True:
                            try:
                                # 等待DATA包
                                data_packet, client_addr = response_socket.recvfrom(516)  # 4(header) + 512(data)
                                
                                # 解析数据包
                                if len(data_packet) < 4:
                                    logger.error("收到无效的数据包")
                                    break
                                    
                                opcode = struct.unpack('!H', data_packet[:2])[0]
                                recv_block = struct.unpack('!H', data_packet[2:4])[0]
                                
                                if opcode != OP_DATA:
                                    logger.error(f"预期DATA包，但收到操作码: {opcode}")
                                    break
                                
                                if recv_block != block_number:
                                    logger.warning(f"接收到非预期的块号: {recv_block}，预期: {block_number}")
                                    # 发送确认上一个正确块
                                    ack_packet = struct.pack('!HH', OP_ACK, block_number - 1)
                                    response_socket.sendto(ack_packet, client_addr)
                                    continue
                                
                                # 写入数据
                                block_data = data_packet[4:]
                                file.write(block_data)
                                
                                # 发送ACK
                                ack_packet = struct.pack('!HH', OP_ACK, recv_block)
                                response_socket.sendto(ack_packet, client_addr)
                                
                                # 文件传输完成条件
                                if len(block_data) < 512:
                                    logger.info(f"设备上传文件完成: {safe_filename} -> {filepath}")
                                    logger.info(f"文件大小: {os.path.getsize(filepath)} 字节")
                                    
                                    # 尝试分析上传文件内容
                                    analyze_uploaded_file(filepath, logger)
                                    break
                                
                                block_number += 1
                                if block_number > 65535:  # 块号超出范围
                                    block_number = 0
                                    
                            except socket.timeout:
                                logger.error("等待DATA包超时")
                                break
                                
                except Exception as e:
                    logger.error(f"处理文件上传时出错: {str(e)}")
                    error_msg = f"上传错误: {str(e)}".encode('utf-8')
                    error_packet = struct.pack('!HH', OP_ERROR, 0) + error_msg + b'\0'
                    response_socket.sendto(error_packet, self.client_address)
            else:
                # 未知操作码
                logger.error(f"收到未知的TFTP操作码: {opcode}")
                error_msg = "未知操作码".encode('utf-8')
                error_packet = struct.pack('!HH', OP_ERROR, 4) + error_msg + b'\0'
                response_socket.sendto(error_packet, self.client_address)
        
        finally:
            response_socket.close()

    def get_device_specific_file(self, requested_filename):
        """根据设备身份获取特定配置文件"""
        # 获取请求者IP地址
        client_ip = self.client_address[0]
        dhcp_server = self.server.dhcp_server
        logger = self.server.logger
        
        logger.info(f"TFTP请求来自IP: {client_ip}, 请求文件: {requested_filename}")
        
        # 获取设备映射
        device_mapping = getattr(self.server, 'device_mapping', {})
        if not device_mapping and dhcp_server:
            device_mapping = dhcp_server.config.get("device_mapping", {})
        
        # 从DHCP服务器获取标识符
        if dhcp_server and hasattr(dhcp_server, 'ip_to_identifiers') and client_ip in dhcp_server.ip_to_identifiers:
            identifiers = dhcp_server.ip_to_identifiers[client_ip]
            logger.info(f"设备标识符: {identifiers}")
            
            # 1. 先尝试直接匹配当前标识符
            for id_type, id_value in [
                ("client_id", identifiers.get("client_id")),
                ("sn", identifiers.get("sn")),
                ("mac", identifiers.get("mac"))
            ]:
                if id_value and id_value in device_mapping:
                    logger.info(f"找到直接匹配! {id_type}={id_value}")
                    mapping = device_mapping[id_value]
                    return mapping["config_file"]
            
            # 2. 如果当前标识符未匹配，尝试该MAC关联的所有Client ID
            mac = identifiers.get("mac")
            current_client_id = identifiers.get("client_id")
            
            if mac and hasattr(dhcp_server, 'mac_to_client_ids') and mac in dhcp_server.mac_to_client_ids:
                logger.info(f"查找MAC {mac}的所有已知Client ID")
                for related_client_id in dhcp_server.mac_to_client_ids[mac]:
                    if related_client_id != current_client_id:  # 避免重复检查
                        logger.info(f"检查关联的Client ID: {related_client_id}")
                        if related_client_id in device_mapping:
                            logger.info(f"通过关联Client ID找到匹配! {related_client_id}")
                            mapping = device_mapping[related_client_id]
                            return mapping["config_file"]
        
        # 如果找不到映射，使用默认配置文件
        user_default = self.server.bootfile
        logger.info(f"未找到任何匹配，使用默认配置: {user_default}")
        return user_default

# 修改SimpleTFTPServer类允许地址重用
class SimpleTFTPServer(socketserver.ThreadingUDPServer):
    """简易TFTP服务器"""
    allow_reuse_address = True  # 启用地址重用
    
    def __init__(self, server_address, root_dir, bootfile="startup.cfg", dhcp_server=None, logger=None, device_mapping=None):
        super().__init__(server_address, TFTPHandler)
        self.root_dir = root_dir
        self.bootfile = bootfile
        self.dhcp_server = dhcp_server
        self.logger = logger or logging.getLogger('ZTP')
        self.device_mapping = device_mapping
        
        # 额外设置套接字选项
        if hasattr(socket, 'SO_REUSEPORT'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

# 修改ZTPTftpServer类
class ZTPTftpServer:
    def __init__(self, config, logger, dhcp_server=None):
        self.config = config
        self.logger = logger
        self.dhcp_server = dhcp_server
        # 确保TFTP根目录存在
        os.makedirs(config["root_dir"], exist_ok=True)
        self.server = None
        self._running = False  # 添加状态跟踪
        self._server_thread = None  # 跟踪服务器线程

    def start(self):
        """启动TFTP服务器"""
        # 如果已经在运行，不要重复启动
        if self._running:
            self.logger.info("TFTP服务器已经在运行中")
            return

        self.logger.info(f"启动TFTP服务器，根目录: {self.config['root_dir']}")
        try:
            # 确保先停止任何现有服务器
            if self.server:
                self.stop()
                
            # 获取引导文件名
            bootfile = self.config.get("bootfile")
            
            # 获取设备映射
            device_mapping = self.config.get("device_mapping")
            
            # 使用Windows兼容的TFTP服务器
            server_address = (self.config["server_ip"], 69)
            self.server = SimpleTFTPServer(
                server_address, 
                self.config["root_dir"], 
                bootfile, 
                self.dhcp_server,
                self.logger,
                device_mapping
            )
            self.logger.info(f"TFTP服务器监听在 {server_address[0]}:{server_address[1]}")
            self.logger.info(f"默认引导文件: {bootfile}")
            
            # 标记为运行中
            self._running = True
            
            # 在线程中运行服务器
            self._server_thread = threading.Thread(target=self._run_server)
            self._server_thread.daemon = True
            self._server_thread.start()
            
        except Exception as e:
            self._running = False
            self.logger.error(f"TFTP服务器启动失败: {str(e)}")
            
    def _run_server(self):
        """在线程中实际运行服务器"""
        try:
            if self.server:
                self.server.serve_forever()
        except Exception as e:
            self.logger.error(f"TFTP服务器运行时错误: {str(e)}")
        finally:
            self._running = False

    def stop(self):
        """停止TFTP服务器"""
        if self.server:
            try:
                self._running = False
                self.server.shutdown()
                self.server.server_close()  # 确保关闭服务器
                self.server = None
                self.logger.info("TFTP服务器已停止")
            except Exception as e:
                self.logger.error(f"停止TFTP服务器时出错: {str(e)}")

# DHCP服务器实现 - 使用原生socket
class SocketDHCPServer:
    """使用socket实现的DHCP服务器"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.allocated_ips = {}         # MAC地址到IP地址的映射
        self.ip_to_mac = {}             # IP地址到MAC地址的反向映射
        self.ip_to_identifiers = {}     # IP地址到所有标识符(MAC、Client ID、SN)的映射
        self.running = False
        
        # 新增: MAC地址到不同形式Client ID的映射
        self.mac_to_client_ids = {}     # 记录同一设备不同阶段的Client ID
        self.client_id_to_mac = {}      # Client ID到MAC的反向映射
        
        # DHCP消息类型
        self.DHCP_DISCOVER = 1
        self.DHCP_OFFER = 2
        self.DHCP_REQUEST = 3
        self.DHCP_ACK = 5
        self.DHCP_RELEASE = 7  # 添加RELEASE类型定义
        
        # DHCP选项代码
        self.OPT_SUBNET_MASK = 1
        self.OPT_ROUTER = 3
        self.OPT_DNS_SERVER = 6
        self.OPT_HOSTNAME = 12
        self.OPT_REQUESTED_IP = 50
        self.OPT_LEASE_TIME = 51
        self.OPT_MSG_TYPE = 53
        self.OPT_SERVER_ID = 54
        self.OPT_PARAM_REQ_LIST = 55
        self.OPT_TFTP_SERVER = 66
        self.OPT_BOOTFILE = 67
        self.OPT_END = 255

        # 添加定时记录任务
        self.log_timer = None
        self.start_log_timer()

    def load_client_id_mappings(self):
        """从文件加载客户端标识符映射关系"""
        try:
            if os.path.exists(self.client_id_map_file):
                import json
                with open(self.client_id_map_file, 'r') as f:
                    saved_mappings = json.load(f)
                    self.mac_to_client_ids = saved_mappings.get('mac_to_client_ids', {})
                    self.client_id_to_mac = saved_mappings.get('client_id_to_mac', {})
                self.logger.info(f"从文件加载了 {len(self.mac_to_client_ids)} 个Client ID映射关系")
                self.logger.debug(f"已加载的Client ID映射: {self.mac_to_client_ids}")
        except Exception as e:
            self.logger.error(f"加载Client ID映射文件失败: {str(e)}")

    def save_client_id_mappings(self):
        """保存客户端标识符映射关系到文件"""
        try:
            import json
            mappings = {
                'mac_to_client_ids': self.mac_to_client_ids,
                'client_id_to_mac': self.client_id_to_mac
            }
            with open(self.client_id_map_file, 'w') as f:
                json.dump(mappings, f, indent=2)
            self.logger.info(f"保存了 {len(self.mac_to_client_ids)} 个Client ID映射关系到文件")
        except Exception as e:
            self.logger.error(f"保存Client ID映射文件失败: {str(e)}")

    def update_client_id_mapping(self, mac_address, client_id):
        """更新MAC地址和Client ID之间的映射关系"""
        if not mac_address or not client_id:
            return
            
        # 如果是新的MAC地址，创建一个空列表
        if mac_address not in self.mac_to_client_ids:
            self.mac_to_client_ids[mac_address] = []
            
        # 如果是新的Client ID，添加到列表中
        if client_id not in self.mac_to_client_ids[mac_address]:
            self.mac_to_client_ids[mac_address].append(client_id)
            self.client_id_to_mac[client_id] = mac_address
            self.logger.info(f"学习到新的Client ID映射: MAC={mac_address} -> Client ID={client_id}")

    def start_log_timer(self):
        """启动定期记录IP分配状态的定时器"""
        if self.running:
            # 每5分钟记录一次
            self.log_timer = threading.Timer(300, self.log_timer_callback)
            self.log_timer.daemon = True
            self.log_timer.start()

    def log_timer_callback(self):
        """定时器回调函数"""
        self.logger.info("定时记录当前IP分配状态:")
        self.log_allocated_ips()
        self.start_log_timer()  # 重新启动定时器

    def stop(self):
        """停止DHCP服务器"""
        self.running = False
        if self.log_timer:
            self.log_timer.cancel()
    
    def load_ip_leases(self):
        """从文件加载IP地址租约信息"""
        try:
            if os.path.exists(self.leases_file):
                import json
                with open(self.leases_file, 'r') as f:
                    leases_data = json.load(f)
                    
                now = time.time()
                # 过滤已过期的租约
                for ip, lease in leases_data.items():
                    if lease["expires"] > now:
                        self.ip_leases[ip] = lease
                        self.allocated_ips[lease["mac"]] = ip
                        self.logger.info(f"加载有效租约: IP={ip}, MAC={lease['mac']}, 过期时间={time.ctime(lease['expires'])}")
                    else:
                        self.logger.info(f"跳过已过期租约: IP={ip}, MAC={lease['mac']}")
                        
                self.logger.info(f"从文件 {self.leases_file} 加载了 {len(self.allocated_ips)} 个有效租约")
            else:
                self.logger.info(f"租约文件 {self.leases_file} 不存在，将创建新的租约记录")
        except Exception as e:
            self.logger.error(f"加载租约文件失败: {str(e)}")
        
    def save_ip_leases(self):
        """保存IP地址租约信息到文件"""
        try:
            import json
            with open(self.leases_file, 'w') as f:
                json.dump(self.ip_leases, f, indent=2)
            self.logger.info(f"保存了 {len(self.ip_leases)} 个租约到文件 {self.leases_file}")
        except Exception as e:
            self.logger.error(f"保存租约文件失败: {str(e)}")
    
    def listen(self):
        """监听DHCP请求"""
        # 创建UDP套接字
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # 在Windows上启用特定选项
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        try:
            # 先尝试绑定到特定接口
            try:
                specific_ip = self.config["server_ip"]
                sock.bind((specific_ip, 67))
                self.logger.info(f"DHCP服务器绑定到特定接口 {specific_ip}:67")
            except:
                # 如果特定接口绑定失败，尝试绑定到所有接口
                sock.bind(('0.0.0.0', 67))
                self.logger.info("DHCP服务器绑定到所有接口 0.0.0.0:67")
                
            self.running = True
            self.logger.info("DHCP服务器准备就绪，等待设备请求...")
            self.log_allocated_ips()  # 启动时记录初始分配状态
            
            while self.running:
                try:
                    # 接收DHCP请求
                    data, addr = sock.recvfrom(4096)
                    
                    # 创建线程处理请求
                    thread = threading.Thread(target=self.handle_dhcp_packet, args=(sock, data, addr))
                    thread.daemon = True
                    thread.start()
                except Exception as e:
                    self.logger.error(f"处理DHCP数据包时出错: {str(e)}")
        
        except Exception as e:
            self.logger.error(f"DHCP服务器启动失败: {str(e)}")
        finally:
            sock.close()
            self.logger.info("DHCP服务器已关闭")
            self.log_allocated_ips()  # 关闭时记录最终分配状态
    
    def handle_dhcp_packet(self, sock, data, addr):
        """处理DHCP数据包"""
        try:
            # 检查是否是DHCP数据包
            if len(data) < 240:  # DHCP报头最小长度
                return
                
            # 检查操作码是否是BOOTREQUEST (1)
            if data[0] != 1:  # op字段
                return
                
            # 提取事务ID (xid)
            xid = struct.unpack('>L', data[4:8])[0]
            
            # 提取客户端MAC地址
            chaddr = data[28:34]
            mac_address = ':'.join(f'{b:02x}' for b in chaddr)
            
            # 提取DHCP选项
            options = self.parse_dhcp_options(data[240:])
            if not options or self.OPT_MSG_TYPE not in options:
                return
                
            msg_type = options[self.OPT_MSG_TYPE][0]
            self.logger.debug(f"DHCP消息类型: {msg_type}, MAC: {mac_address}, XID: {xid}")
            
            if msg_type == self.DHCP_DISCOVER:
                self.logger.info(f"收到DHCP DISCOVER: MAC={mac_address}")
                self.send_dhcp_offer(sock, data, chaddr, xid)
            elif msg_type == self.DHCP_REQUEST:
                self.logger.info(f"收到DHCP REQUEST: MAC={mac_address}")
                self.send_dhcp_ack(sock, data, chaddr, xid)
            elif msg_type == self.DHCP_RELEASE:
                self.logger.info(f"收到DHCP RELEASE: MAC={mac_address}")
                self.release_ip(mac_address)
        
        except Exception as e:
            self.logger.error(f"处理DHCP数据包时出错: {str(e)}")

    def release_ip(self, mac_address):
        """释放指定MAC地址的IP地址"""
        if mac_address in self.allocated_ips:
            ip = self.allocated_ips[mac_address]
            del self.allocated_ips[mac_address]
            if ip in self.ip_to_mac:
                del self.ip_to_mac[ip]
            if ip in self.ip_to_identifiers:
                del self.ip_to_identifiers[ip]
            self.logger.info(f"释放IP地址: {ip} (MAC={mac_address})")
            # 记录更新后的已分配IP
            self.log_allocated_ips()
    
    def parse_dhcp_options(self, options_data):
        """解析DHCP选项"""
        options = {}
        i = 0
        
        while i < len(options_data):
            opt = options_data[i]
            
            # 选项结束
            if opt == self.OPT_END:
                break
                
            # 选项填充
            if opt == 0:
                i += 1
                continue
                
            # 检查是否有足够的数据
            if i + 1 >= len(options_data):
                break
                
            length = options_data[i+1]
            if i + 2 + length > len(options_data):
                break
                
            # 提取选项数据
            data = options_data[i+2:i+2+length]
            options[opt] = data
            
            i += 2 + length
            
        return options
    
    def allocate_ip(self, mac_address, client_id=None, sn=None):
        """为MAC地址分配IP地址，并记录标识符映射"""
        # 如果已经分配了IP，直接返回
        if mac_address in self.allocated_ips:
            return self.allocated_ips[mac_address]
            
        # 如果在设备映射中有固定IP
        if "device_mapping" in self.config and mac_address in self.config["device_mapping"]:
            if "fixed_ip" in self.config["device_mapping"][mac_address]:
                fixed_ip = self.config["device_mapping"][mac_address]["fixed_ip"]
                # 检查固定IP是否已分配给其他MAC
                if fixed_ip in set(self.allocated_ips.values()):
                    self.logger.warning(f"固定IP {fixed_ip} 已被分配，为 {mac_address} 分配新IP")
                else:
                    self.allocated_ips[mac_address] = fixed_ip
                    self.ip_to_mac[fixed_ip] = mac_address
                    self.ip_to_identifiers[fixed_ip] = {"mac": mac_address}
                    self.logger.info(f"分配固定IP: {fixed_ip} -> MAC={mac_address}")
                    # 记录已分配IP
                    self.log_allocated_ips()
                    return fixed_ip
        
        # 分配新IP
        start_ip = int(ipaddress.IPv4Address(self.config["start_ip"]))
        end_ip = int(ipaddress.IPv4Address(self.config["end_ip"]))
        used_ips = set(self.allocated_ips.values())
        
        # 尝试分配IP
        for ip_int in range(start_ip, end_ip + 1):
            ip = str(ipaddress.IPv4Address(ip_int))
            if ip not in used_ips:
                self.allocated_ips[mac_address] = ip
                self.ip_to_mac[ip] = mac_address
                identifiers = {"mac": mac_address}
                if client_id:
                    identifiers["client_id"] = client_id
                if sn:
                    identifiers["sn"] = sn
                self.ip_to_identifiers[ip] = identifiers
                self.logger.info(f"分配新IP: {ip} -> MAC={mac_address}")
                # 记录已分配IP
                self.log_allocated_ips()
                # 在allocate_ip方法结尾处添加
                if ip:
                    self.logger.debug(f"设备标识符详情: MAC={mac_address}, Client ID={client_id}, SN={sn}")
                    self.logger.debug(f"IP到标识符映射表: {self.ip_to_identifiers}")
                return ip
                
        # 没有可用IP
        self.logger.error(f"IP地址池已耗尽，无法为MAC {mac_address}分配IP")
        return None
    
    def create_dhcp_packet(self, op, xid, chaddr, yiaddr, options_list):
        """创建DHCP数据包"""
        packet = bytearray(240)  # 初始化包头
        
        # 设置包头字段
        packet[0] = op          # op (操作码): 1=请求, 2=响应
        packet[1] = 1           # htype: 以太网
        packet[2] = 6           # hlen: MAC地址长度
        packet[3] = 0           # hops
        
        # 事务ID
        packet[4:8] = struct.pack('>L', xid)
        
        # 秒数
        packet[8:10] = b'\x00\x00'
        
        # 标志 (设置广播标志)
        packet[10:12] = b'\x80\x00'
        
        # ciaddr (客户端IP)
        packet[12:16] = b'\x00\x00\x00\x00'
        
        # yiaddr (你的IP)
        if yiaddr:
            packet[16:20] = ipaddress.IPv4Address(yiaddr).packed
        
        # siaddr (下一个服务器IP)
        server_ip = ipaddress.IPv4Address(self.config["server_ip"]).packed
        packet[20:24] = server_ip
        
        # giaddr (中继代理IP)
        packet[24:28] = b'\x00\x00\x00\x00'
        
        # chaddr (客户端硬件地址)
        packet[28:28+len(chaddr)] = chaddr
        packet[28+len(chaddr):44] = b'\x00' * (16 - len(chaddr))  # 填充剩余部分
        
        # sname (服务器主机名) - 填0
        packet[44:108] = b'\x00' * 64
        
        # file (引导文件名) - 这里可以放bootfile
        bootfile_bytes = self.config["options"]["67"].encode()
        if len(bootfile_bytes) <= 128:
            packet[108:108+len(bootfile_bytes)] = bootfile_bytes
            packet[108+len(bootfile_bytes):236] = b'\x00' * (128 - len(bootfile_bytes))
        else:
            packet[108:236] = bootfile_bytes[:128]
        
        # Magic Cookie
        packet[236:240] = b'\x63\x82\x53\x63'
        
        # 添加DHCP选项
        options = bytearray()
        
        # 添加所有选项
        for opt_code, opt_value in options_list:
            options.append(opt_code)
            if isinstance(opt_value, int):
                options.append(1)  # 长度为1字节
                options.append(opt_value)
            elif isinstance(opt_value, str):
                value_bytes = opt_value.encode()
                options.append(len(value_bytes))
                options.extend(value_bytes)
            elif isinstance(opt_value, bytes):
                options.append(len(opt_value))
                options.extend(opt_value)
            elif isinstance(opt_value, list):
                flat_bytes = b''
                for item in opt_value:
                    if isinstance(item, str):
                        if '.' in item:  # IP地址
                            flat_bytes += ipaddress.IPv4Address(item).packed
                    elif isinstance(item, int):
                        flat_bytes += struct.pack('!B', item)
                options.append(len(flat_bytes))
                options.extend(flat_bytes)
        
        # 结束选项
        options.append(self.OPT_END)
        
        # 将选项添加到数据包
        return packet + options
    
    def send_dhcp_offer(self, sock, request, chaddr, xid):
        """发送DHCP OFFER响应"""
        # 将MAC地址转换为可读格式用于日志
        mac_address = ':'.join(f'{b:02x}' for b in chaddr)
        
        # 提取设备标识符
        client_id, sn = self.extract_device_identifiers(request, mac_address)
        
        # 获取设备映射信息 - 添加这行修复错误
        device_info = self.get_device_mapping(mac_address, client_id, sn)
        
        # 分配IP地址时传入所有标识符
        yiaddr = self.allocate_ip(mac_address, client_id, sn)
        if not yiaddr:
            self.logger.error(f"无法为MAC {mac_address}分配IP")
            return
        
        # DHCP选项基本设置
        server_id = self.config["server_ip"]
        subnet_mask = self.config["subnet_mask"]
        router = self.config["gateway"]
        dns_servers = self.config["dns_servers"]
        lease_time = struct.pack('>L', self.config["lease_time"])
        tftp_server = self.config["options"]["66"]
        
        # 根据设备映射确定引导文件
        bootfile = self.config["options"]["67"]  # 默认引导文件
        if device_info and "config_file" in device_info:
            bootfile = device_info["config_file"]
            self.logger.info(f"为设备 {mac_address} 指定特定配置文件: {bootfile}")
        
        # 构造选项列表
        options = [
            (self.OPT_MSG_TYPE, self.DHCP_OFFER),
            (self.OPT_SERVER_ID, ipaddress.IPv4Address(server_id).packed),
            (self.OPT_LEASE_TIME, lease_time),
            (self.OPT_SUBNET_MASK, ipaddress.IPv4Address(subnet_mask).packed),
            (self.OPT_ROUTER, ipaddress.IPv4Address(router).packed)
        ]
        
        # 单独添加TFTP服务器地址和引导文件名选项
        options.append((self.OPT_TFTP_SERVER, tftp_server.encode()))
        options.append((self.OPT_BOOTFILE, bootfile.encode()))
        
        # 添加DNS服务器
        dns_packed = b''
        for dns in dns_servers:
            dns_packed += ipaddress.IPv4Address(dns).packed
        if dns_packed:
            options.append((self.OPT_DNS_SERVER, dns_packed))
        
        # 创建DHCP OFFER数据包
        offer_packet = self.create_dhcp_packet(2, xid, chaddr, yiaddr, options)
        
        # 设置广播标志(某些设备需要)
        offer_packet[10:12] = b'\x80\x00'
        
        # 发送DHCP OFFER - 使用明确的广播地址
        try:
            sock.sendto(offer_packet, ('255.255.255.255', 68))
            self.logger.info(f"发送DHCP OFFER: IP={yiaddr} -> MAC={mac_address}")
        except Exception as e:
            self.logger.error(f"发送DHCP OFFER失败: {str(e)}")
            # 尝试使用另一种方式
            try:
                # 尝试使用子网广播
                ip_parts = self.config["server_ip"].split('.')
                broadcast = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"
                sock.sendto(offer_packet, (broadcast, 68))
                self.logger.info(f"使用子网广播发送DHCP OFFER: {broadcast}")
            except Exception as e2:
                self.logger.error(f"备用发送方法也失败: {str(e2)}")
    
    def send_dhcp_ack(self, sock, request, chaddr, xid):
        """发送DHCP ACK响应"""
        # 将MAC地址转换为可读格式用于日志
        mac_address = ':'.join(f'{b:02x}' for b in chaddr)
        
        # 提取设备标识符 - 添加这部分
        client_id, sn = self.extract_device_identifiers(request, mac_address)
        device_info = self.get_device_mapping(mac_address, client_id, sn)
        
        # 获取已分配的IP地址
        yiaddr = self.allocated_ips.get(mac_address)
        if not yiaddr:
            self.logger.error(f"未找到MAC {mac_address}的分配IP")
            return
        
        # 更新标识符映射 - 添加这部分
        identifiers = {"mac": mac_address}
        if client_id:
            identifiers["client_id"] = client_id
        if sn:
            identifiers["sn"] = sn
        self.ip_to_identifiers[yiaddr] = identifiers
        self.logger.debug(f"更新设备标识符映射: IP={yiaddr}, 标识符={identifiers}")
        
        # 根据设备映射确定引导文件
        bootfile = self.config["options"]["67"]  # 默认引导文件
        if device_info and "config_file" in device_info:
            bootfile = device_info["config_file"]
            self.logger.info(f"为设备 {mac_address} 指定特定配置文件: {bootfile}")
        
        # DHCP选项
        server_id = self.config["server_ip"]
        subnet_mask = self.config["subnet_mask"]
        router = self.config["gateway"]
        dns_servers = self.config["dns_servers"]
        lease_time = struct.pack('>L', self.config["lease_time"])
        tftp_server = self.config["options"]["66"]
        
        # 构造选项列表
        options = [
            (self.OPT_MSG_TYPE, self.DHCP_ACK),
            (self.OPT_SERVER_ID, ipaddress.IPv4Address(server_id).packed),
            (self.OPT_LEASE_TIME, lease_time),
            (self.OPT_SUBNET_MASK, ipaddress.IPv4Address(subnet_mask).packed),
            (self.OPT_ROUTER, ipaddress.IPv4Address(router).packed),
            (self.OPT_TFTP_SERVER, tftp_server),
            (self.OPT_BOOTFILE, bootfile)
        ]
        
        # 添加DNS服务器
        dns_packed = b''
        for dns in dns_servers:
            dns_packed += ipaddress.IPv4Address(dns).packed
        if dns_packed:
            options.append((self.OPT_DNS_SERVER, dns_packed))
        
        # 创建DHCP ACK数据包
        ack_packet = self.create_dhcp_packet(2, xid, chaddr, yiaddr, options)
        
        # 发送DHCP ACK
        try:
            sock.sendto(ack_packet, ('<broadcast>', 68))
            self.logger.info(f"发送DHCP ACK: IP={yiaddr} -> MAC={mac_address}")
        except Exception as e:
            self.logger.error(f"发送DHCP ACK失败: {str(e)}")

    def get_device_mapping(self, mac_address, client_id=None, sn=None):
        """根据多种标识符查找设备映射"""
        if "device_mapping" not in self.config:
            return None
        
        # 首先尝试根据MAC地址查找
        if mac_address in self.config["device_mapping"]:
            mapping = self.config["device_mapping"][mac_address]
            self.logger.info(f"找到MAC地址映射: {mac_address} -> {mapping.get('config_file')}")
            return mapping
        
        # 尝试根据Client ID查找
        if client_id:
            # 直接匹配完整Client ID
            if client_id in self.config["device_mapping"]:
                mapping = self.config["device_mapping"][client_id]
                self.logger.info(f"找到Client ID映射: {client_id} -> {mapping.get('config_file')}")
                return mapping
            
            # 尝试过滤VLAN并匹配 
            try:
                # 解析Client ID并检查是否包含VLAN标识
                readable_id = self.parse_client_id_readable(client_id)
                if readable_id and "原始:" in readable_id:
                    # 提取MAC部分
                    mac_part = readable_id.split(" (原始:")[0].strip()
                    # 尝试查找过滤后的MAC
                    filtered_id = f"client_id:{mac_part}"
                    if filtered_id in self.config["device_mapping"]:
                        mapping = self.config["device_mapping"][filtered_id]
                        self.logger.info(f"找到过滤后Client ID映射: {filtered_id} -> {mapping.get('config_file')}")
                        return mapping
            except:
                pass
        
        # 尝试根据SN查找
        if sn and sn in self.config["device_mapping"]:
            mapping = self.config["device_mapping"][sn]
            self.logger.info(f"找到序列号映射: {sn} -> {mapping.get('config_file')}")
            return mapping
        
        self.logger.debug(f"未找到设备映射: MAC={mac_address}, Client ID={client_id}, SN={sn}")
        return None

    def extract_device_identifiers(self, data, mac_address):
        """从DHCP数据包中提取设备标识符"""
        options = self.parse_dhcp_options(data[240:])
        
        # 提取Client Identifier (选项61)
        client_id = None
        if 61 in options:
            client_id_raw = options[61]
            
            # 记录原始十六进制格式
            raw_hex = client_id_raw.hex()
            self.logger.debug(f"原始Client ID(十六进制): {raw_hex}")
            
            # 检查第一个字节是否为硬件类型标识符(通常为02表示以太网)
            if len(client_id_raw) > 1 and client_id_raw[0] == 2:
                # 移除硬件类型字节，只保留实际标识符
                client_id = f"client_id:{client_id_raw[1:].hex()}"
            else:
                # 如果格式不符合预期，使用完整的值
                client_id = f"client_id:{client_id_raw.hex()}"
            
            # 解析为可读形式
            readable_id = self.parse_client_id_readable(client_id)
            if readable_id:
                self.logger.info(f"Client ID可读形式: {readable_id}")
                    
            # 新增: 更新MAC地址和Client ID之间的映射关系
            self.update_client_id_mapping(mac_address, client_id)
                
            self.logger.debug(f"Client Identifier: {client_id}")
        
        # 尝试从Vendor Class Identifier (选项60)或其他选项中提取SN
        sn = None
        if 60 in options:
            vendor_class = options[60].decode('ascii', errors='ignore')
            # H3C设备的SN通常在厂商类标识中，格式可能因设备而异
            import re
            sn_match = re.search(r'SN[=:]([A-Za-z0-9]+)', vendor_class)
            if sn_match:
                sn = f"sn:{sn_match.group(1)}"
                self.logger.debug(f"Serial Number: {sn}")
        
        return client_id, sn

    def parse_client_id_readable(self, client_id):
        """将Client ID解析为人类可读形式，并过滤掉VLAN标识"""
        if not client_id or not isinstance(client_id, str):
            return None
            
        # 提取十六进制部分
        if client_id.startswith("client_id:"):
            hex_value = client_id[10:]
        else:
            hex_value = client_id
            
        try:
            # 如果有前导字节00，去掉它
            if hex_value.startswith("00"):
                hex_value = hex_value[2:]
                
            # 将十六进制转换为二进制
            binary_data = bytes.fromhex(hex_value)
            
            # 尝试解析为ASCII
            try:
                ascii_value = binary_data.decode('ascii', errors='replace')
                
                # 过滤掉VLAN标识 (如 "1c94683eaf48-VLAN0001")
                import re
                vlan_match = re.match(r'^([0-9a-fA-F]+)-VLAN\d+', ascii_value)
                if vlan_match:
                    mac_part = vlan_match.group(1)
                    self.logger.info(f"过滤VLAN标识，提取MAC: {mac_part}")
                    return f"{mac_part} (原始: {ascii_value})"
                    
                # 其他特定格式处理 (如 xx.xx.xx-Interface)
                if re.search(r'[0-9a-fA-F]{2,4}[.:][0-9a-fA-F]{2,4}[.:][0-9a-fA-F]{2,4}', ascii_value):
                    return ascii_value
                    
                # 如果是纯MAC地址
                if len(binary_data) == 6:  # MAC地址为6字节
                    return ':'.join(f'{b:02x}' for b in binary_data)
            except:
                pass
            
            # 如果上述方法失败，使用十六进制表示，每两个字符用冒号分隔
            readable = ':'.join(f'{b:02x}' for b in binary_data)
            return readable
                
        except Exception as e:
            self.logger.debug(f"解析Client ID失败: {str(e)}")
            return f"HEX:{hex_value}"

    def log_allocated_ips(self):
        """记录当前已分配的IP地址到日志（INFO级别）"""
        if not self.allocated_ips:
            self.logger.info("当前没有已分配的IP地址")
            return
        
        # 格式化输出表头 (第一个表格)
        self.logger.info("+--------------------------------------------+")
        self.logger.info("|           当前已分配的IP地址              |")
        self.logger.info("+--------------------+----------------------+")
        self.logger.info("| {:^18} | {:^20} |".format("MAC地址", "IP地址"))
        self.logger.info("+--------------------+----------------------+")
        
        # 输出每个分配的IP
        for mac, ip in sorted(self.allocated_ips.items()):
            self.logger.info("| {:<18} | {:<20} |".format(mac, ip))
        
        self.logger.info("+--------------------+----------------------+")
        self.logger.info(f"| 共 {len(self.allocated_ips):<14} 个已分配地址     |")
        self.logger.info("+--------------------------------------------+")

        # 如果有更详细的标识符信息，也可以展示
        if hasattr(self, 'ip_to_identifiers') and self.ip_to_identifiers:
            # 计算表格宽度 - 增加可读形式列宽度
            border = "+----------------+------------+---------------------------+--------------------------------+"
            title_width = len(border) - 2  # 减去两侧的"|"字符
            
            self.logger.info("\n" + border)
            self.logger.info("|{:^{}}|".format("设备详细标识符信息", title_width))
            self.logger.info(border)
            self.logger.info("| {:<15} | {:<10} | {:<25} | {:<30} |".format("IP地址", "类型", "标识符", "可读形式"))
            self.logger.info(border)
            
            for ip, identifiers in self.ip_to_identifiers.items():
                # 显示MAC地址
                if "mac" in identifiers:
                    self.logger.info("| {:<15} | {:<10} | {:<25} | {:<30} |".format(
                        ip, "MAC", identifiers["mac"], ""))
                
                # 显示客户端ID (标识符可能需要截断，但可读形式完整显示)
                if "client_id" in identifiers:
                    client_id = identifiers["client_id"]
                    if len(client_id) > 25:
                        client_id_display = client_id[:22] + "..."
                    else:
                        client_id_display = client_id
                    
                    # 解析可读形式并完整显示
                    readable_form = self.parse_client_id_readable(client_id) or ""
                        
                    self.logger.info("| {:<15} | {:<10} | {:<25} | {:<30} |".format(
                        "", "客户端ID", client_id_display, readable_form))
                
                # 显示序列号 - 保持不变
                if "sn" in identifiers and identifiers["sn"]:
                    self.logger.info("| {:<15} | {:<10} | {:<25} | {:<30} |".format(
                        "", "序列号", identifiers["sn"], ""))
                
                # 添加分隔线
                self.logger.info(border)

# ZTP管理器
class ZTPManager:
    def __init__(self, config):
        self.config = config
        self.logger = logger
        self.dhcp_server = SocketDHCPServer(config["dhcp_server"], logger) 
        
        # 显示配置信息
        self.logger.info(f"默认引导文件: {config['dhcp_server']['options']['67']}")
        self.logger.info(f"设备映射配置: {config['device_mapping']}")
        
        # 传递引导文件名和DHCP服务器引用到TFTP服务器配置
        tftp_config = config["tftp_server"].copy()
        tftp_config["bootfile"] = config["dhcp_server"]["options"]["67"]
        tftp_config["device_mapping"] = config["device_mapping"]
        self.logger.info(f"TFTP配置中的设备映射: {tftp_config['device_mapping']}")
        self.tftp_server = ZTPTftpServer(tftp_config, logger, self.dhcp_server)
        
        # 创建基本配置文件
        self.create_basic_configs()
        
    def create_basic_configs(self):
        """创建基本的配置文件目录"""
        tftp_root = self.config["tftp_server"]["root_dir"]
        os.makedirs(tftp_root, exist_ok=True)
        
        # 获取用户设置的引导文件名
        bootfile = self.config["dhcp_server"]["options"]["67"]
        self.logger.info(f"TFTP根目录: {tftp_root}")
        self.logger.info(f"引导文件名: {bootfile}")
        self.logger.info("注意: 请确保在TFTP根目录中手动创建所需的配置文件")
        
        # 检查用户指定的引导文件是否存在
        config_path = os.path.join(tftp_root, bootfile)
        if not os.path.exists(config_path):
            self.logger.warning(f"警告: 指定的引导文件 {bootfile} 不存在于TFTP根目录")
            self.logger.warning(f"请在以下位置手动创建配置文件: {config_path}")
        else:
            self.logger.info(f"已找到引导配置文件: {bootfile}")
    
    def start_services(self):
        """启动DHCP和TFTP服务"""
        self.logger.info("启动ZTP服务...")
        
        # 创建并启动TFTP服务器线程
        tftp_thread = threading.Thread(target=self.tftp_server.start)
        tftp_thread.daemon = True
        tftp_thread.start()
        
        # 给TFTP服务器一点时间启动
        time.sleep(1)
        
        # 启动DHCP服务器（在当前线程中运行）
        self.logger.info("启动DHCP服务器...")
        self.dhcp_server.listen()

    def stop_services(self):
        """停止所有服务"""
        # 停止TFTP服务器
        if hasattr(self, 'tftp_server') and self.tftp_server:
            try:
                self.logger.info("正在停止TFTP服务器...")
                # 添加状态检查，避免重复停止
                if hasattr(self.tftp_server, '_running') and self.tftp_server._running:
                    self.tftp_server.stop()
                else:
                    self.logger.info("TFTP服务器已经是停止状态")
            except Exception as e:
                self.logger.error(f"停止TFTP服务器出错: {str(e)}")
            finally:
                # 确保引用被清除
                self.tftp_server = None
        
        # 停止DHCP服务器
        if hasattr(self, 'dhcp_server') and self.dhcp_server:
            try:
                self.logger.info("正在停止DHCP服务器...")
                self.dhcp_server.stop()
                self.logger.info("DHCP服务器已停止")
            except Exception as e:
                self.logger.error(f"停止DHCP服务器出错: {str(e)}")
            finally:
                # 确保引用被清除
                self.dhcp_server = None

# 使用正确的路径:
# 1. 如果是打包后的EXE文件，使用EXE所在目录
# 2. 如果是直接运行的Python脚本，使用脚本所在目录
def get_app_path():
    if getattr(sys, 'frozen', False):
        # 如果是打包后的EXE
        return os.path.dirname(sys.executable)
    else:
        # 如果是直接运行的Python脚本
        return os.path.dirname(os.path.abspath(__file__))

def analyze_uploaded_file(filepath, logger):
    """分析设备上传的文件内容"""
    try:
        # 读取文件内容(限制大小防止内存溢出)
        with open(filepath, 'rb') as f:
            content = f.read(10240)  # 最多读取10KB
        
        # 尝试解码文本内容
        try:
            text = content.decode('utf-8', errors='replace')
            # 去掉多余空行方便显示
            text_lines = [line for line in text.split('\n') if line.strip()]
            if text_lines:
                logger.info("文件内容预览 (UTF-8):")
                for i, line in enumerate(text_lines[:10]):  # 只显示前10行
                    logger.info(f"  {i+1}: {line}")
                if len(text_lines) > 10:
                    logger.info(f"  ...共 {len(text_lines)} 行")
        except:
            # 如果不是文本文件，显示十六进制摘要
            logger.info("文件内容预览 (十六进制):")
            hex_preview = ' '.join(f"{b:02x}" for b in content[:50])
            logger.info(f"  {hex_preview}{'...' if len(content) > 50 else ''}")
        
        # 尝试识别文件类型
        if content.startswith(b'<?xml'):
            logger.info("文件类型: XML 文档")
        elif b'successful' in content:
            logger.info("文件类型: ZTP状态报告 (成功)")
        elif b'failure' in content or b'failed' in content:
            logger.info("文件类型: ZTP状态报告 (失败)")
        elif content.startswith((b'#!', b'system')):
            logger.info("文件类型: 配置脚本")
        else:
            # 简单的文件类型检测，不使用imghdr模块
            if content.startswith(b'\xff\xd8\xff'):
                logger.info("文件类型: JPEG图像")
            elif content.startswith(b'\x89PNG\r\n\x1a\n'):
                logger.info("文件类型: PNG图像")
            elif content.startswith(b'GIF87a') or content.startswith(b'GIF89a'):
                logger.info("文件类型: GIF图像")
            else:
                logger.info("文件类型: 未知格式")
                
    except Exception as e:
        logger.error(f"分析上传文件时出错: {str(e)}")

def normalize_mac_address(mac_input):
    """标准化不同格式的MAC地址为xx:xx:xx:xx:xx:xx格式"""
    # 去除所有分隔符和空格
    mac_clean = mac_input.replace(':', '').replace('-', '').replace('.', '').replace(' ', '')
    
    # 检查是否是有效的MAC地址（12个十六进制字符）
    if len(mac_clean) != 12 or not all(c in '0123456789abcdefABCDEF' for c in mac_clean):
        return None
    
    # 转换为标准格式 xx:xx:xx:xx:xx:xx
    return ':'.join(mac_clean[i:i+2].lower() for i in range(0, 12, 2))

def main():
    """主程序"""
    try:
        # 立即创建tftpboot文件夹（在程序开始处）
        app_dir = get_app_path()
        tftp_root = os.path.join(app_dir, "tftpboot")
        
        # 程序启动时的检测代码
        if not os.path.exists(tftp_root):
            print(f"\n重要提示: TFTP根目录不存在!")
            print(f"请手动创建文件夹: {tftp_root}")
            create_dir = input("是否现在创建此文件夹? (y/n): ")
            if create_dir.lower() == 'y':
                try:
                    os.makedirs(tftp_root, exist_ok=True)
                    print("文件夹创建成功!")
                except Exception as e:
                    print(f"创建失败: {str(e)}")
                    print("请以管理员权限运行程序或手动创建文件夹")
            else:
                print("警告: 程序可能无法正常工作!")
        
        # 验证文件夹是否存在
        if os.path.exists(tftp_root) and os.path.isdir(tftp_root):
            print(f"已确认TFTP根目录存在")
        else:
            print(f"警告: TFTP根目录不存在，程序可能无法正常工作")

        print("正在获取网络接口...")
        
        # 自动选择第一个非回环IP地址
        selected_ip = None
        
        # 基本方法获取IP
        try:
            hostname = socket.gethostname()
            host_info = socket.gethostbyname_ex(hostname)
            for ip in host_info[2]:
                if not ip.startswith("127."):
                    selected_ip = ip
                    break
        except:
            pass
            
        # 如果上面方法失败，使用简单方法尝试一次
        if not selected_ip:
            try:
                selected_ip = socket.gethostbyname(socket.gethostname())
                if selected_ip.startswith("127."):
                    # 如果只有回环地址，也使用它
                    selected_ip = socket.gethostbyname(socket.gethostname())
            except:
                pass
        
        # 如果无法自动检测到IP，使用默认IP
        if not selected_ip:
            selected_ip = "192.168.55.1"
            print(f"无法自动检测到有效的网络接口，使用默认IP: {selected_ip}")
        else:
            print(f"自动选择IP地址: {selected_ip}")
        
        # 更新配置
        DEFAULT_CONFIG["dhcp_server"]["server_ip"] = selected_ip
        DEFAULT_CONFIG["dhcp_server"]["gateway"] = selected_ip
        DEFAULT_CONFIG["dhcp_server"]["options"]["66"] = selected_ip
        DEFAULT_CONFIG["tftp_server"]["server_ip"] = selected_ip
        
        # 修改IP池范围，确保与所选接口在同一网段
        ip_parts = selected_ip.split('.')
        network_prefix = '.'.join(ip_parts[0:3])
        DEFAULT_CONFIG["dhcp_server"]["start_ip"] = f"{network_prefix}.100"
        DEFAULT_CONFIG["dhcp_server"]["end_ip"] = f"{network_prefix}.200"
        
        # 自定义DHCP参数
        print("\n--- DHCP配置参数 (直接回车使用默认值) ---")
        
        # 网关
        gateway = input(f"网关IP [{DEFAULT_CONFIG['dhcp_server']['gateway']}]: ").strip()
        if gateway:
            DEFAULT_CONFIG["dhcp_server"]["gateway"] = gateway
            
        # 子网掩码
        subnet = input(f"子网掩码 [{DEFAULT_CONFIG['dhcp_server']['subnet_mask']}]: ").strip()
        if subnet:
            DEFAULT_CONFIG["dhcp_server"]["subnet_mask"] = subnet
            
        # IP地址池
        start_ip = input(f"IP地址池起始地址 [{DEFAULT_CONFIG['dhcp_server']['start_ip']}]: ").strip()
        if start_ip:
            DEFAULT_CONFIG["dhcp_server"]["start_ip"] = start_ip
            
        end_ip = input(f"IP地址池结束地址 [{DEFAULT_CONFIG['dhcp_server']['end_ip']}]: ").strip()
        if end_ip:
            DEFAULT_CONFIG["dhcp_server"]["end_ip"] = end_ip
            
        # TFTP服务器地址
        tftp_ip = input(f"TFTP服务器地址 [{DEFAULT_CONFIG['dhcp_server']['options']['66']}]: ").strip()
        if tftp_ip:
            DEFAULT_CONFIG["dhcp_server"]["options"]["66"] = tftp_ip
        
        # 默认引导文件名不再询问，使用默认值
        print(f"默认引导文件名: {DEFAULT_CONFIG['dhcp_server']['options']['67']}")
        
        # 使用绝对路径
        DEFAULT_CONFIG["tftp_server"]["root_dir"] = tftp_root
        print(f"TFTP根目录: {tftp_root}")
        
        # 检查防火墙状态
        print("\n检查防火墙规则...")
        try:
            subprocess.run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=ZTP_DHCP'], 
                        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("防火墙规则已存在")
        except:
            print("正在添加防火墙规则...")
            try:
                subprocess.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule', 
                              'name=ZTP_DHCP', 'dir=in', 'action=allow', 
                              'protocol=UDP', 'localport=67,68,69'], check=False)
                print("防火墙规则添加成功")
            except:
                print("无法添加防火墙规则，可能需要手动设置")
        
        # 设备映射配置
        print("\n--- 设备映射配置 ---")
        print("通过设备映射，您可以为每个设备指定特定的配置文件")

        # 清空默认映射
        DEFAULT_CONFIG["device_mapping"] = {}

        # 此处添加一个全局默认配置文件选项
        default_config_file = input("输入默认配置文件名（当手工输入的配置文件不存在时默认使用该配置文件）[startup.cfg]: ").strip() or "startup.cfg"
        DEFAULT_CONFIG["dhcp_server"]["options"]["67"] = default_config_file
        print(f"默认配置文件已设置为: {default_config_file}")

        add_mapping = True
        while add_mapping:
            print("\n添加设备和配置文件的映射:")
            print("1. 根据设备客户端标识符(Client ID)进行映射")
            print("2. 根据设备MAC地址进行映射")
            print("3. 完成添加并启动ZTP服务")
            
            choice = input("选择 [3]: ") or "3"
            if choice == '3':
                break
                
            if choice in ['1', '2']:
                if choice == '1':  # 现在是客户端标识符
                    identifier = input("输入客户端标识符值: ")
                    identifier = f"client_id:{identifier}"
                    id_type = "客户端标识符"
                else:  # choice == '2' - 现在是MAC地址
                    identifier = input("输入MAC地址 (支持xx:xx:xx:xx:xx:xx或xxxx-xxxx-xxxx格式): ")
                    normalized_mac = normalize_mac_address(identifier)
                    if not normalized_mac:
                        print("警告: 输入的MAC地址格式无效，请使用正确的MAC地址格式")
                        continue
                    identifier = normalized_mac
                    id_type = "MAC地址"
                
                config_file = input("输入设备配置文件名: ")
                
                DEFAULT_CONFIG["device_mapping"][identifier] = {
                    "config_file": config_file
                }
                
                print(f"\n添加了{id_type}映射: {identifier} -> {config_file}")
        
        # 显示最终配置
        print("\n--- 最终DHCP配置 ---")
        print(f"服务器IP: {DEFAULT_CONFIG['dhcp_server']['server_ip']}")
        print(f"网关: {DEFAULT_CONFIG['dhcp_server']['gateway']}")
        print(f"子网掩码: {DEFAULT_CONFIG['dhcp_server']['subnet_mask']}")
        print(f"IP池范围: {DEFAULT_CONFIG['dhcp_server']['start_ip']} - {DEFAULT_CONFIG['dhcp_server']['end_ip']}")
        print(f"TFTP服务器: {DEFAULT_CONFIG['dhcp_server']['options']['66']}")
        
        # 显示所有设备映射
        if DEFAULT_CONFIG["device_mapping"]:
            print("\n--- 设备映射 ---")
            for identifier, info in DEFAULT_CONFIG["device_mapping"].items():
                print(f"{identifier} -> {info['config_file']}")
        else:
            print("\n未配置任何设备映射，将使用默认配置文件")
        
        print("\n启动ZTP服务...")
        ztp_manager = ZTPManager(DEFAULT_CONFIG)
        ztp_manager.start_services()
    
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"发生错误: {e}")
        input("按Enter键退出...")

if __name__ == "__main__":
    main()