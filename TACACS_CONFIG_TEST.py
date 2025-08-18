import os
import sys
import json
import time
import re

# 添加当前目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 导入自定义模块
import login_args
import check_device_output
import get_system_info
import write_log
import interface_config  # 引入interface_config模块用于复用功能

# 添加缓存接口信息的全局变量
cached_interfaces = {}

def extract_device_name(ssh):
    """从SSH提示符中提取设备名，优先使用<设备名>格式"""
    if not ssh:
        print("警告: SSH连接为空，无法提取设备名称，使用默认值'H3C'")
        return "H3C"
    
    try:
        prompt = ssh.find_prompt()
        print(f"正在从提示符提取设备名: '{prompt}'")
        
        # 优先从<设备名>格式提取 - H3C设备常用格式
        if '<' in prompt and '>' in prompt:
            try:
                device_name = prompt.split('<')[1].split('>')[0]
                print(f"成功从<设备名>格式提取到设备名: '{device_name}'")
                return device_name
            except Exception as e:
                print(f"从<设备名>格式提取设备名失败: {str(e)}")
        
        # 尝试从[设备名]格式提取 - 系统视图下的格式
        elif '[' in prompt and ']' in prompt:
            try:
                device_name = prompt.split('[')[1].split(']')[0]
                print(f"成功从[设备名]格式提取到设备名: '{device_name}'")
                return device_name
            except Exception as e:
                print(f"从[设备名]格式提取设备名失败: {str(e)}")
        
        # 尝试直接使用提示符作为设备名 - 去除特殊字符
        else:
            clean_prompt = prompt.strip('<>[]')
            if clean_prompt:
                print(f"未找到标准格式，尝试使用清理后的提示符: '{clean_prompt}'")
                if ':' in clean_prompt:
                    device_name = clean_prompt.split(':')[0]
                    print(f"从提示符中提取设备名: '{device_name}'")
                    return device_name
                return clean_prompt
        
        print(f"警告: 无法从提示符'{prompt}'提取设备名，使用默认值'H3C'")
        return "H3C"
    except Exception as e:
        print(f"提取设备名时出现意外错误: {str(e)}")
        return "H3C"

def get_system_info_for_log(ssh_connection, device_name):
    """获取用于日志记录的系统信息，直接返回版本信息字符串"""
    try:
        ssh_connection.clear_buffer()
        version_output = get_system_info.get_system_info(ssh_connection)
        cleaned_version_output = clean_system_info(version_output, device_name)
        return cleaned_version_output or "未能获取到版本信息"
    except Exception as e:
        return f"获取版本信息失败: {str(e)}"

def clean_system_info(system_info, device_name):
    """清理系统信息，移除多余的设备名称显示"""
    if isinstance(system_info, dict):
        cleaned_info = {}
        for key, value in system_info.items():
            if isinstance(value, str):
                cleaned_value = re.sub(r'\n*<[^>]+>\n*', '', value)
                cleaned_value = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned_value)
                cleaned_value = re.sub(r'display\s+version\n*', '', cleaned_value, flags=re.IGNORECASE)
                cleaned_value = re.sub(r'\n+', '\n', cleaned_value)
                cleaned_value = cleaned_value.strip()
                if cleaned_value:
                    cleaned_info[key] = cleaned_value
        return cleaned_info
    elif isinstance(system_info, str):
        cleaned_value = re.sub(r'\n*<[^>]+>\n*', '', system_info)
        cleaned_value = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned_value)
        cleaned_value = re.sub(r'display\s+version\n*', '', cleaned_value, flags=re.IGNORECASE)
        cleaned_value = re.sub(r'\n+', '\n', cleaned_value)
        return cleaned_value.strip()
    return system_info

def generate_tacacs_config(device_params):
    """生成TACACS配置命令列表"""
    
    # 获取配置参数，设置默认值
    scheme_name = device_params.get('scheme_name', 'tacacs')
    authen_server_ip = device_params.get('authen_server_ip', '192.168.1.100')
    author_server_ip = device_params.get('author_server_ip', authen_server_ip)  # 默认与认证服务器相同
    account_server_ip = device_params.get('account_server_ip', authen_server_ip)  # 默认与认证服务器相同
    domain_name = device_params.get('domain_name', 'tacacs')
    # 移除default_domain参数，直接使用domain_name
    server_password = device_params.get('server_password', 'password123')  # 默认服务器密码
    auth_password = device_params.get('auth_password', server_password)  # 默认与服务器密码相同
    author_password = device_params.get('author_password', server_password)  # 默认与服务器密码相同
    account_password = device_params.get('account_password', server_password)  # 默认与服务器密码相同
    
    config_commands = []
    
    # SSH和Telnet服务启用
    config_commands.append("ssh server enable")
    config_commands.append("telnet server enable")
    
    # HWTACACS方案配置
    config_commands.append(f"hwtacacs scheme {scheme_name}")
    config_commands.append(f"primary authentication {authen_server_ip} 49")
    config_commands.append(f"primary authorization {author_server_ip} 49")
    config_commands.append(f"primary accounting {account_server_ip} 49")
    config_commands.append(f"key authentication simple {auth_password}")
    config_commands.append(f"key authorization simple {author_password}")
    config_commands.append(f"key accounting simple {account_password}")
    config_commands.append("user-name-format without-domain")
    config_commands.append("quit")
    
    # 域配置
    config_commands.append(f"domain {domain_name}")
    config_commands.append(f"authentication login hwtacacs-scheme {scheme_name}")
    config_commands.append(f"authorization login hwtacacs-scheme {scheme_name}")
    config_commands.append(f"accounting login hwtacacs-scheme {scheme_name}")
    config_commands.append("quit")
    
    # 默认域配置
    config_commands.append(f"domain default enable {domain_name}")
    config_commands.append("role default-role enable network-operator")
    
    # VTY线路配置
    config_commands.append("line vty 0 63")
    config_commands.append("authentication-mode scheme")
    config_commands.append("quit")
    
    return config_commands

def ssh_system_view(device_params):
    """登录设备并执行system-view命令，配置TACACS参数"""
    
    ssh = login_args.run_script(device_params)
    
    if not ssh:
        error_message = f"无法登录设备 {device_params.get('hostip', 'unknown')}"
        log_path = write_log.write_log("Failed", [], {}, error_message)
        if log_path:
            print(f"\n日志已保存至: {log_path}")
        return "Failed", None, [], error_message, {}
    
    executed_commands = []
    
    # 获取设备提示符并提取设备名
    try:
        prompt = ssh.find_prompt()
        print(f"登录成功，原始设备提示符: '{prompt}'")
        device_name = extract_device_name(ssh)
        print(f"最终使用的设备名称: '{device_name}'")
        device_params['device_name'] = device_name
    except Exception as e:
        print(f"获取设备名称时出错: {str(e)}")
        device_name = "config"
        device_params['device_name'] = device_name

    try:
        # 先获取当前的提示符
        prompt = ssh.find_prompt()
        
        # 步骤1: 先执行screen-length disable命令禁用屏幕分页
        print(f"{prompt}screen-length disable")
        
        # 步骤2: 获取系统信息 (在进入系统视图前)
        system_info = get_system_info_for_log(ssh, device_name)
        
        # 步骤3: 执行system-view命令进入系统视图
        print(f"{prompt}system-view")
        output = ssh.send_command(
            "system-view",
            strip_prompt=True,
            strip_command=True,
            expect_string=r"[\[\]]"
        )
        print(output)
        executed_commands.append({
            "command": "system-view", 
            "output": f"{prompt}system-view{'' if output.strip() == '' else ' '}{output.strip()}"
        })
        
        # 检查命令输出
        status = check_device_output.check_device_output(output)
        if status == "Failed":
            error_message = f"执行命令 'system-view' 失败，设备返回了错误信息"
            print(f"\n错误: {error_message}")
            
            # 返回已获取的系统信息和已执行的命令
            system_info_dict = {device_name: system_info}
            
            if ssh:
                ssh.disconnect()
            return "Failed", None, executed_commands, error_message, system_info_dict
        
        # 生成TACACS配置命令
        print("\n配置TACACS...")
        tacacs_commands = generate_tacacs_config(device_params)
        
        # 执行TACACS配置命令
        for command in tacacs_commands:
            # 获取当前提示符
            current_prompt = ssh.find_prompt()
            
            # 打印命令
            print(f"{current_prompt}{command}")
            
            # 执行命令
            output = ssh.send_command(
                command,
                strip_prompt=True,
                strip_command=True,
                expect_string=r"]|\[|\>",
                delay_factor=0.2
            )
            
            # 打印输出
            print(output, end='')
            
            # 先记录命令执行结果（无论成功还是失败）
            executed_commands.append({
                "command": command, 
                "output": f"{current_prompt}{command}{'' if output.strip() == '' else ' '}{output.strip()}"
            })
            
            # 添加错误检查
            status = check_device_output.check_device_output(output)
            if status == "Failed":
                error_message = f"执行命令 '{command}' 失败，设备返回了错误信息"
                print(f"\n错误: {error_message}")
                
                # 返回已获取的系统信息和已执行的命令（包含失败的命令）
                system_info_dict = {device_name: system_info}
                
                if ssh:
                    ssh.disconnect()
                return "Failed", None, executed_commands, error_message, system_info_dict
            
            # 特殊处理quit命令
            if command.lower() == "quit":
                time.sleep(0.1)
                new_prompt = ssh.find_prompt()
                print(f"{new_prompt}", end='')
        
        # 返回system_info作为一个字典，键为设备名
        system_info_dict = {device_name: system_info}
        return "succeed", ssh, executed_commands, "", system_info_dict
        
    except Exception as e:
        print(f"\n配置执行失败：{str(e)}")
        
        # 返回已获取的系统信息和已执行的命令
        if 'system_info' in locals():
            system_info_dict = {device_name: system_info}
        else:
            system_info_dict = {}
        
        if ssh:
            ssh.disconnect()
        return "Failed", None, executed_commands, str(e), system_info_dict

def config_single_device_tacacs(device_params):
    """配置单台设备的TACACS功能"""
    
    # 执行TACACS配置
    status, ssh_conn, executed_commands, error_message, device_system_info = ssh_system_view(device_params)
    
    if status == "Failed":
        # 记录失败日志（错误信息已在ssh_system_view中输出，此处不重复输出）
        write_log.write_log("Failed", executed_commands, device_system_info, error_message)
        return False
    
    try:
        device_name = device_params.get('device_name', 'config')
        print(f"\n{device_name} 配置完成")
        
        # 记录成功日志
        write_log.write_log("succeed", executed_commands, device_system_info)
        return True
        
    except Exception as e:
        error_msg = f"配置过程中发生异常: {str(e)}"
        print(f"\n错误: {error_msg}")
        
        # 记录异常日志
        write_log.write_log("Failed", executed_commands, device_system_info, error_msg)
        return False
    finally:
        # 确保关闭SSH连接
        if ssh_conn:
            ssh_conn.disconnect()

def config_multiple_devices_tacacs(base_params, hostips):
    """配置多台设备的TACACS功能"""
    
    success_count = 0
    total_count = len(hostips)
    
    print(f"\n开始配置 {total_count} 台设备的TACACS功能...")
    
    for i, hostip in enumerate(hostips, 1):
        print(f"\n=== 正在配置第 {i}/{total_count} 台设备: {hostip} ===")
        
        # 为每台设备创建独立的参数字典
        device_params = base_params.copy()
        device_params['hostip'] = hostip
        
        if config_single_device_tacacs(device_params):
            success_count += 1
            print(f"设备 {hostip} 配置成功")
        else:
            print(f"设备 {hostip} 配置失败")
    
    print(f"\n=== 配置完成: {success_count}/{total_count} 台设备配置成功 ===")
    return success_count == total_count

def main():
    """主函数"""
    
    if len(sys.argv) != 2:
        print("用法: python TACACS_CONFIG_TEST.py '<JSON参数>'")
        print("\n参数说明:")
        print("必需参数:")
        print("  hostip: 设备IP地址 (单设备) 或 逗号分隔的IP列表 (多设备)")
        print("  username: 登录用户名")
        print("  password: 登录密码")
        print("  authen_server_ip: 认证服务器IP")
        print("\n可选参数:")
        print("  scheme_name: TACACS方案名称 (默认: tacacs)")
        print("  author_server_ip: 授权服务器IP (默认: 与认证服务器相同)")
        print("  account_server_ip: 计费服务器IP (默认: 与认证服务器相同)")
        print("  domain_name: 域名 (用于创建TACACS域和设置默认域，默认: tacacs)")
        print("  auth_password: 认证密码 (默认: password123)")
        print("  author_password: 授权密码 (默认: 与认证密码相同)")
        print("  account_password: 计费密码 (默认: 与认证密码相同)")
        print("  server_password: 服务器密码 (将覆盖所有认证/授权/计费密码的默认值)")
        print("\n注意: domain_name参数同时用于:")
        print("  - 创建域: domain {domain_name}")
        print("  - 设置默认域: domain default enable {domain_name}")
        print("\n单设备配置示例:")
        print('python TACACS_CONFIG_TEST.py \'{"hostip":"192.168.1.1","username":"admin","password":"admin","authen_server_ip":"192.168.1.100","scheme_name":"tacacs_scheme","domain_name":"tacacs_domain","server_password":"password123"}\'')
        print("\n多设备配置示例:")
        print('python TACACS_CONFIG_TEST.py \'{"hostip":"192.168.1.1,192.168.1.2,192.168.1.3","username":"admin","password":"admin","authen_server_ip":"192.168.1.100","domain_name":"company_tacacs","server_password":"password123"}\'')
        sys.exit(1)

    try:
        # 解析JSON参数
        json_str = sys.argv[1]
        params = json.loads(json_str)

        # 解析参数后立即记录Running状态的日志       
        write_log.write_log("Running", {}, {})
        
        # 检查必要参数
        required_params = ['hostip', 'username', 'password', 'authen_server_ip']
        for param in required_params:
            if not params.get(param):
                print(f"错误: 缺少必需参数 {param}")
                sys.exit(1)
        
        # 解析hostip参数，检查是否为多设备配置
        hostip_param = params.get('hostip', '')
        hostips = [ip.strip() for ip in hostip_param.split(',') if ip.strip()]
        
        if len(hostips) == 0:
            print("错误: hostip参数不能为空")
            sys.exit(1)
        elif len(hostips) == 1:
            # 单设备配置模式
            print(f"\n检测到单设备配置模式: {hostips[0]}")
            success = config_single_device_tacacs(params)
            sys.exit(0 if success else 1)
        else:
            # 多设备配置模式
            print(f"\n检测到多设备配置模式: {len(hostips)} 台设备")
            print(f"设备列表: {', '.join(hostips)}")
            
            # 创建基础参数字典（排除hostip）
            base_params = {k: v for k, v in params.items() if k != 'hostip'}
            
            # 执行多设备配置
            success = config_multiple_devices_tacacs(base_params, hostips)
            sys.exit(0 if success else 1)
            
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {str(e)}")
        print("请确保参数格式正确")
        sys.exit(1)
    except Exception as e:
        print(f"程序执行出错: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
