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


# 添加缓存接口信息的全局变量
cached_interfaces = {}

def simple_clean_prompt(prompt):
    """简单清理提示符，避免重复"""
    if not prompt:
        return ""
    
    import re
    
    # 清理基本的换行和空白
    cleaned = prompt.strip()
    
    # 移除重复的提示符模式
    # 处理 <A><A> 重复
    cleaned = re.sub(r'(<[^>]+>)\1+', r'\1', cleaned)
    # 处理 [A][A] 重复  
    cleaned = re.sub(r'(\[[^\]]+\])\1+', r'\1', cleaned)
    
    # 如果仍有混合模式，取最后一个
    bracket_match = re.findall(r'\[[^\]]+\]', cleaned)
    angle_match = re.findall(r'<[^>]+>', cleaned)
    
    if bracket_match:
        return bracket_match[-1]
    elif angle_match:
        return angle_match[-1]
    else:
        return cleaned

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

def generate_telemetry_config(device_params):
    """生成Telemetry配置命令列表"""
    
    # 获取配置参数，设置默认值
    sensor_group_name = device_params.get('sensor_group_name', 'group1')
    destination_group_name = device_params.get('destination_group_name', 'group1')
    subscription_name = device_params.get('subscription_name', 'sub1')
    collector_ip = device_params.get('collector_ip', '192.168.100.1')
    collector_port = device_params.get('collector_port', '50051')
    sample_interval = device_params.get('sample_interval', '1')
    
    # 默认的传感器路径列表
    default_sensor_paths = [
        'device/transceivers',
        'diagnostic/cpuhistory',
        'diagnostic/memories',
        'ifmgr/interfaces',
        'ifmgr/ports',
        'ifmgr/statistics',
        'ifmon/ifmonstatisticsinterfaces'
    ]
    
    # 获取自定义传感器路径，如果没有提供则使用默认路径
    sensor_paths = device_params.get('sensor_paths', default_sensor_paths)
    
    config_commands = []
    
    # 首先启用gRPC服务（Telemetry功能的前提条件）
    config_commands.append("grpc enable")
    
    # 进入telemetry配置
    config_commands.append("telemetry")
    
    # 配置sensor-group
    config_commands.append(f"sensor-group {sensor_group_name}")
    for path in sensor_paths:
        config_commands.append(f"sensor path {path}")
    config_commands.append("quit")
    
    # 配置destination-group  
    config_commands.append(f"destination-group {destination_group_name}")
    config_commands.append(f"ipv4-address {collector_ip} port {collector_port}")
    config_commands.append("quit")
    
    # 直接在telemetry配置中进行subscription配置（不退出）
    config_commands.append(f"subscription {subscription_name}")
    config_commands.append(f"sensor-group {sensor_group_name} sample-interval {sample_interval}")
    config_commands.append(f"destination-group {destination_group_name}")
    config_commands.append("quit")  # 退出subscription配置
    
    # 退出telemetry配置
    config_commands.append("quit")
    
    return config_commands

def ssh_system_view(device_params):
    """登录设备并执行system-view命令，配置Telemetry参数"""
    
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
        # 初始化连接，发送空命令确保连接稳定
        ssh.send_command("", strip_prompt=False, strip_command=False, read_timeout=2)
        time.sleep(0.1)
        
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
        # 先获取当前的提示符并清理
        ssh.clear_buffer()
        time.sleep(0.1)
        raw_initial_prompt = ssh.find_prompt()
        prompt = simple_clean_prompt(raw_initial_prompt)
        
        # 步骤1: 执行screen-length disable命令禁用屏幕分页
        print(f"{prompt}screen-length disable")
        disable_output = ssh.send_command(
            "screen-length disable",
            expect_string=r"[>\]]",  # 使用通用提示符匹配
            strip_prompt=True,
            strip_command=True,
            read_timeout=10
        )
        print(disable_output, end='')
        time.sleep(0.1)
        
        # 步骤2: 获取系统信息 (在进入系统视图前)
        system_info = get_system_info_for_log(ssh, device_name)
        
        # 步骤3: 执行system-view命令进入系统视图
        print(f"{prompt}system-view")
        output = ssh.send_command(
            "system-view",
            expect_string=r"[>\]]",  # 使用通用提示符匹配，避免特殊字符问题
            strip_prompt=True,
            strip_command=True,
            read_timeout=15
        )
        print(output)
        executed_commands.append({
            "command": "system-view", 
            "output": f"{prompt}system-view{'' if output.strip() == '' else ' ' + output.strip()}"
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
        
        telemetry_commands = generate_telemetry_config(device_params)
        
        # 执行Telemetry配置命令
        for command in telemetry_commands:
            try:
                # 检查SSH连接状态
                if not ssh.is_alive():
                    error_message = "SSH连接已断开，无法继续执行命令"
                    print(f"\n错误: {error_message}")
                    system_info_dict = {device_name: system_info}
                    return "Failed", None, executed_commands, error_message, system_info_dict
                
                # 清理SSH缓冲区避免输出混乱
                try:
                    ssh.clear_buffer()
                except:
                    pass
                
                # 获取当前提示符 - 优化处理避免重复
                try:
                    current_prompt = ssh.find_prompt()
                    # 使用simple_clean_prompt清理重复提示符
                    if current_prompt:
                        current_prompt = simple_clean_prompt(current_prompt)
                        # 确保提示符以>或]结尾
                        if not (current_prompt.endswith('>') or current_prompt.endswith(']')):
                            current_prompt = current_prompt + '>'
                    else:
                        current_prompt = ">"
                except:
                    current_prompt = ">"
                
                # 打印命令（因为timing方式可能不显示完整命令）
                print(f"{current_prompt}{command}")
                
                # 恢复使用send_command方式，但调整参数解决之前的问题
                if 'ipv4-address' in command:
                    # 对于IP地址配置命令，使用更长延迟确保捕获错误信息
                    output = ssh.send_command(
                        command,
                        expect_string=r"[>\]]",  # 使用通用提示符匹配
                        delay_factor=3.0,        # 进一步增加延迟以捕获错误信息
                        max_loops=150,           # 增加等待循环次数
                        strip_command=True,      # 自动移除命令回显
                        strip_prompt=True,       # 自动移除提示符
                        read_timeout=30          # 增加读取超时
                    )
                else:
                    # 其他命令使用更长延迟避免命令连接
                    output = ssh.send_command(
                        command,
                        expect_string=r"[>\]]",  # 使用通用提示符匹配
                        delay_factor=1.0,        # 增加延迟避免命令连接
                        max_loops=80,            # 增加等待循环次数
                        strip_command=True,      # 自动移除命令回显
                        strip_prompt=True,       # 自动移除提示符
                        read_timeout=20          # 增加读取超时
                    )
                
                # 命令间延迟，确保设备完全处理完命令
                time.sleep(0.2)
                
                # 显示输出（过滤提示符行）
                if output and output.strip():
                    cleaned = output.strip()
                    # 过滤掉只包含提示符的行
                    import re
                    if not re.match(r'^[<\[][^>\]]*[>\]]$', cleaned):
                        print(cleaned)
                
                # 命令间延迟，确保设备完全处理完命令
                time.sleep(0.2)
                
                # 记录命令执行结果（应用与显示输出相同的过滤逻辑）
                log_output = f"{current_prompt}{command}"
                if output and output.strip():
                    cleaned_output = output.strip()
                    import re
                    # 应用与屏幕显示相同的过滤逻辑：过滤掉纯提示符行
                    if not re.match(r'^[<\[][^>\]]*[>\]]$', cleaned_output):
                        # 进一步清理输出中包含的多余提示符
                        cleaned_output = re.sub(r'\n\s*[<\[][^>\]]*[>\]]\s*$', '', cleaned_output)
                        if cleaned_output:
                            log_output += f"\n{cleaned_output}"
                
                executed_commands.append({
                    "command": command, 
                    "output": log_output
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
                
                # 特殊处理quit命令 - 避免多余输出
                if command.lower() == "quit":
                    time.sleep(0.1)  # 给设备处理时间
                    # quit命令不显示后续空提示符
                    continue
                
            except Exception as cmd_error:
                error_message = f"执行命令 '{command}' 时发生异常: {str(cmd_error)}"
                print(f"\n错误: {error_message}")
                
                # 记录命令执行异常（简化记录）
                executed_commands.append({
                    "command": command, 
                    "output": f"{command} (执行异常: {str(cmd_error)})"
                })
                
                system_info_dict = {device_name: system_info}
                
                if ssh:
                    ssh.disconnect()
                return "Failed", None, executed_commands, error_message, system_info_dict
        
        # 返回system_info作为一个字典，键为设备名
        system_info_dict = {device_name: system_info}
        return "succeed", ssh, executed_commands, "", system_info_dict
        
    except Exception as e:
        error_msg = str(e)
        print(f"\n配置执行失败：{error_msg}")
        
        # 返回已获取的系统信息和已执行的命令
        if 'system_info' in locals():
            system_info_dict = {device_name: system_info}
        else:
            system_info_dict = {}
        
        if ssh:
            try:
                ssh.disconnect()
            except:
                pass  # 忽略断开连接时的错误
        return "Failed", None, executed_commands, error_msg, system_info_dict

def config_single_device_telemetry(device_params):
    """配置单台设备的Telemetry功能"""
    
    # 执行Telemetry配置
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

def config_multiple_devices_telemetry(base_params, hostips):
    """配置多台设备的Telemetry功能"""
    
    success_count = 0
    total_count = len(hostips)
    
    print(f"\n开始配置 {total_count} 台设备的Telemetry功能...")
    
    for i, hostip in enumerate(hostips, 1):
        print(f"\n=== 正在配置第 {i}/{total_count} 台设备: {hostip} ===")
        
        # 为每台设备创建独立的参数字典
        device_params = base_params.copy()
        device_params['hostip'] = hostip
        
        if config_single_device_telemetry(device_params):
            success_count += 1
            print(f"设备 {hostip} 配置成功")
        else:
            print(f"设备 {hostip} 配置失败")
    
    print(f"\n=== 配置完成: {success_count}/{total_count} 台设备配置成功 ===")
    return success_count == total_count

def main():
    """主函数"""
    
    if len(sys.argv) != 2:
        print("用法: python TELEMETRY_CONFIG_TEST.py '<JSON参数>'")
        print("\n参数说明:")
        print("必需参数:")
        print("  hostip: 设备IP地址 (单设备) 或 逗号分隔的IP列表 (多设备)")
        print("  username: 登录用户名")
        print("  password: 登录密码")
        print("  collector_ip: 收集器IP地址")
        print("\n重要提示:")
        print("  脚本会自动执行 'grpc enable' 命令启用gRPC服务")
        print("  这是Telemetry功能正常工作的必要前提条件")
        print("\n可选参数:")
        print("  sensor_group_name: 传感器组名称 (默认: group1)")
        print("  destination_group_name: 目标组名称 (默认: group1)")
        print("  subscription_name: 订阅名称 (默认: sub1)")
        print("  collector_port: 收集器端口 (默认: 50051)")
        print("  sample_interval: 采样间隔(秒) (默认: 1)")
        print("  sensor_paths: 传感器路径列表 (可选，使用默认路径)")
        print("\n默认传感器路径:")
        print("  - device/transceivers")
        print("  - diagnostic/cpuhistory")
        print("  - diagnostic/memories")
        print("  - ifmgr/interfaces")
        print("  - ifmgr/ports")
        print("  - ifmgr/statistics")
        print("  - ifmon/ifmonstatisticsinterfaces")
        print("\n单设备配置示例:")
        print('python TELEMETRY_CONFIG_TEST.py \'{"hostip":"192.168.1.1","username":"admin","password":"admin","collector_ip":"192.168.100.1","sensor_group_name":"group1","destination_group_name":"group1","subscription_name":"sub1","sample_interval":"10"}\'')
        print("\n多设备配置示例:")
        print('python TELEMETRY_CONFIG_TEST.py \'{"hostip":"192.168.1.1,192.168.1.2,192.168.1.3","username":"admin","password":"admin","collector_ip":"192.168.100.1","sample_interval":"5"}\'')
        sys.exit(1)

    try:
        # 解析JSON参数
        json_str = sys.argv[1]
        params = json.loads(json_str)

        # 解析参数后立即记录Running状态的日志       
        write_log.write_log("Running", {}, {})
        
        # 检查必要参数
        required_params = ['hostip', 'username', 'password', 'collector_ip']
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
            success = config_single_device_telemetry(params)
            sys.exit(0 if success else 1)
        else:
            # 多设备配置模式
            print(f"\n检测到多设备配置模式: {len(hostips)} 台设备")
            print(f"设备列表: {', '.join(hostips)}")
            
            # 创建基础参数字典（排除hostip）
            base_params = {k: v for k, v in params.items() if k != 'hostip'}
            
            # 执行多设备配置
            success = config_multiple_devices_telemetry(base_params, hostips)
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
