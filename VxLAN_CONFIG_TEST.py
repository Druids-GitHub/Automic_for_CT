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

def generate_vxlan_config(vxlan_params):
    """生成VXLAN配置命令"""
    config_commands = []
    
    # 获取参数
    vni = vxlan_params.get('vni', '10000')
    vlan_id = vxlan_params.get('vlan_id', '100')
    local_ip = vxlan_params.get('local_ip', '')
    remote_ip = vxlan_params.get('remote_ip', '')
    vsi_name = vxlan_params.get('vsi_name', f'vsi{vni}')
    
    # 0.开启L2VPN功能
    config_commands.append("l2vpn enable")

    # 1. 创建VSI (Virtual Switch Instance)
    config_commands.append(f"vsi {vsi_name}")
    config_commands.append(f"vxlan {vni}")
    config_commands.append("quit")
    
    # 2. 创建VXLAN隧道
    config_commands.append(f"interface tunnel {vni} mode vxlan")
    config_commands.append(f"source {local_ip}")  # 使用Loopback接口的IP地址作为源
    config_commands.append(f"destination {remote_ip}")
    config_commands.append("quit")

    # 3. 将tunnel与VSI关联
    config_commands.append(f"vsi {vsi_name}")
    config_commands.append(f"vxlan {vni}")
    config_commands.append(f"tunnel {vni}")
    config_commands.append("quit")
    config_commands.append("quit")
    
    # 注意：service-instance命令需要在接口配置模式下执行，已移至config_interface_vxlan函数

    return config_commands

def ssh_system_view(device_params):
    """登录设备并执行system-view命令，配置VXLAN全局参数"""
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
            
            if ssh:
                ssh.disconnect()
            return "Failed", None, executed_commands, error_message, {}
        
        # 获取VXLAN参数
        vni = device_params.get('vni', '10000')
        vlan_id = device_params.get('vlan_id', '100')
        local_ip = device_params.get('local_ip', '')
        remote_ip = device_params.get('remote_ip', '')
        vsi_name = device_params.get('vsi_name', f'vsi{vni}')
        
        # 生成VXLAN配置命令
        vxlan_commands = generate_vxlan_config({
            'vni': vni,
            'vlan_id': vlan_id,
            'local_ip': local_ip,
            'remote_ip': remote_ip,
            'vsi_name': vsi_name
        })
        
        # 执行VXLAN配置命令
        for command in vxlan_commands:
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
                
                if ssh:
                    ssh.disconnect()
                return "Failed", None, executed_commands, error_message, {}
            
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

def config_interface_vxlan(ssh, interface, all_interfaces=None, vlan_id='100', vni='10000', 
                          vsi_name=None, executed_commands=None, device_name="config"):
    """配置接口的VXLAN参数（切换到bridge模式并配置service-instance）"""
    global log_recorded
    
    # 如果没有提供vsi_name，则使用默认格式
    if vsi_name is None:
        vsi_name = f'vsi{vni}'
    
    # 使用传入的接口列表或从缓存获取
    if all_interfaces is None:
        all_interfaces = get_cached_interfaces(ssh)
    
    # 映射接口编号到实际接口名
    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh)
    if mapped_interfaces:
        interface = mapped_interfaces[0]
        print(f"映射后的接口名: {interface}")

    print(f"执行命令: interface {interface}")

    # 检查接口模式并切换到bridge模式（VXLAN需要bridge模式）
    is_loopback = interface_config.is_loopback_interface(interface)
    if not is_loopback:
        current_mode = interface_config.check_interface_mode(ssh, interface)
        if current_mode and current_mode.lower() != "bridge":
            print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到bridge模式")
            # 切换到bridge模式
            switch_result = switch_interface_to_bridge_mode(ssh, interface, executed_commands)
            if switch_result is False:
                print(f"\n错误: 将接口 {interface} 切换到bridge模式失败")
                if ssh:
                    ssh.disconnect()
                sys.exit(1)
        else:
            print(f"接口 {interface} 已经是bridge模式，跳过切换")
    else:
        print(f"接口 {interface} 是环回口，不适用于VXLAN配置")
        return "Failed", "环回口不适用于VXLAN配置"

    # 添加等待时间
    print("等待2秒以确保设备响应...")
    time.sleep(2)
    
    # 进入接口模式
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, interface, executed_commands, skip_vlan_creation=True)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义VXLAN接口命令（配置service-instance）
    vxlan_commands = [
        f"service-instance {vni}",
        f"encapsulation s-vid {vlan_id}",
        f"xconnect vsi {vsi_name}",
        "quit",
        "quit"
    ]
    
    # 使用interface_config的批量发送命令功能
    status, vxlan_executed_commands, error_message = interface_config.execute_commands(
        ssh, vxlan_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 将VXLAN命令结果合并到主命令列表
    if vxlan_executed_commands and isinstance(vxlan_executed_commands, list):
        for cmd in vxlan_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name)
    
    return status, error_message

def config_uplink_interface(ssh, interface, all_interfaces=None, vlan_id='100', 
                           executed_commands=None, device_name="config", 
                           device_index=1):
    """配置上行接口参数（切换到route模式、配置IP地址、使能OSPF协议）"""
    global log_recorded
    
    # 使用传入的接口列表或从缓存获取
    if all_interfaces is None:
        all_interfaces = get_cached_interfaces(ssh)
    
    # 映射接口编号到实际接口名
    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh)
    if mapped_interfaces:
        interface = mapped_interfaces[0]
        print(f"映射后的上行接口名: {interface}")

    print(f"执行命令: interface {interface}")

    # 检查接口模式并切换到route模式（上行接口需要route模式进行三层路由）
    is_loopback = interface_config.is_loopback_interface(interface)
    if not is_loopback:
        current_mode = interface_config.check_interface_mode(ssh, interface)
        if current_mode and current_mode.lower() != "route":
            print(f"上行接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
            # 切换到route模式
            switch_result = switch_interface_to_route_mode(ssh, interface, executed_commands)
            if switch_result is False:
                print(f"\n错误: 将上行接口 {interface} 切换到route模式失败")
                if ssh:
                    ssh.disconnect()
                sys.exit(1)
        else:
            print(f"上行接口 {interface} 已经是route模式，跳过切换")
    else:
        print(f"接口 {interface} 是环回口，不适用于上行接口配置")
        return "Failed", "环回口不适用于上行接口配置"

    # 添加等待时间
    print("等待2秒以确保设备响应...")
    time.sleep(2)
    
    # 进入接口模式
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, interface, executed_commands, skip_vlan_creation=True)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义上行接口命令（配置IP地址和OSPF协议）
    uplink_commands = []
    
    # 固定IP地址配置：DUT1使用172.16.1.1/24，DUT2使用172.16.1.2/24
    uplink_ip = f"172.16.1.{device_index}"
    uplink_commands.append(f"ip address {uplink_ip} 255.255.255.0")
    
    # 使能OSPF协议（固定配置：进程ID=1，区域=0）
    uplink_commands.append("ospf 1 area 0")
    uplink_commands.append("ospf network-type p2p") # 设置为点对点网络类型
    
    # 退出接口配置
    uplink_commands.append("quit")
    
    # 使用interface_config的批量发送命令功能
    status, uplink_executed_commands, error_message = interface_config.execute_commands(
        ssh, uplink_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 将上行接口命令结果合并到主命令列表
    if uplink_executed_commands and isinstance(uplink_executed_commands, list):
        for cmd in uplink_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name)
    
    return status, error_message

def switch_interface_to_bridge_mode(ssh, interface, executed_commands):
    """将接口切换到bridge模式 - 使用interface_config模块的函数"""
    return interface_config.switch_interface_to_bridge_mode(ssh, interface, executed_commands)

def switch_interface_to_route_mode(ssh, interface, executed_commands):
    """将接口切换到route模式 - 使用interface_config模块的函数"""
    return interface_config.switch_interface_to_route_mode(ssh, interface, executed_commands)

def config_loopback_interface(ssh, executed_commands=None, device_name="config", device_index=1):
    """配置Loopback接口OSPF协议（使用设备特定的IP地址）"""
    global log_recorded
    
    loopback_interface = "LoopBack0"
    
    # 进入Loopback接口模式
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, loopback_interface, executed_commands, skip_vlan_creation=True)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义Loopback接口配置命令（根据设备索引配置不同IP地址）
    loopback_commands = []
    
    # 根据设备索引分配Loopback IP地址：DUT1使用10.1.1.1，DUT2使用20.1.1.1
    if device_index == 1:
        loopback_ip = "10.1.1.1"
    else:
        loopback_ip = "20.1.1.1"
    
    # 配置IP地址和OSPF协议
    loopback_commands.append(f"ip address {loopback_ip} 32")
    loopback_commands.append("ospf 1 area 0")
    
    # 退出接口配置
    loopback_commands.append("quit")
    
    # 使用interface_config的批量发送命令功能
    status, loopback_executed_commands, error_message = interface_config.execute_commands(
        ssh, loopback_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 将Loopback接口命令结果合并到主命令列表
    if loopback_executed_commands and isinstance(loopback_executed_commands, list):
        for cmd in loopback_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name)
    
    return status, error_message

def config_ospf_process(ssh, executed_commands=None, device_name="config"):
    """配置OSPF进程（固定配置）"""
    global log_recorded
    
    # OSPF进程配置命令（固定配置）
    ospf_commands = [
        "ospf 1",
        "quit"
    ]
    
    # 执行OSPF配置命令
    for command in ospf_commands:
        try:
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
                
                if not log_recorded:
                    log_recorded = True
                    system_info = get_system_info_for_log(ssh, device_name)
                    write_log.write_log("Failed", executed_commands, system_info, error_message, 
                                      device_name=device_name)
                
                return "Failed", error_message
            
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
                
        except Exception as e:
            error_message = f"执行OSPF命令 '{command}' 时出错: {str(e)}"
            print(f"\n错误: {error_message}")
            
            if not log_recorded:
                log_recorded = True
                system_info = get_system_info_for_log(ssh, device_name)
                write_log.write_log("Failed", executed_commands, system_info, error_message, 
                                  device_name=device_name)
            
            return "Failed", error_message
    
    return "succeed", None

def config_dual_devices_vxlan(dual_params):
    """同时配置两台设备的VXLAN参数"""
    # 提取共同参数
    common_params = dual_params.get('common', {})
    vni = common_params.get('vni', '10000')
    vlan_id = common_params.get('vlan_id', '100')
    
    # 初始化连通性测试状态变量
    vxlan_connectivity_status = "not_tested"
    vxlan_tunnel_status = "unknown"

    # 提取接口信息
    interface_params = dual_params.get('interfaces', {})
    dut1_ac_interface = interface_params.get('dut1_ac_interface', '')
    dut1_uplink_interface = interface_params.get('dut1_uplink_interface', '')
    dut2_ac_interface = interface_params.get('dut2_ac_interface', '')
    dut2_uplink_interface = interface_params.get('dut2_uplink_interface', '')
    
    # 检查AC接口参数（必须）
    if not dut1_ac_interface or not dut2_ac_interface:
        print("错误: 必须提供两台设备的AC接口参数 dut1_ac_interface 和 dut2_ac_interface")
        return "Failed", {}, {}, "缺少AC接口参数", {}

    # 创建设备参数
    devices = []
    for idx, device_key in enumerate(['dut1', 'dut2']):
        if device_key not in dual_params:
            print(f"错误: 缺少设备 {device_key} 的参数")
            return "Failed", {}, {}, f"缺少设备 {device_key} 的参数", {}
        
        device_params = dual_params[device_key]
        
        # 添加公共VXLAN参数
        device_params['vni'] = vni
        device_params['vlan_id'] = vlan_id
        
        # 为设备分配接口
        if device_key == 'dut1':
            device_params['ac_interface'] = dut1_ac_interface
            device_params['uplink_interface'] = dut1_uplink_interface
        else:
            device_params['ac_interface'] = dut2_ac_interface
            device_params['uplink_interface'] = dut2_uplink_interface
        
        # 根据设备1/2分配不同的本地和远程IP地址（使用固定的Loopback地址）
        if device_key == 'dut1':
            device_params['local_ip'] = '10.1.1.1'  # DUT1固定使用10.1.1.1作为Loopback地址
            device_params['remote_ip'] = '20.1.1.1'  # DUT1的远程地址指向DUT2的Loopback地址
            device_params['vsi_name'] = f'vsi{vni}'
        else:
            device_params['local_ip'] = '20.1.1.1'  # DUT2固定使用20.1.1.1作为Loopback地址
            device_params['remote_ip'] = '10.1.1.1'  # DUT2的远程地址指向DUT1的Loopback地址
            device_params['vsi_name'] = f'vsi{vni}'
        
        devices.append(device_params)
    
    # 保存两台设备的执行命令和系统信息
    all_executed_commands = {}
    all_system_info = {}
    final_status = "succeed"
    error_messages = []
    
    # 依次配置每台设备
    for i, device_params in enumerate(devices):
        temp_id = ['dut1', 'dut2'][i]
        print(f"\n开始配置设备 {temp_id}...")
        
        try:
            # 登录设备并配置全局VXLAN参数
            status, ssh_conn, executed_commands, error_message, device_system_info = ssh_system_view(device_params)
            
            if status == "Failed" or ssh_conn is None:
                final_status = "Failed"
                device_name = device_params.get('device_name', temp_id)
                error_messages.append(f"{device_name}: {error_message}")
                
                # 记录日志并退出
                result_format = {}
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
            
            # 处理AC接口参数
            ac_interface = device_params['ac_interface']
            uplink_interface = device_params.get('uplink_interface', '')
            
            # AC接口映射
            mapped_ac_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [ac_interface], ssh_conn)
            if not mapped_ac_interfaces:
                raise Exception(f"无法映射AC接口名称: {ac_interface}")
                
            ac_interface = mapped_ac_interfaces[0]
            
            # 配置AC接口VXLAN
            print(f"\n配置AC接口: {ac_interface}")
            result, error_message = config_interface_vxlan(
                ssh_conn, ac_interface,
                all_interfaces=all_interfaces,
                vlan_id=vlan_id,
                vni=vni,
                vsi_name=device_params.get('vsi_name', f'vsi{vni}'),
                executed_commands=executed_commands,
                device_name=device_name
            )
            
            if result == "Failed":
                raise Exception(f"配置AC接口VXLAN失败: {error_message}")
            
            # 配置上行接口（如果提供）
            if uplink_interface:
                print(f"\n配置上行接口: {uplink_interface}")
                
                # 上行接口映射
                mapped_uplink_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [uplink_interface], ssh_conn)
                if not mapped_uplink_interfaces:
                    raise Exception(f"无法映射上行接口名称: {uplink_interface}")
                    
                uplink_interface = mapped_uplink_interfaces[0]
                
                # 配置上行接口（配置IP地址和OSPF协议）
                # 为每台设备自动分配IP地址：DUT1使用172.16.1.1，DUT2使用172.16.1.2
                device_index = i + 1  # i=0对应DUT1，i=1对应DUT2
                
                result, error_message = config_uplink_interface(
                    ssh_conn, uplink_interface,
                    all_interfaces=all_interfaces,
                    vlan_id=vlan_id,
                    executed_commands=executed_commands,
                    device_name=device_name,
                    device_index=device_index
                )
                
                if result == "Failed":
                    raise Exception(f"配置上行接口失败: {error_message}")
                
                # 配置Loopback接口
                result, error_message = config_loopback_interface(
                    ssh_conn, executed_commands=executed_commands, device_name=device_name, device_index=device_index
                )
                
                if result == "Failed":
                    raise Exception(f"配置Loopback接口失败: {error_message}")
                
                # 配置OSPF进程
                result, error_message = config_ospf_process(
                    ssh_conn, executed_commands=executed_commands, device_name=device_name
                )
                
                if result == "Failed":
                    raise Exception(f"配置OSPF进程失败: {error_message}")
            else:
                print(f"\n未提供上行接口，跳过上行接口配置")
            
            # 保存命令和系统信息
            all_executed_commands[device_name] = executed_commands
            all_system_info[device_name] = device_system_info.get(device_name, "")

            # 如果是第一台设备完成配置
            if i == 0:
                print(f"第一台设备 {device_name} 配置完成，等待第二台设备配置...")

            # 如果是第二台设备配置完成，检查VXLAN隧道状态 
            if i == 1:
                print("\n第二台设备配置完成，等待检查VXLAN隧道状态...")
                try:
                    is_up, status = monitor_vxlan_tunnel_status(ssh_conn, device_name, vni, timeout_minutes=1, check_interval=5)
                    
                    # 记录VXLAN隧道状态
                    vxlan_tunnel_status = status
                    
                    print(f"VXLAN隧道状态检查结果: {vxlan_tunnel_status}")
                    
                    # 如果VXLAN隧道状态为UP，执行连通性测试
                    if is_up:    
                        print("\nVXLAN隧道状态为UP，等待3秒后开始执行连通性测试...")
                        time.sleep(3)
                        
                        # 执行连通性测试
                        connectivity_result = test_vxlan_connectivity(ssh_conn, vlan_id)
                        vxlan_connectivity_status = connectivity_result
                        
                        print(f"VXLAN连通性测试结果: {connectivity_result}")
                        
                    else:
                        print("\nVXLAN隧道状态为DOWN，跳过连通性测试")
                        vxlan_connectivity_status = "failed"
                        
                except Exception as e:
                    print(f"检查VXLAN隧道状态时出错: {str(e)}")
                    vxlan_tunnel_status = "unknown"
                    vxlan_connectivity_status = "error"

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
                
            # 转换所有已保存设备的命令记录格式
            result_format = {}
            for dk, commands in all_executed_commands.items():
                if not commands:
                    continue
                    
                full_output = []
                for cmd_entry in commands:
                    if isinstance(cmd_entry, dict):
                        output = cmd_entry.get("output", "")
                        if output:
                            full_output.append(output)
                if full_output:
                    result_format[dk] = "\n".join(full_output)
            
            # 记录日志 - 配置失败时也包含所有已配置设备的信息
            log_path = write_log.write_log(
                final_status, 
                result_format, 
                all_system_info, 
                "\n".join(error_messages)
            )
            
            if log_path:
                print(f"\n日志已保存至: {log_path}")
            sys.exit(1)
    
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
        "\n".join(error_messages) if error_messages else None, 
        vxlan_tunnel_status=vxlan_tunnel_status,
        vxlan_connectivity=vxlan_connectivity_status
    )

    print(f"\n双设备VXLAN配置完成，状态: {final_status}")
    print(f"VXLAN隧道状态: {vxlan_tunnel_status}")
    print(f"连通性测试: {vxlan_connectivity_status}")

    if log_path:
        print(f"日志已保存至: {log_path}")

    return final_status, all_executed_commands, all_system_info, vxlan_connectivity_status, vxlan_tunnel_status

def monitor_vxlan_tunnel_status(ssh_connection, device_name, vni, timeout_minutes=2, check_interval=5):
    """
    监控VXLAN隧道状态，定期检查直到发现UP状态或超时
    
    Args:
        ssh_connection: SSH连接对象
        device_name: 设备名称
        vni: VXLAN网络标识符
        timeout_minutes: 超时时间(分钟)
        check_interval: 检查间隔(秒)
        
    Returns:
        tuple: (bool是否发现UP状态, str隧道状态详情)
    """
    print(f"\n开始监控VXLAN隧道状态，将在{timeout_minutes}分钟内每{check_interval}秒检查一次...")
    
    # 计算超时时间点
    start_time = time.time()
    end_time = start_time + (timeout_minutes * 60)
    
    # 开始循环检查
    check_count = 0
    while time.time() < end_time:
        check_count += 1
        remaining_seconds = int(end_time - time.time())
        remaining_minutes = remaining_seconds // 60
        remaining_seconds %= 60
        
        print(f"\n检查 #{check_count} - 剩余时间: {remaining_minutes}分{remaining_seconds}秒")
        
        try:
            # 获取VXLAN隧道信息
            output = ssh_connection.send_command(
                f"display vxlan tunnel", 
                strip_prompt=False,
                strip_command=False,
                delay_factor=2,
                expect_string=r"[>\]]"
            )
            
            print(f"VXLAN隧道状态:\n{output}")
            
            # 改进的VXLAN隧道状态分析逻辑
            lines = output.strip().split('\n')
            tunnel_count_up = 0
            tunnel_count_total = 0
            tunnel_details = []
            
            for line in lines:
                line_upper = line.upper()
                
                # 解析统计信息：Total tunnels: 1 (0 up, 1 down, 0 defect, 0 blocked)
                if "TOTAL TUNNELS:" in line_upper and "(" in line and "UP" in line_upper:
                    import re
                    # 提取 (x up, y down, ...) 格式中的up数量
                    match = re.search(r'\((\d+)\s+up', line_upper)
                    if match:
                        tunnel_count_up = int(match.group(1))
                        print(f"解析到UP状态隧道数量: {tunnel_count_up}")
                
                # 解析具体隧道状态行：Tun100 20.1.1.1 10.1.1.1 Down Manual Disabled -
                elif line.strip() and not line_upper.startswith("VXLAN") and not line_upper.startswith("TOTAL") and not line_upper.startswith("TUNNEL NAME"):
                    # 检查是否是隧道详情行（包含源IP、目标IP、状态等）
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        # 第4个字段通常是状态（Up/Down）
                        tunnel_name = parts[0] if parts else "unknown"
                        tunnel_state = parts[3] if len(parts) > 3 else "unknown"
                        tunnel_details.append(f"{tunnel_name}: {tunnel_state}")
                        
                        if tunnel_state.upper() == "UP":
                            tunnel_count_up += 1
                        tunnel_count_total += 1
            
            # 输出详细的解析结果
            if tunnel_details:
                print(f"隧道详情: {', '.join(tunnel_details)}")
            
            print(f"UP状态隧道数量: {tunnel_count_up}, 总隧道数量: {tunnel_count_total}")
            
            # 判断是否有UP状态的隧道
            if tunnel_count_up > 0:
                return True, "UP"
            
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"检查VXLAN隧道状态时出错: {str(e)}")
            time.sleep(check_interval)
    
    print(f"\n监控超时: 在{timeout_minutes}分钟内未发现UP状态的VXLAN隧道")
    return False, "DOWN"

def test_vxlan_connectivity(ssh_connection, vlan_id):
    """测试VXLAN连通性 - 使用ping测试Loopback地址连通性"""
    try:
        # 使用ping测试VXLAN隧道连通性
        # 从第二台设备(DUT2)的Loopback地址ping第一台设备(DUT1)的Loopback地址
        
        # 执行ping命令，增加超时时间和更灵活的提示符匹配
        print("正在测试VXLAN连通性: ping -a 20.1.1.1 10.1.1.1")
        output = ssh_connection.send_command(
            "ping -a 20.1.1.1 10.1.1.1", 
            strip_prompt=False,
            strip_command=False,
            delay_factor=5,  # 增加延迟因子
            max_loops=2000   # 增加最大循环次数以适应较长的ping响应时间
        )
        
        print(f"Ping测试结果:\n{output}")
        
        # 分析ping结果
        output_lower = output.lower()
        if "bytes from" in output_lower or "reply from" in output_lower:
            # 有回复，说明连通性正常
            return "success"
        elif "timeout" in output_lower or "request timeout" in output_lower:
            # 超时，连通性失败
            return "timeout"
        elif "unreachable" in output_lower:
            # 不可达，连通性失败
            return "unreachable"
        elif "100% packet loss" in output_lower or "100% loss" in output_lower:
            # 100%丢包，连通性失败
            return "packet_loss"
        elif "0% packet loss" in output_lower or "0% loss" in output_lower:
            # 0%丢包，连通性正常
            return "success"
        else:
            # 其他情况，可能是ping命令格式问题或网络问题
            return "failed"
            
    except Exception as e:
        print(f"VXLAN连通性测试出错: {str(e)}")
        return "error"

def main():
    """主函数"""
    global log_recorded
    log_recorded = False
    
    try:
        if len(sys.argv) != 2:
            # 显示帮助信息
            print("使用方法:")
            print('python vxlan_config_test.py {"hostip":"192.168.56.10,192.168.56.11","username":"admin",')
            print('                           "password":"admin123","vni":"10000",')
            print('                           "vlan_id":"100",')
            print('                           "dut1_ac_interface":"GigabitEthernet1/0/1","dut1_uplink_interface":"GigabitEthernet1/0/2",')
            print('                           "dut2_ac_interface":"GigabitEthernet1/0/1","dut2_uplink_interface":"GigabitEthernet1/0/2"}')
            
            print("\n参数说明：")
            print("  hostip: 设备IP地址，用逗号分隔多个设备")
            print("  username: 设备用户名（两台设备使用相同用户名，或用逗号分隔不同用户名）")
            print("  password: 设备密码（两台设备使用相同密码，或用逗号分隔不同密码）")
            print("  vni: VXLAN网络标识符，默认为10000")
            print("  vlan_id: VLAN ID，默认为100")
            print("  dut1_ac_interface: 第一台设备的AC接口名称（接入接口）")
            print("  dut1_uplink_interface: 第一台设备的上行接口名称（互联接口，可选）")
            print("  dut2_ac_interface: 第二台设备的AC接口名称（接入接口）")
            print("  dut2_uplink_interface: 第二台设备的上行接口名称（互联接口，可选）")
            print("\n自动配置功能（无需用户输入）：")
            print("  - 自动使用Loopback地址作为VXLAN隧道源/目标地址（DUT1: 10.1.1.1, DUT2: 20.1.1.1）")
            print("  - 自动为上行接口配置IP地址（DUT1: 172.16.1.1/24, DUT2: 172.16.1.2/24）")
            print("  - 自动在Loopback接口启用OSPF协议（使用已有IP地址）")
            print("  - 自动配置OSPF协议（进程ID=1，区域=0）")
            print("  - 在上行接口和Loopback接口上启用OSPF邻接，实现Loopback连通性")
            
            sys.exit(1)

        try:
            # 处理输入参数
            json_str = sys.argv[1]
            params = json.loads(json_str)

            # 解析参数后立即记录Running状态的日志       
            write_log.write_log("Running", {}, {})
            
            # 检查是否包含必要的逗号分隔参数
            if "hostip" in params and "," in params["hostip"]:
                # 处理双设备配置
                print("\n使用双设备模式配置VXLAN")
                
                # 解析逗号分隔的参数
                hostips = [ip.strip() for ip in params["hostip"].split(",")]
                
                # 用户名和密码处理 - 支持单个值或逗号分隔的值
                username_input = params.get("username", "admin")
                password_input = params.get("password", "admin")
                
                # 如果用户名包含逗号，则按逗号分隔；否则两台设备使用相同的用户名
                if "," in username_input:
                    usernames = [user.strip() for user in username_input.split(",")]
                else:
                    usernames = [username_input, username_input]  # 两台设备使用相同的用户名
                
                # 如果密码包含逗号，则按逗号分隔；否则两台设备使用相同的密码
                if "," in password_input:
                    passwords = [pwd.strip() for pwd in password_input.split(",")]
                else:
                    passwords = [password_input, password_input]  # 两台设备使用相同的密码
                
                # 处理dut1_local_ip和dut2_local_ip参数 - 现在使用固定的Loopback地址
                # 不再需要用户输入，直接使用默认的Loopback地址
                dut1_local_ip = "10.1.1.1"  # DUT1固定使用10.1.1.1
                dut2_local_ip = "20.1.1.1"  # DUT2固定使用20.1.1.1
                
                print("自动使用默认Loopback地址: DUT1=10.1.1.1, DUT2=20.1.1.1")
                
                # 构建标准化的双设备参数
                dual_params = {
                    "dut1": {
                        "hostip": hostips[0],
                        "username": usernames[0],
                        "password": passwords[0],
                        "local_ip": dut1_local_ip,
                        "remote_ip": dut2_local_ip
                    },
                    "dut2": {
                        "hostip": hostips[1],
                        "username": usernames[1],
                        "password": passwords[1],
                        "local_ip": dut2_local_ip,
                        "remote_ip": dut1_local_ip
                    },
                    "common": {
                        "vni": params.get("vni", "10000"),
                        "vlan_id": params.get("vlan_id", "100")
                    },
                    "interfaces": {
                        "dut1_ac_interface": params.get("dut1_ac_interface", ""),
                        "dut1_uplink_interface": params.get("dut1_uplink_interface", ""),
                        "dut2_ac_interface": params.get("dut2_ac_interface", ""),
                        "dut2_uplink_interface": params.get("dut2_uplink_interface", ""),
                        # 保持向后兼容性
                        "dut1_interface": params.get("dut1_interface", ""),
                        "dut2_interface": params.get("dut2_interface", "")
                    }
                }
                
                # 检查接口参数是否存在 - 支持新格式和旧格式
                interface_params = dual_params["interfaces"]
                
                # 优先使用新格式参数（AC接口和上行接口）
                if interface_params["dut1_ac_interface"] and interface_params["dut1_uplink_interface"] and \
                   interface_params["dut2_ac_interface"] and interface_params["dut2_uplink_interface"]:
                    print("使用新格式接口参数：AC接口和上行接口")
                # 兼容旧格式参数（单接口）
                elif interface_params["dut1_interface"] and interface_params["dut2_interface"]:
                    print("使用旧格式接口参数，将作为AC接口处理")
                    # 将旧格式参数复制到新格式中作为AC接口
                    interface_params["dut1_ac_interface"] = interface_params["dut1_interface"]
                    interface_params["dut2_ac_interface"] = interface_params["dut2_interface"]
                    # 上行接口留空，只配置AC接口
                    interface_params["dut1_uplink_interface"] = ""
                    interface_params["dut2_uplink_interface"] = ""
                else:
                    print("错误: 必须提供接口参数。")
                    print("新格式: dut1_ac_interface, dut1_uplink_interface, dut2_ac_interface, dut2_uplink_interface")
                    print("旧格式: dut1_interface, dut2_interface（仅作为AC接口）")
                    sys.exit(1)
                
                # 配置双设备VXLAN
                print("\n启动双设备VXLAN配置...")
                status, executed_commands, system_info, connectivity_status, tunnel_status = config_dual_devices_vxlan(dual_params)
                
                if status == "Failed":
                    print(f"\n双设备VXLAN配置失败")
                    sys.exit(1)
                else:
                    print("\n双设备VXLAN配置完成!")
                    print(f"隧道状态: {tunnel_status}")
                    print(f"连通性状态: {connectivity_status}")
                
            else:
                # 单设备配置逻辑
                print("\n使用单设备模式配置VXLAN...")
                
                # 构建单设备参数 - 使用固定的Loopback地址
                device_params = {
                    "hostip": params.get("hostip", ""),
                    "username": params.get("username", "admin"),
                    "password": params.get("password", "admin"),
                    "vni": params.get("vni", "10000"),
                    "vlan_id": params.get("vlan_id", "100"),
                    "local_ip": "10.1.1.1",  # 单设备模式固定使用10.1.1.1作为本地地址
                    "remote_ip": "20.1.1.1",  # 单设备模式固定使用20.1.1.1作为远程地址
                    "interface": params.get("interface", ""),
                    "vsi_name": params.get("vsi_name", f"vsi{params.get('vni', '10000')}")
                }
                
                print("单设备模式自动使用默认地址: local_ip=10.1.1.1, remote_ip=20.1.1.1")
                
                # 检查必要参数
                if not device_params["interface"]:
                    print("错误: 单设备模式必须提供interface参数")
                    sys.exit(1)
                
                # 执行单设备配置
                print("\n开始配置VXLAN全局参数...")
                status, ssh_conn, executed_commands, error_message, device_system_info = ssh_system_view(device_params)
                
                if status == "Failed" or ssh_conn is None:
                    final_status = "Failed"
                    device_name = device_params.get('device_name', "unknown_device")
                    error_messages = [f"{device_name}: {error_message}"]
                    
                    all_system_info = device_system_info if device_system_info else {}
                    
                    # 记录日志并退出
                    result_format = {}
                    log_path = write_log.write_log(final_status, result_format, all_system_info, 
                                "\n".join(error_messages))
                    if log_path:
                        print(f"\n日志已保存至: {log_path}")
                    sys.exit(1)
                
                # 获取设备名
                device_name = device_params.get('device_name', "device1")
                
                # 获取系统信息
                system_info = get_system_info_for_log(ssh_conn, device_name)
                
                # 获取接口信息
                all_interfaces = get_cached_interfaces(ssh_conn)
                
                # 配置接口
                interface = device_params["interface"]
                
                # 配置接口VXLAN参数
                print(f"\n配置接口 {interface} 的VXLAN参数...")
                
                result, error_message = config_interface_vxlan(
                    ssh_conn, interface,
                    all_interfaces=all_interfaces,
                    vlan_id=device_params["vlan_id"],
                    vni=device_params["vni"],
                    vsi_name=device_params.get("vsi_name", f'vsi{device_params["vni"]}'),
                    executed_commands=executed_commands,
                    device_name=device_name
                )
                
                if result == "Failed":
                    print(f"\n错误: 配置接口 {interface} VXLAN参数失败: {error_message}")
                    
                    result_format = {}
                    full_output = []
                    for cmd_entry in executed_commands:
                        if isinstance(cmd_entry, dict):
                            output = cmd_entry.get("output", "")
                            if output:
                                full_output.append(output)
                    
                    if full_output:
                        result_format[device_name] = "\n".join(full_output)
                    
                    log_path = write_log.write_log(
                        "Failed", result_format, {device_name: system_info}, error_message
                    )
                    
                    if log_path:
                        print(f"\n日志已保存至: {log_path}")
                    
                    if ssh_conn:
                        ssh_conn.disconnect()
                    sys.exit(1)
                
                # 断开连接
                if ssh_conn:
                    ssh_conn.disconnect()
                
                # 记录单设备配置日志
                print("\n单设备VXLAN配置完成!")
                
                # 格式化命令输出为单个字符串
                result_format = {}
                full_output = []
                for cmd_entry in executed_commands:
                    if isinstance(cmd_entry, dict):
                        output = cmd_entry.get("output", "")
                        if output:
                            full_output.append(output)
                
                if full_output:
                    result_format[device_name] = "\n".join(full_output)
                
                # 记录成功日志
                log_path = write_log.write_log(
                    "Completed", result_format, {device_name: system_info}, None
                )
                
                print(f"\n日志已保存至: {log_path}")

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