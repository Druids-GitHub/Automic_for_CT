import argparse
import getpass
import time
from netmiko import ConnectHandler
import re

def check_ip(hostip):
    """检查 IP 地址是否合法"""
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', hostip):
        parts = hostip.split('.')
        return all(0 <= int(part) <= 255 for part in parts)
    return False

def login(hostip, username, password):
    """登录 H3C 设备"""
    try:
        # 创建正确的设备字典 - 进一步优化性能
        device = {
            'device_type': 'hp_comware',
            'host': hostip,  # 使用host而不是hostip
            'username': username,
            'password': password,
            'timeout': 5,    # 进一步减少连接超时
            'session_timeout': 10,   # 进一步减少会话超时
            'keepalive': 5,   # 进一步减少保持连接间隔
            'blocking_timeout': 3,    # 进一步减少阻塞操作超时
            'conn_timeout': 3,    # 进一步减少连接超时
            'read_timeout_override': 5,   # 进一步减少读取超时覆盖
            'global_delay_factor': 0.3,   # 进一步减少全局延迟因子
            'fast_cli': True,  # 启用快速CLI模式
            'session_log': None,  # 禁用会话日志提升速度
        }
        
        # 调用ConnectHandler
        return ConnectHandler(**device)
    except Exception as e:
        error_msg = str(e)
        print("\n" + "*" * 50)
        print(f"登录失败: {error_msg}")
        
        # 根据错误类型提供更详细的帮助信息
        if "TCP connection to device failed" in error_msg:
            print("\n可能的原因:")
            print("1. 设备IP地址 {} 不正确或无法访问".format(hostip))
            print("2. 设备未开机或网络接口未激活")
            print("3. 网络连接问题（检查网络电缆、交换机、路由器等）")
            print("4. 防火墙阻止了SSH连接（默认端口22）")
            print("5. 设备上的SSH服务未启用或配置错误")
            print("\n建议操作:")
            print("- 使用ping测试设备连通性: ping {}".format(hostip))
            print("- 检查设备物理连接和网络配置")
            print("- 尝试使用telnet连接（如已启用）: telnet {} 23".format(hostip))
        elif "Authentication failed" in error_msg or "Authentication failure" in error_msg:
            print("\n可能的原因:")
            print("1. 用户名 {} 不存在或输入错误".format(username))
            print("2. 密码输入错误")
            print("3. 设备上的用户认证方式可能不是密码认证")
            print("\n建议操作:")
            print("- 检查用户名和密码是否正确")
            print("- 尝试使用其他已知的用户名和密码")
            print("- 通过控制台访问设备重置认证信息")
        elif "timed out" in error_msg.lower():
            print("\n可能的原因:")
            print("1. 设备响应超时（网络延迟过高）")
            print("2. 设备过载或处理能力不足")
            print("3. 防火墙或ACL正在限制连接速度")
            print("\n建议操作:")
            print("- 增加超时设置（当前为10秒）")
            print("- 检查网络质量和延迟")
        print("*" * 50)
        return None

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
    """
    主入口函数，供其他脚本调用
    """
    # 验证必需的参数
    required_params = ['hostip', 'username', 'password']
    if not all(param in device_params for param in required_params):
        print("缺少必需的参数，需要 'hostip'、'username' 和 'password'")
        return None
    
    # 检查 IP 地址格式
    if not check_ip(device_params['hostip']):
        print("IP 地址格式错误")
        return None
    
    try:
        # 关键修改：创建新的设备字典，使用host而不是hostip
        device = {
            'device_type': 'hp_comware',
            'host': device_params['hostip'],  # 这里是关键修改
            'username': device_params['username'],
            'password': device_params['password'],
            'timeout': 15,  # 减少超时时间
            'session_timeout': 30,  # 减少会话超时
            'keepalive': 15,  # 减少保持连接间隔
            'blocking_timeout': 10,  # 减少阻塞操作超时
            'conn_timeout': 8,  # 减少连接超时
            'read_timeout_override': 15,  # 减少读取超时覆盖
            'global_delay_factor': 1,  # 减少全局延迟因子
        }
        
        # 传递正确参数名称的字典
        net_connect = ConnectHandler(**device)
        return net_connect
    except Exception as e:
        error_msg = str(e)
        if not "登录失败" in error_msg:  # 避免重复打印错误信息
            print("\n" + "*" * 50)
            print(f"脚本登录失败: {error_msg}")
            
            # 根据错误类型提供更详细的帮助信息
            if "TCP connection to device failed" in error_msg:
                print("\n可能的原因和建议:")
                print(f"1. 设备 {device_params['hostip']} 不在线或无法访问")
                print("2. 请检查网络连接和设备状态")
                print("3. 检查防火墙设置是否允许SSH连接")
                print(f"4. 尝试ping测试: ping {device_params['hostip']}")
            print("*" * 50)
        return None

if __name__ == "__main__":
    # 这部分代码只在直接运行login_args.py时执行
    import argparse
    parser = argparse.ArgumentParser(description='登录 H3C 设备')
    parser.add_argument('-i', '--hostip', required=True, help='设备IP地址')
    parser.add_argument('-u', '--username', required=True, help='登录用户名')
    parser.add_argument('-p', '--password', required=True, help='登录密码')
    args = parser.parse_args()
    
    # 将命令行参数转换为字典格式
    device_params = {
        'hostip': args.hostip,
        'username': args.username,
        'password': args.password
    }
    
    net_connect = run_script(device_params)
    if net_connect:
        print("登录成功")
        net_connect.disconnect()
    else:
        print("登录失败")
