import argparse
import getpass
import time
from netmiko import ConnectHandler
import re

def check_ip(ip):
    """检查 IP 地址是否合法"""
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
        parts = ip.split('.')
        return all(0 <= int(part) <= 255 for part in parts)
    return False

def login(ip, username, password):
    """登录 H3C 设备"""
    device = {
        'device_type': 'hp_comware',
        'ip': ip,
        'username': username,
        'password': password,
        'timeout': 10
    }
    return ConnectHandler(**device)

def silent_input(net_connect):
    """静默输入"""
    try:
        command = input().strip()
        if command.lower() == 'exit':
            return command
        net_connect.write_channel(command + '\n')
        time.sleep(0.2)
        return command
    except KeyboardInterrupt:
        return 'exit'

def main(ip, username, password):
    net_connect = login(ip, username, password)
    # 连接成功后清空缓冲区
    net_connect.clear_buffer()
    
    # 发送回车获取初始提示符
    net_connect.write_channel('\n')
    time.sleep(1)  # 给设备足够的响应时间
    
    # 持续读取直到获取完整的banner和提示符
    output = ''
    max_attempts = 10  # 最大尝试次数
    attempts = 0
    
    while attempts < max_attempts:
        new_data = net_connect.read_channel()
        if new_data:
            output += new_data
            if '>' in output or ']' in output:  # 检测到提示符
                break
        else:
            attempts += 1
            time.sleep(0.2)
    
    if output:
        print(output, end='', flush=True)
    
    while True:
        command = silent_input(net_connect)  # 传入 net_connect 对象
        if command.lower() == 'exit':
            break
        
        # 清除输出缓冲区
        net_connect.clear_buffer()
        
        # 发送命令
        net_connect.write_channel(command + '\n')
        time.sleep(0.2)
        
        # 读取设备回显
        output = ''
        attempts = 0
        while attempts < max_attempts:
            new_data = net_connect.read_channel()
            if new_data:
                # 如果新数据以命令开头，则只跳过命令本身
                if new_data.startswith(command):
                    new_data = new_data[len(command):]
                output += new_data
                if '>' in new_data or ']' in new_data:  # 检测到提示符
                    break
            else:
                attempts += 1
                time.sleep(0.2)

        if output:
            print(output, end='', flush=True)

def run_script(device_params):
    """
    主入口函数，供其他脚本调用
    
    Args:
        device_params (dict): 包含设备连接参数的字典
            {
                "ip": "设备IP地址",
                "username": "登录用户名",
                "password": "登录密码"
            }
    
    Returns:
        netmiko.ConnectHandler or None: 如果登录成功返回连接对象，否则返回 None
    """
    # 验证必需的参数
    required_params = ['ip', 'username', 'password']
    if not all(param in device_params for param in required_params):
        print("缺少必需的参数，需要 'ip'、'username' 和 'password'")
        return None
    
    # 检查 IP 地址格式
    if not check_ip(device_params['ip']):
        print("IP 地址格式错误")
        return None
    
    try:
        device = {
            'device_type': 'hp_comware',
            'ip': device_params['ip'],
            'username': device_params['username'],
            'password': device_params['password'],
        }
        net_connect = ConnectHandler(**device)
        return net_connect
    except Exception as e:
        print(f"登录失败: {str(e)}")
        return None

if __name__ == "__main__":
    # 这部分代码只在直接运行login_args.py时执行
    import argparse
    parser = argparse.ArgumentParser(description='登录 H3C 设备')
    parser.add_argument('-i', '--ip', required=True, help='设备IP地址')
    parser.add_argument('-u', '--username', required=True, help='登录用户名')
    parser.add_argument('-p', '--password', required=True, help='登录密码')
    args = parser.parse_args()
    
    # 将命令行参数转换为字典格式
    device_params = {
        'ip': args.ip,
        'username': args.username,
        'password': args.password
    }
    
    net_connect = run_script(device_params)
    if net_connect:
        print("登录成功")
        net_connect.disconnect()
    else:
        print("登录失败")
