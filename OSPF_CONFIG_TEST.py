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
cached_interfaces = {}  # 使用设备地址作为键，接口列表作为值

# 添加专门提取设备名的函数
def extract_device_name(ssh):
    """从SSH提示符中提取设备名，优先使用<设备名>格式"""
    if not ssh:
        print("警告: SSH连接为空，无法提取设备名称，使用默认值'config'")
        return "config"
    
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
                print(f"成功从[设备名>格式提取到设备名: '{device_name}'")
                return device_name
            except Exception as e:
                print(f"从[设备名>格式提取设备名失败: {str(e)}")
        
        # 尝试直接使用提示符作为设备名 - 去除特殊字符
        else:
            clean_prompt = prompt.strip('<>[]')
            if clean_prompt:
                print(f"未找到标准格式，尝试使用清理后的提示符: '{clean_prompt}'")
                if ':' in clean_prompt:
                    # 如果包含冒号，取冒号前的部分
                    device_name = clean_prompt.split(':')[0]
                    print(f"从提示符中提取设备名: '{device_name}'")
                    return device_name
                return clean_prompt
        
        # 如果所有方法都失败，使用config作为默认值
        print(f"警告: 无法从提示符'{prompt}'提取设备名，使用默认值'config'")
        return "config"
    except Exception as e:
        print(f"提取设备名时出现意外错误: {str(e)}")
        return "config"

# 添加缓存函数，避免重复执行display interface命令
def get_cached_interfaces(ssh):
    """获取接口信息，优先使用缓存"""
    global cached_interfaces
    
    # 获取设备IP作为缓存键
    device_id = ssh.host if hasattr(ssh, 'host') else "unknown"
    
    # 检查缓存
    if device_id in cached_interfaces:
        print(f"使用缓存的接口列表，跳过执行: display interface brief | include UP|DOWN|ADM")
        return cached_interfaces[device_id]
    
    # 如果缓存中没有，获取接口列表并存入缓存
    interfaces = interface_config.get_device_interfaces(ssh)
    cached_interfaces[device_id] = interfaces
    
    return interfaces

def get_system_info_for_log(ssh_connection, device_name):
    """获取用于日志记录的系统信息，直接返回版本信息字符串"""
    try:
        ssh_connection.clear_buffer()
        version_output = get_system_info.get_system_info(ssh_connection)
        
        # 清理system_info中的多余设备名称
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
                # 移除多余的提示符和换行
                cleaned_value = re.sub(r'\n*<[^>]+>\n*', '', value)
                cleaned_value = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned_value)
                # 移除display version命令回显
                cleaned_value = re.sub(r'display\s+version\n*', '', cleaned_value, flags=re.IGNORECASE)
                # 移除多余的换行符
                cleaned_value = re.sub(r'\n+', '\n', cleaned_value)
                cleaned_value = cleaned_value.strip()
                if cleaned_value:  # 只保留非空内容
                    cleaned_info[key] = cleaned_value
        return cleaned_info
    elif isinstance(system_info, str):
        # 清理字符串格式
        cleaned = re.sub(r'\n*<[^>]+>\n*', '', system_info)
        cleaned = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned)
        # 移除display version命令回显
        cleaned = re.sub(r'display\s+version\n*', '', cleaned, flags=re.IGNORECASE)
        # 移除多余的换行符
        cleaned = re.sub(r'\n+', '\n', cleaned)
        
        return cleaned.strip()
    else:
        return system_info

def ssh_system_view(device_params):
    """
    登录设备并执行system-view命令，配置OSPF全局参数
    """
    global log_recorded  # 添加全局声明，使函数内可修改全局变量
    
    ssh = login_args.run_script(device_params)
    
    if not ssh:
        # 获取login_args.py已经打印的错误信息作为日志
        error_message = f"无法登录设备 {device_params.get('hostip', 'unknown')}"
        
        # 更新日志状态为Failed
        log_path = write_log.write_log("Failed", [], {}, error_message)
        if log_path:
            print(f"\n日志已保存至: {log_path}")
        
        return "Failed", None, [], error_message
    
    executed_commands = []
    
    # 获取设备提示符并提取设备名 - 只在这里提取一次
    try:
        prompt = ssh.find_prompt()
        print(f"登录成功，原始设备提示符: '{prompt}'")
        device_name = extract_device_name(ssh)
        print(f"最终使用的设备名称: '{device_name}'")
        # 保存到device_params中，便于在其他地方使用
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
            
            # 断开连接并返回失败状态
            if ssh:
                ssh.disconnect()
            return "Failed", None, executed_commands, error_message
        
        # 获取用户指定的进程ID和其他OSPF参数
        ospf_process_id = device_params.get('ospf_process_id', '100')
        ospf_area = device_params.get('ospf_area', '0.0.0.0')
        ospf_router_id = device_params.get('ospf_router_id', '')
        ospf_stack = device_params.get('ospf_stack', 'IPv4&IPv6')
        
        # OSPF全局配置命令
        ospf_commands = []
        
        # 配置IPv4 OSPF - IPv4使用ospf 100 router-id x.x.x.x一行配置
        if ospf_stack in ['IPv4', 'IPv4&IPv6']:
            # 如果有hostip，将router-id与ospf命令合并在一行
            if 'hostip' in device_params and device_params['hostip']:
                ospf_router_id = device_params['hostip'].strip()
                ospf_commands.append(f"ospf {ospf_process_id} router-id {ospf_router_id}")
            else:
                # 无router-id情况
                ospf_commands.append(f"ospf {ospf_process_id}")
            
            # OSPF全局配置相关命令可在这里添加
            
            # 退出OSPF视图
            ospf_commands.append("quit")  # 从OSPF视图退出到系统视图
                
        # 配置IPv6 OSPF - IPv6使用ospfv3 100然后router-id x.x.x.x分两行配置
        if ospf_stack in ['IPv6', 'IPv4&IPv6']:
            ospf_commands.append(f"ospfv3 {ospf_process_id}")
            
            # 直接使用设备IP作为Router-ID，不再使用手动设置的router-id
            if 'hostip' in device_params and device_params['hostip']:
                ospf_router_id = device_params['hostip'].strip()
                ospf_commands.append(f"router-id {ospf_router_id}")
            
            # OSPFv3全局配置相关命令可在这里添加
            
            # 退出OSPFv3视图
            ospf_commands.append("quit")  # 从OSPFv3视图退出到系统视图
        
        # 执行OSPF全局配置命令
        for command in ospf_commands:
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
                
                # 先获取系统信息，再记录日志
                if not log_recorded:
                    log_recorded = True
                    system_info = {}
                    
                    try:
                        version_output = get_system_info.get_system_info(ssh)
                        system_info[device_name] = version_output or "未能获取到版本信息" 
                    except Exception as e:
                        system_info[device_name] = f"获取版本信息失败: {str(e)}"
                    
                    write_log.write_log("Failed", executed_commands, system_info, error_message, 
                                      device_name=device_name, file_suffix="status")
                
                # 断开连接并返回失败状态
                if ssh:
                    ssh.disconnect()
                return "Failed", None, executed_commands, error_message
            
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
        
        # 捕获并记录错误
        error_msg = f"配置执行失败: {str(e)}"
        system_info_dict = {}
        
        if device_name:
            try:
                version_output = get_system_info.get_system_info(ssh) if ssh else "未连接"
                system_info_dict[device_name] = version_output
            except:
                system_info_dict[device_name] = "获取版本信息失败"
        
        # 记录日志
        log_path = write_log.write_log("Failed", executed_commands or {}, system_info_dict, error_msg, file_suffix="dual_ospf_status")
        
        # 打印日志保存路径
        if log_path:
            print(f"\n日志已保存至: {log_path}")
        
        if ssh:
            ssh.disconnect()
        sys.exit(1)

        return "Failed", None, [], ""

def config_interface_ospf(ssh, interface, all_interfaces=None, ospf_process_id='100', ospf_area='0.0.0.0', ospf_cost='10', 
                         ospf_networktype=None, ospf_stack='IPv4&IPv6', executed_commands=None, 
                         skip_vlan_creation=False, device_name="config"):
    """配置接口的OSPF参数"""
    global log_recorded
    
    # 使用传入的接口列表或从缓存获取
    if all_interfaces is None:
        all_interfaces = get_cached_interfaces(ssh)
    
    # 映射接口编号到实际接口名
    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh)
    if mapped_interfaces:
        interface = mapped_interfaces[0]
        print(f"映射后的接口名: {interface}")

    # 现在使用映射后的接口名进入接口模式
    cmd = f"interface {interface}"
    print(f"执行命令: {cmd}")    

    # 检查接口模式并切换到route模式（如果是bridge模式）
    is_loopback = interface_config.is_loopback_interface(interface)
    if not is_loopback:
        current_mode = interface_config.check_interface_mode(ssh, interface)
        if current_mode and current_mode.lower() != "route":
            print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
            switch_result = interface_config.switch_interface_to_route_mode(ssh, interface, executed_commands)
            if switch_result is False:
                print(f"\n错误: 将接口 {interface} 切换到route模式失败")
                if ssh:
                    ssh.disconnect()
                sys.exit(1)
        else:
            print(f"接口 {interface} 已经是route模式，跳过切换")
    else:
        print(f"接口 {interface} 是环回口，跳过模式检查")

    # 添加1秒等待
    print("等待2秒以确保设备响应...")
    time.sleep(2)

    # 先检查接口类型，再进入接口模式
    is_loopback = interface_config.is_loopback_interface(interface)
    print(f"接口类型检查: {interface} {'是' if is_loopback else '不是'}环回口")    
    
    # 进入接口模式
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, interface, executed_commands, skip_vlan_creation)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义OSPF接口命令
    ospf_commands = []

    # 根据ospf_stack参数配置OSPF
    if ospf_stack in ['IPv4', 'IPv4&IPv6']:
        # 启用IPv4 OSPF - 在接口模式下配置
        ospf_commands.append(f"ospf {ospf_process_id} area {ospf_area}")
        
        # 配置OSPF网络类型（如果指定）
        if ospf_networktype and not is_loopback:
            ospf_commands.append(f"ospf network-type {ospf_networktype}")
        
        # 配置OSPF接口开销
        if ospf_cost:
            ospf_commands.append(f"ospf cost {ospf_cost}")

    if ospf_stack in ['IPv6', 'IPv4&IPv6']:
        # 启用IPv6 OSPF（OSPFv3）- 在接口模式下配置
        ospf_commands.append(f"ospfv3 {ospf_process_id} area {ospf_area}")
        
        # 配置OSPFv3网络类型（如果指定）
        if ospf_networktype and not is_loopback:
            ospf_commands.append(f"ospfv3 network-type {ospf_networktype}")
        
        # 配置OSPFv3接口开销
        if ospf_cost:
            ospf_commands.append(f"ospfv3 cost {ospf_cost}")

    # 添加退出接口配置的命令
    ospf_commands.append("quit")
    
    # 使用interface_config的批量发送命令功能
    status, ospf_executed_commands, error_message = interface_config.execute_commands(
        ssh, ospf_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 将OSPF命令结果合并到主命令列表
    if ospf_executed_commands and isinstance(ospf_executed_commands, list):
        for cmd in ospf_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name, file_suffix="status")
    
    return status, error_message

def config_dual_devices(dual_params):
    """同时配置两台设备的OSPF参数"""
    # 提取共同参数
    common_params = dual_params.get('common', {})
    ospf_process_id = common_params.get('ospf_process_id', '100')
    ospf_area = common_params.get('ospf_area', '0.0.0.0')
    ospf_stack = common_params.get('ospf_stack', 'IPv4&IPv6')
    
    # 初始化PING测试状态变量
    overall_ping_status = {
        "IPv4_PING_Status": "not_tested",
        "IPv6_PING_Status": "not_tested"
    }
    ospf_peer_status = "unknown"  # OSPF邻居状态

    # 提取接口信息
    interface_params = dual_params.get('interfaces', {})
    dut1_interface = interface_params.get('dut1_interface', '')
    dut2_interface = interface_params.get('dut2_interface', '')
    
    if not dut1_interface or not dut2_interface:
        print("错误: 必须提供两台设备的接口参数 dut1_interface 和 dut2_interface")
        return "Failed", {}, {}, "缺少接口参数", {}

    # 创建设备参数
    devices = []
    for idx, device_key in enumerate(['dut1', 'dut2']):
        if device_key not in dual_params:
            print(f"错误: 缺少设备 {device_key} 的参数")
            return "Failed", {}, {}, f"缺少设备 {device_key} 的参数", {}
        
        device_params = dual_params[device_key]
        
        # 添加公共OSPF参数
        device_params['ospf_process_id'] = ospf_process_id
        device_params['ospf_area'] = ospf_area
        device_params['ospf_stack'] = ospf_stack
        
        # 为设备分配接口
        interface = dut1_interface if device_key == 'dut1' else dut2_interface
        device_params['interface'] = interface
        
        # 根据设备1/2分配不同IP地址
        if device_key == 'dut1':
            device_params['ip_address'] = '172.16.1.1'
            device_params['mask'] = '24'
            device_params['ipv6_address'] = '2025:172:16:1::1'
            device_params['ipv6_prefix'] = '64'
        else:
            device_params['ip_address'] = '172.16.1.2'
            device_params['mask'] = '24'
            device_params['ipv6_address'] = '2025:172:16:1::2'
            device_params['ipv6_prefix'] = '64'
        
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
        
        # 根据ospf_stack决定是否配置IPv4和IPv6
        has_ipv4 = ospf_stack in ['IPv4', 'IPv4&IPv6']
        has_ipv6 = ospf_stack in ['IPv6', 'IPv4&IPv6']
        
        if not has_ipv4:
            device_params.pop('ip_address', None)
            device_params.pop('mask', None)
        
        if not has_ipv6:
            device_params.pop('ipv6_address', None)
            device_params.pop('ipv6_prefix', None)
        
        try:
            # 登录设备并配置全局OSPF参数（注意：这里接收5个返回值）
            status, ssh_conn, executed_commands, error_message, device_system_info = ssh_system_view(device_params)
            
            if status == "Failed" or ssh_conn is None:
                final_status = "Failed"
                device_name = device_params.get('device_name', temp_id)
                error_messages.append(f"{device_name}: {error_message}")
                
                # 记录日志并退出
                result_format = {}
                log_path = write_log.write_log(final_status, result_format, all_system_info, 
                            "\n".join(error_messages), file_suffix="dual_ospf_status")
                if log_path:
                    print(f"\n日志已保存至: {log_path}")
                sys.exit(1)
            
            # 获取设备名 - 使用从提示符提取的真实设备名
            device_name = device_params.get('device_name', f"device{i+1}")
            
            # 更新系统信息字典
            all_system_info.update(device_system_info)
            
            # 获取接口信息
            all_interfaces = get_cached_interfaces(ssh_conn)
            
            # 处理接口参数
            interfaces = [device_params['interface']]
            ip_address = [device_params.get('ip_address', '')] if 'ip_address' in device_params else []
            mask = [device_params.get('mask', '')] if 'mask' in device_params else []
            ipv6_address = [device_params.get('ipv6_address', '')] if 'ipv6_address' in device_params else []
            ipv6_prefix = [device_params.get('ipv6_prefix', '')] if 'ipv6_prefix' in device_params else []
            
            # 获取通用参数
            ospf_cost = common_params.get('ospf_cost', '10')
            ospf_networktype = common_params.get('ospf_networktype', 'p2p')
            
            # 接口映射
            mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces, ssh_conn)
            if not mapped_interfaces:
                raise Exception(f"无法映射接口名称: {interfaces[0]}")
                
            interface = mapped_interfaces[0]
            
            # 检查接口模式并切换到route模式（如果是bridge模式）
            is_loopback = interface_config.is_loopback_interface(interface)
            if not is_loopback:
                current_mode = interface_config.check_interface_mode(ssh_conn, interface)
                if current_mode and current_mode.lower() != "route":
                    print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
                    switch_result = interface_config.switch_interface_to_route_mode(ssh_conn, interface, executed_commands)
                    if switch_result is False:
                        raise Exception(f"将接口 {interface} 切换到route模式失败")
                else:
                    print(f"接口 {interface} 已经是route模式，跳过切换")
            else:
                print(f"接口 {interface} 是环回口，跳过模式检查")
            
            # 配置接口IP地址
            current_ipv6_address = ipv6_address[0] if ipv6_address else None
            current_ipv6_prefix = ipv6_prefix[0] if ipv6_prefix else None
            
            if ip_address or current_ipv6_address:
                try:
                    result = interface_config.config_interface_ip(
                        ssh_conn, interface,
                        ip_address[0] if ip_address else None,
                        mask[0] if mask else None,
                        executed_commands,
                        current_ipv6_address, current_ipv6_prefix
                    )

                    if result == "Failed" or (isinstance(result, tuple) and len(result) > 0 and result[0] == "Failed"):
                        error_msg = f"配置接口 {interface} IP地址失败"
                        if isinstance(result, tuple) and len(result) > 1:
                            error_msg += f": {result[1]}"
                        raise Exception(error_msg)
                except Exception as e:
                    raise Exception(f"配置接口IP失败: {str(e)}")
            
            # 配置接口OSPF
            result, error_message = config_interface_ospf(
                ssh_conn, interface,
                all_interfaces=all_interfaces,
                ospf_process_id=ospf_process_id,
                ospf_area=ospf_area,
                ospf_cost=ospf_cost,
                ospf_networktype=ospf_networktype,
                ospf_stack=ospf_stack,
                executed_commands=executed_commands,
                device_name=device_name
            )
            
            if result == "Failed":
                raise Exception(f"配置接口OSPF协议失败: {error_message}")
            
            # 在主接口配置完成后，配置环回口
            print(f"\n开始配置环回口...")
            loopback_interface = "LoopBack9"

            try:
                # 为设备分配环回口IP地址 - 使用循环索引i来区分设备
                if i == 0:  # 第一台设备(dut1)
                    loopback_ipv4 = '11.11.11.11' if has_ipv4 else None
                    loopback_mask = '32' if has_ipv4 else None
                    loopback_ipv6 = '2025:11:11:11::11' if has_ipv6 else None
                    loopback_ipv6_prefix = '128' if has_ipv6 else None
                else:  # 第二台设备(dut2)
                    loopback_ipv4 = '22.22.22.22' if has_ipv4 else None
                    loopback_mask = '32' if has_ipv4 else None
                    loopback_ipv6 = '2025:22:22:22::22' if has_ipv6 else None
                    loopback_ipv6_prefix = '128' if has_ipv6 else None
                
                print(f"设备 {device_name} 配置环回口 {loopback_interface}")
                if loopback_ipv4:
                    print(f"IPv4地址: {loopback_ipv4}/{loopback_mask}")
                if loopback_ipv6:
                    print(f"IPv6地址: {loopback_ipv6}/{loopback_ipv6_prefix}")
                
                # 配置环回口IP地址
                if loopback_ipv4 or loopback_ipv6:
                    result = interface_config.config_interface_ip(
                        ssh_conn, loopback_interface,
                        loopback_ipv4, loopback_mask,
                        executed_commands,
                        loopback_ipv6, loopback_ipv6_prefix
                    )
                    
                    if result == "Failed" or (isinstance(result, tuple) and result[0] == "Failed"):
                        error_msg = f"配置环回口 {loopback_interface} IP地址失败"
                        if isinstance(result, tuple) and len(result) > 1:
                            error_msg += f": {result[1]}"
                        raise Exception(error_msg)
                
                # 配置环回口OSPF参数
                print(f"配置环回口 {loopback_interface} OSPF参数...")
                
                # 使用interface_config进入环回口配置模式
                status, interface_executed_commands = interface_config.enter_interface_mode(
                    ssh_conn, loopback_interface, executed_commands, skip_vlan_creation=True)
                
                if status == "Failed":
                    raise Exception(f"进入环回口 {loopback_interface} 配置模式失败")
                
                # 定义环回口OSPF命令
                loopback_ospf_commands = []
                
                # 根据ospf_stack配置相应的OSPF功能
                if has_ipv4:
                    loopback_ospf_commands.append(f"ospf {ospf_process_id} area {ospf_area}")
                    # 环回口通常使用较小的cost值
                    loopback_ospf_commands.append(f"ospf cost {ospf_cost}")
                
                if has_ipv6:
                    loopback_ospf_commands.append(f"ospfv3 {ospf_process_id} area {ospf_area}")
                    loopback_ospf_commands.append(f"ospfv3 cost {ospf_cost}")
                
                # 退出接口配置模式
                loopback_ospf_commands.append("quit")
                
                # 执行环回口OSPF配置命令
                status, loopback_executed_commands, error_message = interface_config.execute_commands(
                    ssh_conn, loopback_ospf_commands, executed_commands, {}, 
                    is_interface_mode=True, return_error_message=True
                )
                
                if status == "Failed":
                    raise Exception(f"配置环回口OSPF参数失败: {error_message}")
                
                # 将环回口命令合并到主命令列表
                if loopback_executed_commands and isinstance(loopback_executed_commands, list):
                    for cmd in loopback_executed_commands:
                        if cmd not in executed_commands:
                            executed_commands.append(cmd)
                
                print(f"环回口 {loopback_interface} 配置完成")
                
            except Exception as e:
                error_msg = f"环回口配置失败: {str(e)}"
                print(f"\n错误: {error_msg}")
                raise Exception(error_msg)
            
            # 【关键修改】每台设备配置完成立即保存命令和系统信息
            all_executed_commands[device_name] = executed_commands
            all_system_info[device_name] = device_system_info.get(device_name, "")

            # 如果是第一台设备完成配置
            if i == 0:
                print(f"第一台设备 {device_name} 配置完成，等待第二台设备配置...")

            # 如果是第二台设备配置完成，检查OSPF邻居状态 
            if i == 1:
                print("\n第二台设备配置完成，等待检查OSPF邻居状态...")
                try:
                    is_up, status = monitor_ospf_neighbor_status(ssh_conn, device_name, timeout_minutes=1, check_interval=5)
                    
                    # 记录OSPF邻居状态
                    ospf_peer_status = status
                    
                    print(f"OSPF邻居状态检查结果: {ospf_peer_status}")
                    
                    # 如果OSPF邻居状态为Full，执行PING连通性测试
                    ping_results = {}
                    if is_up:    
                        print("\nOSPF邻居状态为Full，等待10秒后开始执行PING连通性测试...")
                        time.sleep(10)  # 添加10秒等待时间
                        
                        # 根据ospf_stack配置执行相应的PING测试
                        has_ipv4 = ospf_stack in ['IPv4', 'IPv4&IPv6']
                        has_ipv6 = ospf_stack in ['IPv6', 'IPv4&IPv6']
                        
                        # IPv4 PING测试
                        if has_ipv4:
                            print("执行IPv4 PING测试: 从22.22.22.22 PING 11.11.11.11")
                            ping_cmd = "ping -a 22.22.22.22 11.11.11.11"
                            print(f"执行命令: {ping_cmd}")
                            print("等待PING命令完成...")

                            try:
                                ping_output = ssh_conn.send_command_timing(
                                    ping_cmd,
                                    delay_factor=12,
                                    strip_prompt=False,
                                    strip_command=False
                                )
                                
                                # 添加额外等待
                                time.sleep(5)
                                
                                print(f"IPv4 PING结果:\n{ping_output}")
                                
                                if "100% packet loss" in ping_output or "100.0% packet loss" in ping_output:
                                    ping_results['ipv4_ping'] = "failed"
                                    print("IPv4 PING测试: 失败 (100% 丢包)")
                                elif any(keyword in ping_output.lower() for keyword in ["bytes from", "packet(s) received", "ms", "ttl=", "reply from", "statistics", "time="]):
                                    ping_results['ipv4_ping'] = "success"
                                    print("IPv4 PING测试: 成功")
                                else:
                                    ping_results['ipv4_ping'] = "failed"
                                    print("IPv4 PING测试: 失败 (无响应)")
                                    
                            except Exception as e:
                                ping_results['ipv4_ping'] = "error"
                                print(f"IPv4 PING测试执行出错: {str(e)}")

                        # 在IPv4&IPv6混合环境下等待5秒
                        if has_ipv4 and has_ipv6:
                            print("\nIPv4 PING测试完成，等待5秒后进行IPv6 PING测试...")
                            time.sleep(5)

                        # IPv6 PING测试
                        if has_ipv6:
                            print("执行IPv6 PING测试: 从2025:22:22:22::22 PING 2025:11:11:11::11")
                            try:
                                ping_cmd = "ping ipv6 -a 2025:22:22:22::22 2025:11:11:11::11"
                                print(f"执行命令: {ping_cmd}")
                                print("等待PING命令完成...")
                                
                                ping_output = ssh_conn.send_command_timing(
                                    ping_cmd,
                                    delay_factor=12,
                                    strip_prompt=False,
                                    strip_command=False
                                )
                                
                                # 添加额外等待
                                time.sleep(5)
                                
                                print(f"IPv6 PING结果:\n{ping_output}")
                                
                                if "100% packet loss" in ping_output or "100.0% packet loss" in ping_output:
                                    ping_results['ipv6_ping'] = "failed"
                                    print("IPv6 PING测试: 失败 (100% 丢包)")
                                elif any(keyword in ping_output.lower() for keyword in ["bytes from", "packet(s) received", "ms", "hlim=", "reply from", "statistics", "time="]):
                                    ping_results['ipv6_ping'] = "success"
                                    print("IPv6 PING测试: 成功")
                                else:
                                    ping_results['ipv6_ping'] = "failed"
                                    print("IPv6 PING测试: 失败 (无响应)")
                                    
                            except Exception as e:
                                ping_results['ipv6_ping'] = "error"
                                print(f"IPv6 PING测试执行出错: {str(e)}")
                        
                        # 汇总PING测试结果
                        if ping_results:
                            success_count = sum(1 for result in ping_results.values() if result == "success")
                            total_count = len(ping_results)
                            
                            # 创建结构化PING结果字典
                            overall_ping_status = {
                                "IPv4_PING_Status": ping_results.get("ipv4_ping", "not_tested"),
                                "IPv6_PING_Status": ping_results.get("ipv6_ping", "not_tested")
                            }
                            
                            # 生成汇总状态
                            if success_count == total_count:
                                print(f"\nPING连通性测试完成: 全部成功 ({success_count}/{total_count})")
                            elif success_count > 0:
                                print(f"\nPING连通性测试完成: 部分成功 ({success_count}/{total_count})")
                                print(f"详细结果: IPv4={overall_ping_status['IPv4_PING_Status']}, IPv6={overall_ping_status['IPv6_PING_Status']}")
                            else:
                                print(f"\nPING连通性测试完成: 全部失败 ({success_count}/{total_count})")
                        else:
                            overall_ping_status = {
                                "IPv4_PING_Status": "not_tested",
                                "IPv6_PING_Status": "not_tested"
                            }
                            print("\nPING连通性测试: 未执行测试")

                        print(f"PING测试结果汇总: {overall_ping_status}")
                        
                    else:
                        print("\nOSPF邻居状态为DOWN，跳过PING连通性测试")
                        
                except Exception as e:
                    print(f"检查OSPF邻居状态时出错: {str(e)}")
                    ospf_peer_status = "unknown"
                    overall_ping_status = {
                        "IPv4_PING_Status": "error",
                        "IPv6_PING_Status": "error"
                    }

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

            # 【关键修改】在异常处理中保存当前设备的配置信息
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
                
            # 【关键修改】转换所有已保存设备的命令记录格式
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
                "\n".join(error_messages), 
                file_suffix="dual_ospf_status",
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
        file_suffix="dual_ospf_status", 
        ospf_peer_status=ospf_peer_status,
        ping_connectivity=overall_ping_status
    )

    print(f"\n双设备配置完成，状态: {final_status}")
    print(f"OSPF邻居状态: {ospf_peer_status}")
    print(f"PING连通性: {overall_ping_status}")

    if log_path:
        print(f"日志已保存至: {log_path}")

    return final_status, all_executed_commands, all_system_info, overall_ping_status, ospf_peer_status

def monitor_ospf_neighbor_status(ssh_connection, device_name, timeout_minutes=2, check_interval=5):
    """
    监控OSPF邻居状态，定期检查直到发现Full状态或超时
    
    Args:
        ssh_connection: SSH连接对象
        device_name: 设备名称
        timeout_minutes: 超时时间(分钟)
        check_interval: 检查间隔(秒)
        
    Returns:
        tuple: (bool是否发现UP状态, str邻居状态详情)
    """
    print(f"\n开始监控OSPF邻居状态，将在{timeout_minutes}分钟内每{check_interval}秒检查一次...")
    
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
            # 获取OSPF邻居信息
            output = ssh_connection.send_command(
                "display ospf peer", 
                strip_prompt=False,
                strip_command=False,
                delay_factor=2,
                expect_string=r"[>\]]"
            )
            
            print(f"OSPF邻居状态:\n{output}")
            
            # 分析输出查找Full状态（OSPF邻居状态是Full表示完全相邻）
            lines = output.strip().split('\n')
            for line in lines:
                if "FULL" in line.upper():
                    return True, "Full"  # 返回(成功状态,OSPF状态)
            
            # 如果IPv6也启用，检查OSPFv3
            output = ssh_connection.send_command(
                "display ospfv3 peer", 
                strip_prompt=False,
                strip_command=False,
                delay_factor=2,
                expect_string=r"[>\]]"
            )
            
            print(f"OSPFv3邻居状态:\n{output}")
            
            lines = output.strip().split('\n')
            for line in lines:
                if "FULL" in line.upper():
                    return True, "Full"  # 返回(成功状态,OSPF状态)
            
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"检查OSPF邻居状态时出错: {str(e)}")
            time.sleep(check_interval)
    
    print(f"\n监控超时: 在{timeout_minutes}分钟内未发现FULL状态的OSPF邻居")
    return False, "down"  # 超时返回

def main():
    # 声明全局变量
    global log_recorded
    
    # 初始化变量
    log_recorded = False
    
    try:
        if len(sys.argv) != 2:
            # 显示帮助信息
            print("使用方法:")
            print('python ospf_config_test.py {"hostip":"192.168.56.10,192.168.56.11","username":"admin,admin",')
            print('                           "password":"admin123,admin123","ospf_process_id":"100",')
            print('                           "ospf_area":"0.0.0.0","ospf_stack":"IPv4&IPv6",')
            print('                           "dut1_interface":"GigabitEthernet1/0/1","dut2_interface":"GigabitEthernet1/0/1"}')
            
            print("\n参数说明：")
            print("  hostip: 设备IP地址，用逗号分隔多个设备")
            print("  username: 设备用户名，用逗号分隔多个设备的用户名")
            print("  password: 设备密码，用逗号分隔多个设备的密码")
            print("  ospf_process_id: OSPF进程号，默认为100")
            print("  ospf_area: OSPF区域，默认为0.0.0.0")
            print("  ospf_stack: OSPF协议栈类型，可选值：IPv4, IPv6, IPv4&IPv6，默认为IPv4&IPv6")
            print("  dut1_interface: 第一台设备的接口名称")
            print("  dut2_interface: 第二台设备的接口名称")
            
            sys.exit(1)

        try:
            # 处理输入参数
            json_str = sys.argv[1]
            params = json.loads(json_str)

            # 解析参数后立即记录Running状态的日志       
            write_log.write_log("Running", {}, {})
            
            # 检查是否包含必要的逗号分隔参数
            if "hostip" in params and "," in params["hostip"]:
                # 处理简化格式参数
                print("\n使用简化参数格式配置双设备OSPF")
                
                # 解析逗号分隔的参数
                hostips = [ip.strip() for ip in params["hostip"].split(",")]
                usernames = [user.strip() for user in params.get("username", "").split(",")] if "username" in params else []
                passwords = [pwd.strip() for pwd in params.get("password", "").split(",")] if "password" in params else []
                
                # 确保有足够的用户名和密码
                if len(usernames) < len(hostips):
                    usernames = usernames * len(hostips) if usernames else ["admin"] * len(hostips)
                if len(passwords) < len(hostips):
                    passwords = passwords * len(hostips) if passwords else ["admin"] * len(hostips)
                
                # 构建标准化的双设备参数
                dual_params = {
                    "dut1": {
                        "hostip": hostips[0],
                        "username": usernames[0],
                        "password": passwords[0],
                    },
                    "dut2": {
                        "hostip": hostips[1],
                        "username": usernames[1],
                        "password": passwords[1],
                    },
                    "common": {
                        "ospf_process_id": params.get("ospf_process_id", "100"),
                        "ospf_area": params.get("ospf_area", "0.0.0.0"),
                        "ospf_stack": params.get("ospf_stack", "IPv4&IPv6"),
                        "ospf_cost": params.get("ospf_cost", "10"),
                        "ospf_networktype": params.get("ospf_networktype", "p2p")
                    },
                    "interfaces": {
                        "dut1_interface": params.get("dut1_interface", ""),
                        "dut2_interface": params.get("dut2_interface", "")
                    }
                }
                
                # 检查接口参数是否存在
                if not dual_params["interfaces"]["dut1_interface"] or not dual_params["interfaces"]["dut2_interface"]:
                    print("错误: 必须提供 dut1_interface 和 dut2_interface 参数")
                    sys.exit(1)
                
                # 配置双设备OSPF
                print("\n启动双设备OSPF配置...")
                status, executed_commands, system_info, ping_status, ospf_peer_status = config_dual_devices(dual_params)
                
                if status == "Failed":
                    print(f"\n双设备配置失败")
                    sys.exit(1)
                else:
                    print("\n双设备配置完成!")
                    
                    # 使用单独的结果记录代码确保显示日志保存路径
                    result_format = {}
                    for device_key, commands in executed_commands.items():
                        full_output = []
                        for cmd_entry in commands:
                            if isinstance(cmd_entry, dict):
                                output = cmd_entry.get("output", "")
                                if output:
                                    full_output.append(output)
                        result_format[device_key] = "\n".join(full_output)
                    
                    # 确保ping_status不为None
                    if ping_status is None:
                        ping_status = {
                            "IPv4_PING_Status": "not_tested",
                            "IPv6_PING_Status": "not_tested"
                        }
                        print(f"警告: ping_status为None，设置为默认值: {ping_status}")
                    
                    # 记录最终日志
                    log_path = write_log.write_log(
                        "Completed" if status == "succeed" else status, 
                        result_format, 
                        system_info, 
                        None,
                        file_suffix="dual_ospf_status", 
                        ospf_peer_status=ospf_peer_status,
                        ping_connectivity=ping_status
                    )

                    print(f"\n日志已保存至: {log_path}")
                    print(f"PING状态: {ping_status}")
                
            else:
                # 单设备配置逻辑
                print("\n使用单设备模式配置...")
                
                # 构建单设备参数
                device_params = {
                    "hostip": params.get("hostip", ""),
                    "username": params.get("username", "admin"),
                    "password": params.get("password", "admin"),
                    "ospf_process_id": params.get("ospf_process_id", "100"),
                    "ospf_area": params.get("ospf_area", "0.0.0.0"),
                    "ospf_router_id": params.get("ospf_router_id", ""),
                    "ospf_stack": params.get("ospf_stack", "IPv4&IPv6"),
                    "interface": params.get("interface", ""),
                    "ospf_cost": params.get("ospf_cost", "10"),
                    "ospf_networktype": params.get("ospf_networktype", "p2p")
                }
                
                # 检查接口参数是否存在
                if not device_params["interface"]:
                    print("错误: 单设备模式必须提供interface参数")
                    sys.exit(1)
                
                # 执行单设备配置
                print("\n开始配置OSPF全局参数...")
                status, ssh_conn, executed_commands, error_message, device_system_info = ssh_system_view(device_params)
                
                if status == "Failed" or ssh_conn is None:
                    final_status = "Failed"
                    device_name = device_params.get('device_name', "unknown_device")
                    error_messages = [f"{device_name}: {error_message}"]  # 明确初始化error_messages
                    
                    # 修正all_system_info未定义问题
                    all_system_info = device_system_info if device_system_info else {}
                    
                    # 记录日志并退出
                    result_format = {}
                    log_path = write_log.write_log(final_status, result_format, all_system_info, 
                                "\n".join(error_messages), file_suffix="dual_ospf_status")
                    if log_path:
                        print(f"\n日志已保存至: {log_path}")
                    sys.exit(1)
                
                # 获取设备名
                device_name = device_params.get('device_name', f"device{i+1}")
                
                # 获取系统信息
                system_info = get_system_info_for_log(ssh_conn, device_name)
                
                # 获取接口信息
                all_interfaces = get_cached_interfaces(ssh_conn)
                
                # 将接口字符串分割为多个接口
                interfaces = [intf.strip() for intf in device_params["interface"].split(',') if intf.strip()]

                if not interfaces:
                    print("错误: 未提供有效的接口名称")
                    if ssh_conn:
                        ssh_conn.disconnect()
                    sys.exit(1)

                # 检查是否提供了IP地址参数
                has_ipv4 = "ip_address" in params and params["ip_address"]
                has_mask = "mask" in params and params["mask"]
                has_ipv6 = "ipv6_address" in params and params["ipv6_address"] 
                has_ipv6_prefix = "ipv6_prefix" in params and params["ipv6_prefix"]

                # 自动生成所有接口的IP地址
                auto_ipv4 = []
                auto_mask = []
                auto_ipv6 = []
                auto_ipv6_prefix = []
                if (not has_ipv4 or not has_mask) or (device_params["ospf_stack"] in ["IPv6", "IPv4&IPv6"] and (not has_ipv6 or not has_ipv6_prefix)):
                    # 检查是否需要自动生成IP地址
                    print("\n需要自动生成IP地址...")
                    
                    # 调用interface_config模块生成IP地址
                    auto_ipv4, auto_mask, auto_ipv6, auto_ipv6_prefix = interface_config.generate_ip_addresses(
                        interfaces, 
                        hostip=device_params.get("hostip", "192.168.1.1"),
                        ip_stack=device_params["ospf_stack"]
                    )
                    
                    # 打印生成的IP地址
                    print("\n生成的IP地址信息:")
                    for i, intf in enumerate(interfaces):
                        if i < len(auto_ipv4):
                            print(f"接口 {intf}: IPv4={auto_ipv4[i]}/{auto_mask[i]}", end="")
                            if i < len(auto_ipv6):
                                print(f", IPv6={auto_ipv6[i]}/{auto_ipv6_prefix[i]}")
                            else:
                                print("")
                
                # 将生成的IP地址与提供的参数合并
                ip_addresses = params.get("ip_address", "").split(",") if has_ipv4 else []
                masks = params.get("mask", "").split(",") if has_mask else []
                ipv6_addresses = params.get("ipv6_address", "").split(",") if has_ipv6 else []
                ipv6_prefixes = params.get("ipv6_prefix", "").split(",") if has_ipv6_prefix else []
                
                # 如果没有足够的手动IP地址，使用自动生成的
                if len(ip_addresses) < len(interfaces):
                    ip_addresses.extend(auto_ipv4[len(ip_addresses):])
                    masks.extend(auto_mask[len(masks):])
                
                if len(ipv6_addresses) < len(interfaces) and device_params["ospf_stack"] in ["IPv6", "IPv4&IPv6"]:
                    ipv6_addresses.extend(auto_ipv6[len(ipv6_addresses):])
                    ipv6_prefixes.extend(auto_ipv6_prefix[len(ipv6_prefixes):])
                
                # 配置每个接口的IP地址和OSPF
                for i, interface in enumerate(interfaces):
                    # 先映射接口
                    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh_conn)
                    if mapped_interfaces:
                        interface = mapped_interfaces[0]
                        print(f"映射后的接口名: {interface}")
                        
                    if i < len(ip_addresses) or i < len(ipv6_addresses):
                        # 重要：在配置IP之前先检查并切换接口模式
                        is_loopback = interface_config.is_loopback_interface(interface)
                        if not is_loopback:
                            current_mode = interface_config.check_interface_mode(ssh_conn, interface)
                            if current_mode and current_mode.lower() != "route":
                                print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
                                switch_result = interface_config.switch_interface_to_route_mode(ssh_conn, interface, executed_commands)
                                if not switch_result:
                                    error_msg = f"将接口 {interface} 切换到route模式失败"
                                    print(f"\n错误: {error_msg}")
                                    
                                    # 记录错误并退出
                                    if ssh_conn:
                                        ssh_conn.disconnect()
                                    sys.exit(1)
                                print(f"成功切换接口 {interface} 到route模式")
                            else:
                                print(f"接口 {interface} 已经是route模式，跳过切换")
                        
                        # 配置接口IP地址
                        current_ipv4 = ip_addresses[i] if i < len(ip_addresses) else None
                        current_mask = masks[i] if i < len(masks) else None
                        current_ipv6 = ipv6_addresses[i] if i < len(ipv6_addresses) else None
                        current_ipv6_prefix = ipv6_prefixes[i] if i < len(ipv6_prefixes) else None
                        
                        print(f"\n配置接口 {interface} 的IP地址...")
                        if current_ipv4:
                            print(f"IPv4: {current_ipv4}/{current_mask}")
                        if current_ipv6:
                            print(f"IPv6: {current_ipv6}/{current_ipv6_prefix}")
                        
                        # 调用接口配置模块设置IP地址
                        result = interface_config.config_interface_ip(
                            ssh_conn, interface,
                            current_ipv4, current_mask,
                            executed_commands,
                            current_ipv6, current_ipv6_prefix
                        )
                        
                        if result == "Failed" or (isinstance(result, tuple) and result[0] == "Failed"):
                            error_msg = f"配置接口 {interface} IP地址失败"
                            if isinstance(result, tuple) and len(result) > 1:
                                error_msg += f": {result[1]}"
                            
                            print(f"\n错误: {error_msg}")
                            
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
                                "Failed", result_format, {device_name: system_info}, error_msg,
                                file_suffix="single_ospf_status"
                            )
                            
                            if log_path:
                                print(f"\n日志已保存至: {log_path}")
                            
                            if ssh_conn:
                                ssh_conn.disconnect()
                            sys.exit(1)
                        
                        # 配置接口OSPF参数
                        print(f"\n配置接口 {interface} 的OSPF参数...")
                        
                        result, error_message = config_interface_ospf(
                            ssh_conn, interface,
                            all_interfaces=all_interfaces,
                            ospf_process_id=device_params["ospf_process_id"],
                            ospf_area=device_params["ospf_area"],
                            ospf_cost=device_params["ospf_cost"],
                            ospf_networktype=device_params["ospf_networktype"],
                            ospf_stack=device_params["ospf_stack"],
                            executed_commands=executed_commands,
                            device_name=device_name
                        )
                        
                        if result == "Failed":
                            print(f"\n错误: 配置接口 {interface} OSPF参数失败: {error_message}")
                            
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
                                "Failed", result_format, {device_name: system_info}, error_message,
                                file_suffix="single_ospf_status"
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
                print("\n单设备配置完成!")
                
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
                    "Completed", result_format, {device_name: system_info}, None,
                    file_suffix="single_ospf_status"
                )
                
                print(f"\n日志已保存至: {log_path}")
                
                # 断开连接
                if ssh_conn:
                    ssh_conn.disconnect()

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