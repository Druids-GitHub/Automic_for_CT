import socket
import time
import json

class SPT:
    def __init__(self, ip='1.1.1.1', port=5025, timeout=10):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.session_id = None
        self.devices = {}  # 存储创建的设备信息
        self.connect()

    def connect(self):
        """Connect to the SPT device."""
        try:
            self.socket = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            self.socket.settimeout(self.timeout)
            print(f"Connected to SPT at {self.ip}:{self.port}")
            
            # 获取设备信息
            device_info = self.send_command('*IDN?')
            if device_info:
                print(f"Device Info: {device_info}")
                
        except socket.error as e:
            print(f"Failed to connect to SPT: {e}")
            self.socket = None

    def send_command(self, command):
        """Send a command to the SPT device."""
        if self.socket is None:
            print("Socket is not connected.")
            return None
        try:
            print(f"Sending command: {command}")
            self.socket.sendall((command + '\n').encode('utf-8'))
            time.sleep(0.5)  # 增加等待时间
            
            # 接收响应
            response = ""
            while True:
                try:
                    data = self.socket.recv(1024).decode('utf-8')
                    if not data:
                        break
                    response += data
                    if '\n' in data:  # 响应结束标志
                        break
                except socket.timeout:
                    break
                    
            return response.strip()
        except socket.error as e:
            print(f"Error sending command: {e}")
            return None

    def create_session(self, session_name="TestSession"):
        """创建测试会话"""
        command = f"sth::test_session_id -session_name {session_name}"
        response = self.send_command(command)
        if response and "session_id" in response:
            # 解析session_id
            self.session_id = response.split("session_id")[1].strip()
            print(f"Session created: {self.session_id}")
            return True
        return False

    def reserve_ports(self, port_list):
        """预留端口"""
        ports = " ".join(port_list)
        command = f"sth::test_config -action reserve_ports -port_list {ports}"
        response = self.send_command(command)
        print(f"Reserve ports response: {response}")
        return response

    def create_device(self, port, device_type="router", **kwargs):
        """创建设备"""
        # 基本参数
        params = {
            "mode": "config",
            "port_handle": port,
            "device_type": device_type,
        }
        
        # 添加其他参数
        params.update(kwargs)
        
        # 构建命令
        param_str = " ".join([f"-{k} {v}" for k, v in params.items()])
        command = f"sth::emulation_device_config {param_str}"
        
        response = self.send_command(command)
        
        if response and "device_handle" in response:
            # 解析device_handle
            device_handle = response.split("device_handle")[1].strip().split()[0]
            self.devices[device_handle] = {
                "port": port,
                "type": device_type,
                "handle": device_handle
            }
            print(f"Device created: {device_handle}")
            return device_handle
        return None

    def configure_interface(self, device_handle, **kwargs):
        """配置接口"""
        params = {
            "mode": "config",
            "device_handle": device_handle,
        }
        params.update(kwargs)
        
        param_str = " ".join([f"-{k} {v}" for k, v in params.items()])
        command = f"sth::emulation_device_config {param_str}"
        
        response = self.send_command(command)
        print(f"Interface configuration response: {response}")
        return response

    def create_bgp_router(self, port, local_as, router_id, **kwargs):
        """创建BGP路由器"""
        params = {
            "mode": "config",
            "port_handle": port,
            "local_as": local_as,
            "router_id": router_id,
        }
        params.update(kwargs)
        
        param_str = " ".join([f"-{k} {v}" for k, v in params.items()])
        command = f"sth::emulation_bgp_config {param_str}"
        
        response = self.send_command(command)
        if response and "bgp_handle" in response:
            bgp_handle = response.split("bgp_handle")[1].strip().split()[0]
            print(f"BGP router created: {bgp_handle}")
            return bgp_handle
        return None

    def create_traffic_stream(self, src_port, dst_port, **kwargs):
        """创建流量流"""
        params = {
            "mode": "create",
            "port_handle": src_port,
            "transmit_mode": "continuous",
        }
        params.update(kwargs)
        
        param_str = " ".join([f"-{k} {v}" for k, v in params.items()])
        command = f"sth::traffic_config {param_str}"
        
        response = self.send_command(command)
        if response and "stream_id" in response:
            stream_id = response.split("stream_id")[1].strip().split()[0]
            print(f"Traffic stream created: {stream_id}")
            return stream_id
        return None

    def start_traffic(self, port_handle="all"):
        """启动流量"""
        command = f"sth::traffic_control -action run -port_handle {port_handle}"
        response = self.send_command(command)
        print(f"Start traffic response: {response}")
        return response

    def stop_traffic(self, port_handle="all"):
        """停止流量"""
        command = f"sth::traffic_control -action stop -port_handle {port_handle}"
        response = self.send_command(command)
        print(f"Stop traffic response: {response}")
        return response

    def get_traffic_stats(self, port_handle):
        """获取流量统计"""
        command = f"sth::traffic_stats -port_handle {port_handle} -mode stream"
        response = self.send_command(command)
        print(f"Traffic stats: {response}")
        return response

    def start_protocol(self, handle):
        """启动协议"""
        command = f"sth::emulation_bgp_control -handle {handle} -mode start"
        response = self.send_command(command)
        print(f"Start protocol response: {response}")
        return response

    def stop_protocol(self, handle):
        """停止协议"""
        command = f"sth::emulation_bgp_control -handle {handle} -mode stop"
        response = self.send_command(command)
        print(f"Stop protocol response: {response}")
        return response

    def cleanup(self):
        """清理配置"""
        command = "sth::cleanup_session"
        response = self.send_command(command)
        print(f"Cleanup response: {response}")
        return response

    def close(self):
        """Close the connection to the SPT device."""
        if self.socket:
            self.socket.close()
            print("Connection to SPT closed.")
            self.socket = None

    def __del__(self):
        """Ensure the connection is closed when the object is deleted."""
        self.close()

# 使用示例
if __name__ == "__main__":
    # 连接思博伦测试仪
    spt = SPT(ip='192.168.1.100', port=5025)
    
    try:
        # 创建测试会话
        spt.create_session("BGP_Test_Session")
        
        # 预留端口
        ports = ["1/1", "1/2"]
        spt.reserve_ports(ports)
        
        # 创建BGP路由器设备
        bgp_handle1 = spt.create_bgp_router(
            port="1/1",
            local_as="65001",
            router_id="192.168.1.1",
            neighbor_ip="192.168.1.2",
            remote_as="65002"
        )
        
        bgp_handle2 = spt.create_bgp_router(
            port="1/2", 
            local_as="65002",
            router_id="192.168.1.2",
            neighbor_ip="192.168.1.1",
            remote_as="65001"
        )
        
        # 启动BGP协议
        if bgp_handle1:
            spt.start_protocol(bgp_handle1)
        if bgp_handle2:
            spt.start_protocol(bgp_handle2)
        
        # 等待协议建立
        time.sleep(10)
        
        # 创建流量流
        stream_id = spt.create_traffic_stream(
            src_port="1/1",
            dst_port="1/2",
            rate_pps="1000",
            frame_size="64"
        )
        
        # 启动流量
        spt.start_traffic()
        
        # 运行流量10秒
        time.sleep(10)
        
        # 获取统计信息
        spt.get_traffic_stats("1/1")
        spt.get_traffic_stats("1/2")
        
        # 停止流量
        spt.stop_traffic()
        
        # 停止协议
        if bgp_handle1:
            spt.stop_protocol(bgp_handle1)
        if bgp_handle2:
            spt.stop_protocol(bgp_handle2)
            
    finally:
        # 清理并关闭连接
        spt.cleanup()
        spt.close()
