import time
import json
import os
import sys
import re
from netmiko import ConnectHandler
import write_log

def check_ip(hostip):
    """检查 IP 地址是否合法"""
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', hostip):
        parts = hostip.split('.')
        return all(0 <= int(part) <= 255 for part in parts)
    return False

def login(hostip, username, password):
    """使用 Telnet 登录 H3C 设备，返回 (连接对象/None, 失败原因)"""
    try:
        device = {
            'device_type': 'hp_comware_telnet',  # Telnet 类型
            'host': hostip,
            'username': username,
            'password': password,
            'timeout': 8,              # Telnet 适当放宽
            'session_timeout': 15,
            'blocking_timeout': 5,
            'conn_timeout': 5,
            'global_delay_factor': 0.5,
            'fast_cli': True,
            'session_log': None,
        }
        conn = ConnectHandler(**device)
        return conn, None
    except Exception as e:
        error_msg = str(e)
        failure_reason = "未知错误"
        if "TCP connection to device failed" in error_msg or "Telnet connection failed" in error_msg:
            failure_reason = "Telnet连接失败/无法到达设备"
        elif "Authentication failed" in error_msg or "invalid username" in error_msg.lower():
            failure_reason = "用户名或密码错误"
        elif "timed out" in error_msg.lower():
            failure_reason = "连接或响应超时"
        elif "not a valid IP" in error_msg.lower():
            failure_reason = "IP格式无效"
        print("\n" + "*" * 50)
        print(f"Telnet 登录失败: {error_msg}")
        print("失败原因: ", failure_reason)
        print("*" * 50)
        return None, failure_reason

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

def read_login_args():
    """
    从配置文件或环境变量读取登录信息
    返回设备信息列表，格式：[{'hostip': '...', 'username': '...', 'password': '...'}]
    """
    # 方法1: 尝试从device_config.json文件读取
    config_files = ['device_config.json', 'devices.json', 'login_config.json']
    
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    # 支持多种格式
                    if 'devices' in config_data:
                        return config_data['devices']
                    elif isinstance(config_data, list):
                        return config_data
                    else:
                        # 单个设备格式
                        return [config_data]
            except Exception as e:
                print(f"读取配置文件 {config_file} 失败: {e}")
                continue
    
    # 方法2: 尝试从环境变量读取
    import os
    device_ip = os.environ.get('DEVICE_IP')
    device_user = os.environ.get('DEVICE_USERNAME')
    device_pass = os.environ.get('DEVICE_PASSWORD')
    
    if device_ip and device_user and device_pass:
        return [{
            'hostip': device_ip,
            'username': device_user,
            'password': device_pass
        }]
    
    # 方法3: 返回默认测试设备（如果存在）
    default_devices = [
        {
            'hostip': '192.168.56.10',
            'username': 'admin', 
            'password': 'h3c.com123'
        }
    ]
    
    print("警告: 未找到设备配置文件，使用默认测试设备")
    return default_devices

def main(hostip, username, password):
    net_connect = login(hostip, username, password)
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
    """返回 (连接对象/None, 失败原因) - Telnet 方式"""
    required_params = ['hostip', 'username', 'password']
    if not all(param in device_params for param in required_params):
        return None, "缺少必要参数"
    if not check_ip(device_params['hostip']):
        return None, "IP格式错误"
    return login(device_params['hostip'], device_params['username'], device_params['password'])

def _print_usage():
    print("用法: python TELNET_TEST.py '{\"hostip\":\"192.168.30.7\",\"username\":\"admin\",\"password\":\"admin\"}'")
    print("说明: 仅接受一个 JSON 字符串参数; 仅支持单一 hostip (Telnet)。")


def _normalize_json(raw: str) -> str:
    """尝试把宽松格式转成合法 JSON
    支持情况:
    1. 单引号 -> 双引号
    2. 未带引号的键名 hostip: -> "hostip":
    3. 去掉首尾多余空白
    """
    txt = raw.strip()
    # 如果是文件路径且存在，则读取文件内容作为 JSON
    if os.path.exists(txt) and os.path.isfile(txt):
        try:
            with open(txt, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            pass
    # 将单引号替换成双引号（不处理已经在双引号内部的复杂情形，足够应对当前场景）
    if "'" in txt and '"' not in txt:
        txt = txt.replace("'", '"')
    # 给未加引号的键名补引号  hostip: -> "hostip":
    # 仅处理 a-zA-Z0-9_ 开头的简单键名
    def repl_key(m):
        return f'"{m.group(1)}":'
    txt = re.sub(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*:', repl_key, txt)
    return txt


def _parse_single_arg():
    if len(sys.argv) != 2 or sys.argv[1] in ('-h', '--help', 'help'):  # 只接受一个自定义参数
        _print_usage()
        sys.exit(1)
    raw = sys.argv[1]
    norm = _normalize_json(raw)
    try:
        data = json.loads(norm)
    except json.JSONDecodeError as e:
        print("提供的参数不是有效JSON: ", e)
        print("原始内容: ", raw)
        _print_usage()
        sys.exit(2)
    # 基本字段校验
    for field in ("hostip", "username", "password"):
        if field not in data:
            print(f"缺少必需字段: {field}")
            _print_usage()
            sys.exit(3)
    return data


if __name__ == "__main__":
    params = _parse_single_arg()
    # 写入 Running 日志
    write_log.write_log(
        "Running",
        commands=None,
        system_info=None,
        file_suffix="telnet_test",
        error_message=None
    )
    ip = params['hostip'].strip()
    username = params['username']
    password = params['password']
    if not ip:
        print("未提供 hostip")
        write_log.write_log(
            "Failed",
            commands={},
            system_info={},
            file_suffix="telnet_test",
            error_message="未提供 hostip"
        )
        sys.exit(4)
    if ',' in ip:
        print("当前版本仅支持单一设备，请勿使用逗号分隔多个IP")
        write_log.write_log(
            "Failed",
            commands={},
            system_info={},
            file_suffix="telnet_test",
            error_message="检测到多个IP，当前仅支持单设备"
        )
        sys.exit(4)
    print(f"\n==== 尝试 Telnet 登录设备 {ip} ====")
    if not check_ip(ip):
        print(f"IP 格式非法: {ip}")
        write_log.write_log(
            "Failed",
            commands={"login_result": "failed"},
            system_info={},
            file_suffix="telnet_test",
            error_message="IP 格式非法"
        )
        sys.exit(5)
    conn, failure_reason = run_script({'hostip': ip, 'username': username, 'password': password})
    if conn:
        print("Telnet 登录成功")
        try:
            conn.disconnect()
        except Exception:
            pass
        write_log.write_log(
            "succeed",
            commands={"login_result": "success"},
            system_info={},
            file_suffix="telnet_test",
            error_message=None
        )
        print("\n========== Telnet 登录结果 ==========")
        print("结果: success")
        sys.exit(0)
    else:
        print("Telnet 登录失败")
        if not failure_reason:
            failure_reason = "未知原因"
        write_log.write_log(
            "Failed",
            commands={"login_result": "failed"},
            system_info={},
            file_suffix="telnet_test",
            error_message=failure_reason
        )
        print("\n========== Telnet 登录结果 ==========")
        print("结果: failed")
        print("原因: ", failure_reason)
        sys.exit(5)
