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

def get_cached_interfaces(ssh):
    """获取接口信息，优先使用缓存"""
    global cached_interfaces
    
    device_id = ssh.host if hasattr(ssh, 'host') else "unknown"
    
    if device_id in cached_interfaces:
        print(f"使用缓存的接口列表，跳过执行: display interface brief | include UP|DOWN|ADM")
        return cached_interfaces[device_id]
    
    interfaces = interface_config.get_device_interfaces(ssh)
    cached_interfaces[device_id] = interfaces
    
    return interfaces

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
        cleaned = re.sub(r'\n*<[^>]+>\n*', '', system_info)
        cleaned = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned)
        cleaned = re.sub(r'display\s+version\n*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n+', '\n', cleaned)
        return cleaned.strip()
    else:
        return system_info

def generate_dhcp_server_config(dhcp_params):
    """生成DHCP Server配置命令"""
    config_commands = []
    
    # 获取参数
    pool_name = dhcp_params.get('pool_name', 'dhcp_pool')
    network = dhcp_params.get('network', '192.168.100.0')
    mask = dhcp_params.get('mask', '255.255.255.0')
    gateway = dhcp_params.get('gateway', '192.168.100.1')
    dns_server = dhcp_params.get('dns_server', '8.8.8.8')
    server_to_relay_interface = dhcp_params.get('server_to_relay_interface', '')
    
    # 1. 开启DHCP服务
    config_commands.append("dhcp enable")
    
    # 2. 创建DHCP地址池
    config_commands.append(f"dhcp server ip-pool {pool_name}")
    config_commands.append(f"network {network} mask {mask}")
    config_commands.append(f"gateway-list {gateway}")
    config_commands.append(f"dns-list {dns_server}")
    config_commands.append("quit")
    
    # 3. 添加静态路由 (指向DHCP客户端网络)
    config_commands.append(f"ip route-static {network} {mask} {server_to_relay_interface} 172.16.1.2")
    
    return config_commands

def generate_dhcp_relay_config(relay_params):
    """生成DHCP Relay配置命令"""
    config_commands = []
    
    # 1. 开启DHCP服务
    config_commands.append("dhcp enable")
    
    # 2. 开启DHCP中继客户端信息记录功能
    config_commands.append("dhcp relay client-information record")
    
    return config_commands

def ssh_system_view(device_params):
    """登录设备并执行system-view命令，配置DHCP全局参数"""
    global log_recorded
    
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
        
        # 获取设备角色和相关参数
        device_role = device_params.get('device_role', 'server')  # server or relay
        
        # 根据设备角色生成相应的DHCP配置命令
        if device_role == 'server':
            print("\n配置DHCP Server...")
            dhcp_commands = generate_dhcp_server_config(device_params)
        else:
            print("\n配置DHCP Relay...")
            dhcp_commands = generate_dhcp_relay_config(device_params)
        
        # 执行DHCP配置命令
        for command in dhcp_commands:
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
            
            # 添加错误检查
            status = check_device_output.check_device_output(output)
            if status == "Failed":
                error_message = f"执行命令 '{command}' 失败，设备返回了错误信息"
                print(f"\n错误: {error_message}")
                
                # 返回已获取的系统信息和已执行的命令
                system_info_dict = {device_name: system_info}
                
                if ssh:
                    ssh.disconnect()
                return "Failed", None, executed_commands, error_message, system_info_dict
            
            # 记录到日志
            executed_commands.append({
                "command": command, 
                "output": f"{current_prompt}{command}{'' if output.strip() == '' else ' '}{output.strip()}"
            })
            
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
        
        error_msg = f"配置执行失败: {str(e)}"
        system_info_dict = {}
        
        # 确保设备名已定义
        if 'device_name' not in locals():
            device_name = device_params.get('device_name', 'unknown_device')
        
        if device_name and ssh:
            try:
                version_output = get_system_info.get_system_info(ssh)
                cleaned_version_output = clean_system_info(version_output, device_name)
                system_info_dict[device_name] = cleaned_version_output or "未能获取到版本信息"
            except Exception as sys_info_error:
                print(f"获取系统信息失败: {str(sys_info_error)}")
                system_info_dict[device_name] = f"获取版本信息失败: {str(sys_info_error)}"
        else:
            system_info_dict[device_name if device_name else 'unknown_device'] = "SSH连接不可用或设备名未知"
        
        log_path = write_log.write_log("Failed", executed_commands or [], system_info_dict, error_msg)
        
        if log_path:
            print(f"\n日志已保存至: {log_path}")
        
        if ssh:
            ssh.disconnect()
        sys.exit(1)

        return "Failed", None, [], error_msg, system_info_dict

def config_interface_dhcp_server_pool(ssh, interface, pool_name='dhcp_pool', all_interfaces=None, 
                                   executed_commands=None, device_name="config"):
    """配置接口DHCP Server地址池绑定"""
    global log_recorded
    
    # 使用传入的接口列表或从缓存获取
    if all_interfaces is None:
        all_interfaces = get_cached_interfaces(ssh)
    
    # 映射接口编号到实际接口名
    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh)
    if mapped_interfaces:
        interface = mapped_interfaces[0]
        print(f"映射后的接口名: {interface}")

    print(f"执行命令: interface {interface}")

    # 检查接口模式并切换到route模式（DHCP Server pool绑定需要route模式）
    is_loopback = interface_config.is_loopback_interface(interface)
    if not is_loopback:
        current_mode = interface_config.check_interface_mode(ssh, interface)
        if current_mode and current_mode.lower() != "route":
            print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
            # 切换到route模式
            switch_result = interface_config.switch_interface_to_route_mode(ssh, interface, executed_commands)
            if switch_result is False:
                print(f"\n错误: 将接口 {interface} 切换到route模式失败")
                if ssh:
                    ssh.disconnect()
                sys.exit(1)
        else:
            print(f"接口 {interface} 已经是route模式，跳过切换")
    else:
        print(f"接口 {interface} 是环回口，不适用于DHCP Server地址池绑定")
        return "Failed", "环回口不适用于DHCP Server地址池绑定"

    # 添加等待时间
    print("等待2秒以确保设备响应...")
    time.sleep(2)
    
    # 进入接口模式
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, interface, executed_commands, skip_vlan_creation=True)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义DHCP Server地址池绑定命令
    dhcp_server_commands = [
        f"dhcp server apply ip-pool {pool_name}",
        "quit"
    ]
    
    # 使用interface_config的批量发送命令功能
    status, dhcp_executed_commands, error_message = interface_config.execute_commands(
        ssh, dhcp_server_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 将DHCP命令结果合并到主命令列表
    if dhcp_executed_commands and isinstance(dhcp_executed_commands, list):
        for cmd in dhcp_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name)
    
    return status, error_message

def config_interface_dhcp_relay(ssh, interface, all_interfaces=None, dhcp_server_ip=None, 
                               executed_commands=None, device_name="config"):
    """配置接口的DHCP Relay参数"""
    global log_recorded
    
    # 使用传入的接口列表或从缓存获取
    if all_interfaces is None:
        all_interfaces = get_cached_interfaces(ssh)
    
    # 映射接口编号到实际接口名
    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh)
    if mapped_interfaces:
        interface = mapped_interfaces[0]
        print(f"映射后的接口名: {interface}")

    print(f"执行命令: interface {interface}")

    # 检查接口模式并切换到route模式（DHCP Relay需要route模式）
    is_loopback = interface_config.is_loopback_interface(interface)
    if not is_loopback:
        current_mode = interface_config.check_interface_mode(ssh, interface)
        if current_mode and current_mode.lower() != "route":
            print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
            # 切换到route模式
            switch_result = interface_config.switch_interface_to_route_mode(ssh, interface, executed_commands)
            if switch_result is False:
                print(f"\n错误: 将接口 {interface} 切换到route模式失败")
                if ssh:
                    ssh.disconnect()
                sys.exit(1)
        else:
            print(f"接口 {interface} 已经是route模式，跳过切换")
    else:
        print(f"接口 {interface} 是环回口，不适用于DHCP Relay配置")
        return "Failed", "环回口不适用于DHCP Relay配置"

    # 添加等待时间
    print("等待2秒以确保设备响应...")
    time.sleep(2)
    
    # 进入接口模式
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, interface, executed_commands, skip_vlan_creation=True)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义DHCP Relay接口命令
    dhcp_relay_commands = [
        "dhcp select relay",
        f"dhcp relay server-address {dhcp_server_ip}" if dhcp_server_ip else "dhcp relay server-address 172.16.1.1",
        "quit"
    ]
    
    # 使用interface_config的批量发送命令功能
    status, dhcp_executed_commands, error_message = interface_config.execute_commands(
        ssh, dhcp_relay_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 将DHCP命令结果合并到主命令列表
    if dhcp_executed_commands and isinstance(dhcp_executed_commands, list):
        for cmd in dhcp_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name)
    
    return status, error_message

def config_dual_devices_dhcp(dual_params):
    """同时配置两台设备的DHCP参数"""
    # 提取共同参数
    common_params = dual_params.get('common', {})

    # 提取接口信息
    interface_params = dual_params.get('interfaces', {})
    server_to_relay_interface = interface_params.get('server_to_relay_interface', '')
    relay_to_server_interface = interface_params.get('relay_to_server_interface', '')
    relay_dhcp_interface = interface_params.get('relay_dhcp_interface', '')
    
    # 检查接口参数（必须）
    if not server_to_relay_interface or not relay_to_server_interface:
        print("错误: 必须提供两台设备的接口参数 server_to_relay_interface 和 relay_to_server_interface")
        return "Failed", {}, {}, "缺少接口参数", {}
    
    if not relay_dhcp_interface:
        print("错误: 必须提供 relay_dhcp_interface 参数")
        return "Failed", {}, {}, "缺少relay_dhcp_interface参数", {}

    # 创建设备参数
    devices = []
    for idx, device_key in enumerate(['server', 'relay']):
        if device_key not in dual_params:
            print(f"错误: 缺少设备 {device_key} 的参数")
            return "Failed", {}, {}, f"缺少设备 {device_key} 的参数", {}
        
        device_params = dual_params[device_key]
        
        # 添加设备角色
        device_params['device_role'] = device_key
        
        # 为设备分配接口
        if device_key == 'server':
            device_params['interface'] = server_to_relay_interface
            # DHCP Server参数
            device_params.update(common_params.get('dhcp_server', {}))
        else:
            device_params['interface'] = relay_to_server_interface  # 互联接口
            device_params['relay_dhcp_interface'] = relay_dhcp_interface  # DHCP配置接口
            # DHCP Relay参数
            device_params.update(common_params.get('dhcp_relay', {}))
        
        devices.append(device_params)
    
    # 保存两台设备的执行命令和系统信息
    all_executed_commands = {}
    all_system_info = {}
    final_status = "succeed"
    error_messages = []
    
    # 依次配置每台设备
    for i, device_params in enumerate(devices):
        temp_id = ['server', 'relay'][i]
        print(f"\n开始配置设备 {temp_id}...")
        
        try:
            # 登录设备并配置全局DHCP参数
            status, ssh_conn, executed_commands, error_message, device_system_info = ssh_system_view(device_params)
            
            if status == "Failed" or ssh_conn is None:
                final_status = "Failed"
                device_name = device_params.get('device_name', temp_id)
                error_messages.append(f"{device_name}: {error_message}")
                
                # 更新系统信息字典，即使失败也要记录已获取的信息
                if device_system_info:
                    all_system_info.update(device_system_info)
                
                # 更新执行命令字典，即使失败也要记录已执行的命令
                if executed_commands:
                    all_executed_commands[device_name] = executed_commands
                
                # 转换命令记录格式
                result_format = {}
                for device_name_key, commands in all_executed_commands.items():
                    full_output = []
                    for cmd_entry in commands:
                        if isinstance(cmd_entry, dict):
                            output = cmd_entry.get("output", "")
                            if output:
                                full_output.append(output)
                    result_format[device_name_key] = "\n".join(full_output)
                
                # 记录日志
                log_path = write_log.write_log(final_status, result_format, all_system_info, 
                            "\n".join(error_messages))
                if log_path:
                    print(f"\n日志已保存至: {log_path}")
                sys.exit(1)
            
            # 获取设备名
            device_name = device_params.get('device_name', f"device{i+1}")
            
            # 更新系统信息字典
            all_system_info.update(device_system_info)
            
            # 获取接口信息
            all_interfaces = get_cached_interfaces(ssh_conn)
            
            # 处理接口参数
            interface = device_params['interface']
            
            # 接口映射
            mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh_conn)
            if not mapped_interfaces:
                raise Exception(f"无法映射接口名称: {interface}")
                
            interface = mapped_interfaces[0]
            
            # 配置接口IP地址（如果提供）
            if device_params.get('ip_address') and device_params.get('mask'):
                print(f"\n配置接口 {interface} 的IP地址...")
                
                # 检查接口模式并切换到route模式（IP地址配置需要route模式）
                is_loopback = interface_config.is_loopback_interface(interface)
                if not is_loopback:
                    current_mode = interface_config.check_interface_mode(ssh_conn, interface)
                    if current_mode and current_mode.lower() != "route":
                        print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
                        # 切换到route模式
                        switch_result = interface_config.switch_interface_to_route_mode(ssh_conn, interface, executed_commands)
                        if switch_result is False:
                            raise Exception(f"将接口 {interface} 切换到route模式失败")
                    else:
                        print(f"接口 {interface} 已经是route模式，可以配置IP地址")
                else:
                    print(f"接口 {interface} 是环回口，可以直接配置IP地址")
                
                # 添加等待时间确保模式切换完成
                print("等待2秒以确保接口模式切换完成...")
                time.sleep(2)
                
                result = interface_config.config_interface_ip(
                    ssh_conn, interface,
                    device_params.get('ip_address'),
                    device_params.get('mask'),
                    executed_commands
                )
                
                if result == "Failed" or (isinstance(result, tuple) and len(result) > 0 and result[0] == "Failed"):
                    error_msg = f"配置接口 {interface} IP地址失败"
                    if isinstance(result, tuple) and len(result) > 1:
                        error_msg += f": {result[1]}"
                    raise Exception(error_msg)
            
            # 如果是DHCP Server设备，配置接口DHCP Server地址池绑定
            if device_params['device_role'] == 'server':
                # 获取地址池名称和server_to_relay_interface
                pool_name = device_params.get('pool_name', 'dhcp_pool')
                server_to_relay_interface = device_params.get('server_to_relay_interface', interface)
                
                print(f"\n配置接口 {server_to_relay_interface} 的DHCP Server地址池绑定...")
                
                result, error_message = config_interface_dhcp_server_pool(
                    ssh_conn, server_to_relay_interface,
                    pool_name=pool_name,
                    all_interfaces=all_interfaces,
                    executed_commands=executed_commands,
                    device_name=device_name
                )
                
                if result == "Failed":
                    raise Exception(f"配置接口DHCP Server地址池绑定失败: {error_message}")
            
            # 如果是DHCP Relay设备，配置接口DHCP Relay
            if device_params['device_role'] == 'relay':
                # 获取DHCP配置接口
                relay_dhcp_interface = device_params.get('relay_dhcp_interface')
                if relay_dhcp_interface:
                    print(f"\n配置接口 {relay_dhcp_interface} 的DHCP Relay参数...")
                    
                    # 映射DHCP配置接口
                    mapped_dhcp_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [relay_dhcp_interface], ssh_conn)
                    if not mapped_dhcp_interfaces:
                        raise Exception(f"无法映射DHCP配置接口名称: {relay_dhcp_interface}")
                        
                    relay_dhcp_interface = mapped_dhcp_interfaces[0]
                    
                    # 为relay_dhcp_interface配置默认IP地址 192.168.100.1/24
                    print(f"为接口 {relay_dhcp_interface} 配置默认IP地址 192.168.100.1/24...")
                    
                    # 检查接口模式并切换到route模式（IP地址配置需要route模式）
                    is_loopback_dhcp = interface_config.is_loopback_interface(relay_dhcp_interface)
                    if not is_loopback_dhcp:
                        current_mode_dhcp = interface_config.check_interface_mode(ssh_conn, relay_dhcp_interface)
                        if current_mode_dhcp and current_mode_dhcp.lower() != "route":
                            print(f"接口 {relay_dhcp_interface} 当前模式为 {current_mode_dhcp}，需要切换到route模式")
                            # 切换到route模式
                            switch_result_dhcp = interface_config.switch_interface_to_route_mode(ssh_conn, relay_dhcp_interface, executed_commands)
                            if switch_result_dhcp is False:
                                raise Exception(f"将接口 {relay_dhcp_interface} 切换到route模式失败")
                        else:
                            print(f"接口 {relay_dhcp_interface} 已经是route模式，可以配置IP地址")
                    else:
                        print(f"接口 {relay_dhcp_interface} 是环回口，可以直接配置IP地址")
                    
                    # 添加等待时间确保模式切换完成
                    print("等待2秒以确保接口模式切换完成...")
                    time.sleep(2)
                    
                    # 配置DHCP接口的IP地址
                    result_dhcp_ip = interface_config.config_interface_ip(
                        ssh_conn, relay_dhcp_interface,
                        "192.168.100.1",  # 默认IP地址
                        "255.255.255.0",  # 默认掩码
                        executed_commands
                    )
                    
                    if result_dhcp_ip == "Failed" or (isinstance(result_dhcp_ip, tuple) and len(result_dhcp_ip) > 0 and result_dhcp_ip[0] == "Failed"):
                        error_msg = f"配置接口 {relay_dhcp_interface} IP地址失败"
                        if isinstance(result_dhcp_ip, tuple) and len(result_dhcp_ip) > 1:
                            error_msg += f": {result_dhcp_ip[1]}"
                        raise Exception(error_msg)
                    
                    # 获取DHCP Server的IP地址（server设备连接relay设备的接口IP地址）
                    server_interface_ip = device_params.get('server_interface_ip', device_params.get('dhcp_server_ip', '172.16.1.1'))
                    result, error_message = config_interface_dhcp_relay(
                        ssh_conn, relay_dhcp_interface,
                        all_interfaces=all_interfaces,
                        dhcp_server_ip=server_interface_ip,
                        executed_commands=executed_commands,
                        device_name=device_name
                    )
                    
                    if result == "Failed":
                        raise Exception(f"配置接口DHCP Relay失败: {error_message}")
                else:
                    print("警告: 未提供relay_dhcp_interface参数，跳过DHCP Relay配置")
            
            # 保存命令和系统信息
            all_executed_commands[device_name] = executed_commands
            all_system_info[device_name] = device_system_info.get(device_name, "")

            # 如果是第一台设备完成配置
            if i == 0:
                print(f"第一台设备 {device_name} 配置完成，等待第二台设备配置...")

            # 如果是第二台设备配置完成
            if i == 1:
                print("\n第二台设备配置完成!")

            # 配置完成后断开连接
            if ssh_conn:
                ssh_conn.disconnect()
                
        except Exception as e:
            # 确保device_name变量已定义
            if 'device_name' not in locals():
                device_name = f"device{i+1}" if 'i' in locals() else "unknown_device"

            error_msg = f"{device_name} 配置失败: {str(e)}"
            print(error_msg)
            final_status = "Failed"
            error_messages.append(error_msg)

            # 在异常处理中保存当前设备的配置信息
            if 'executed_commands' in locals() and executed_commands:
                all_executed_commands[device_name] = executed_commands

            if 'device_system_info' in locals() and device_system_info:
                all_system_info.update(device_system_info)
            
            # 确保断开连接
            if 'ssh_conn' in locals() and ssh_conn:
                try:
                    ssh_conn.disconnect()
                except:
                    pass
                
            # 不要立即记录日志，让程序继续到最终的日志记录部分
            break  # 跳出循环，但继续执行最终的日志记录
    
    # 转换命令记录格式
    result_format = {}
    for device_name_key, commands in all_executed_commands.items():
        full_output = []
        for cmd_entry in commands:
            if isinstance(cmd_entry, dict):
                output = cmd_entry.get("output", "")
                if output:
                    full_output.append(output)
        result_format[device_name_key] = "\n".join(full_output)

    # 记录日志
    log_path = write_log.write_log(
        "Completed" if final_status == "succeed" else final_status, 
        result_format, 
        all_system_info, 
        "\n".join(error_messages) if error_messages else None
    )

    if log_path:
        print(f"日志已保存至: {log_path}")

    return final_status, all_executed_commands, all_system_info

def main():
    """主函数"""
    global log_recorded
    log_recorded = False
    
    try:
        if len(sys.argv) != 2:
            # 显示帮助信息
            print("使用方法:")
            print('python DHCP_RELAY_CONFIG_TEST.py {"hostip":"192.168.56.10,192.168.56.11",')
            print('                                  "username":"admin","password":"admin123",')
            print('                                  "server_to_relay_interface":"GigabitEthernet1/0/1","relay_to_server_interface":"GigabitEthernet1/0/1",')
            print('                                  "relay_dhcp_interface":"GigabitEthernet1/0/2",')
            print('                                  "pool_name":"dhcp_pool","network":"192.168.100.0","mask":"255.255.255.0",')
            print('                                  "gateway":"192.168.100.1","dns_server":"8.8.8.8"}')
            
            print("\n参数说明：")
            print("  hostip: 设备IP地址，用逗号分隔两个设备（第一个为DHCP Server，第二个为DHCP Relay）")
            print("  username: 设备用户名（两台设备使用相同用户名）")
            print("  password: 设备密码（两台设备使用相同密码）")
            print("  server_to_relay_interface: DHCP Server设备连接Relay的接口名称")
            print("  relay_to_server_interface: DHCP Relay设备连接Server的接口名称")
            print("  relay_dhcp_interface: DHCP Relay设备用于中继DHCP请求的接口名称（必须）")
            print("  pool_name: DHCP地址池名称，默认为dhcp_pool")
            print("  network: DHCP网络地址，默认为192.168.100.0")
            print("  mask: DHCP网络掩码，默认为255.255.255.0")
            print("  gateway: DHCP网关地址，默认为192.168.100.1")
            print("  dns_server: DNS服务器地址，默认为8.8.8.8")
            print("\n功能说明：")
            print("  - DHCP Server设备将自动配置：")
            print("    * 在server_to_relay_interface接口下绑定DHCP地址池：dhcp server apply ip-pool {pool_name}")
            print("    * 添加指向客户端网络的静态路由：ip route-static {network} {mask} {server_to_relay_interface} 172.16.1.2")
            print("  - DHCP Relay设备将自动配置：")
            print("    * 开启客户端信息记录功能：dhcp relay client-information record")
            print("\n注意：")
            print("  - Server和Relay设备互联接口IP已固定为：")
            print("    * Server设备互联接口：172.16.1.1/24")
            print("    * Relay设备互联接口：172.16.1.2/24")
            print("  - Relay设备的DHCP中继接口将自动配置IP：192.168.100.1/24")
            
            sys.exit(1)

        try:
            # 处理输入参数
            json_str = sys.argv[1]
            params = json.loads(json_str)

            # 解析参数后立即记录Running状态的日志       
            write_log.write_log("Running", {}, {})
            
            # 检查必要参数
            if not params.get('hostip'):
                print("错误: 必须提供hostip参数")
                sys.exit(1)
            
            # 解析逗号分隔的hostip参数
            hostips = [ip.strip() for ip in params.get("hostip", "").split(",")]
            if len(hostips) != 2:
                print("错误: hostip参数必须包含两个用逗号分隔的IP地址")
                sys.exit(1)
            
            if not params.get('server_to_relay_interface') or not params.get('relay_to_server_interface'):
                print("错误: 必须提供server_to_relay_interface和relay_to_server_interface参数")
                sys.exit(1)
            
            if not params.get('relay_dhcp_interface'):
                print("错误: 必须提供relay_dhcp_interface参数")
                sys.exit(1)
            
            # 处理双设备配置
            print("\n使用双设备模式配置DHCP")
            
            # 构建标准化的双设备参数
            dual_params = {
                "server": {
                    "hostip": hostips[0],  # 第一个IP为DHCP Server
                    "username": params.get("username", "admin"),
                    "password": params.get("password", "admin"),
                    "ip_address": "172.16.1.1",  # Server设备互联接口IP（固定值）
                    "mask": "255.255.255.0"  # 互联接口掩码（固定值）
                },
                "relay": {
                    "hostip": hostips[1],  # 第二个IP为DHCP Relay
                    "username": params.get("username", "admin"),
                    "password": params.get("password", "admin"),
                    "ip_address": "172.16.1.2",  # Relay设备互联接口IP（固定值）
                    "mask": "255.255.255.0",  # 互联接口掩码（固定值）
                    "dhcp_server_ip": hostips[0],  # DHCP Server的IP地址
                    "server_interface_ip": "172.16.1.1",  # Server设备连接Relay的接口IP（固定值）
                    "dhcp_server_group": params.get("dhcp_server_group", "1")
                },
                "common": {
                    "dhcp_server": {
                        "pool_name": params.get("pool_name", "dhcp_pool"),
                        "network": params.get("network", "192.168.100.0"),
                        "mask": params.get("mask", "255.255.255.0"),
                        "gateway": params.get("gateway", "192.168.100.1"),
                        "dns_server": params.get("dns_server", "8.8.8.8")
                    },
                    "dhcp_relay": {
                        "dhcp_server_ip": hostips[0]  # 使用第一个IP地址作为DHCP Server IP
                    }
                },
                "interfaces": {
                    "server_to_relay_interface": params.get("server_to_relay_interface"),
                    "relay_to_server_interface": params.get("relay_to_server_interface"),
                    "relay_dhcp_interface": params.get("relay_dhcp_interface")
                }
            }
            
            # 配置双设备DHCP
            print("\n启动双设备DHCP配置...")
            status, executed_commands, system_info = config_dual_devices_dhcp(dual_params)
            
            if status == "Failed":
                print(f"\n双设备DHCP配置失败")
                sys.exit(1)
            else:
                print("\n双设备DHCP配置完成!")

        except json.JSONDecodeError as e:
            print(f"\n错误: 无法解析JSON参数: {str(e)}")
            print("请确保输入参数是有效的JSON格式")
            
            # 记录错误日志
            write_log.write_log("Failed", {}, {}, f"JSON解析错误: {str(e)}")
            sys.exit(1)

        except Exception as e:
            print(f"\n意外错误: {str(e)}")
            
            # 记录错误日志
            write_log.write_log("Failed", {}, {}, f"意外错误: {str(e)}")
            sys.exit(1)

    except Exception as e:
        print(f"\n程序运行时发生错误: {str(e)}")
        
        # 确保错误被记录
        try:
            write_log.write_log("Failed", {}, {}, f"程序错误: {str(e)}")
        except:
            pass
        
        sys.exit(1)

if __name__ == "__main__":
    main()
