import os
import sys
import json
import time

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
        version_output = get_system_info.get_system_info(ssh_connection)
        return version_output or "未能获取到版本信息"
    except Exception as e:
        return f"获取版本信息失败: {str(e)}"

def ssh_system_view(device_params):
    """
    登录设备并执行system-view命令，配置ISIS全局参数
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
        # 获取用户指定的进程ID和其他ISIS参数
        isis_process_id = device_params.get('isis_process_id', '100')
        isis_net = device_params.get('isis_net')
        isis_islevel = str(device_params.get('isis_islevel', '2'))
        isis_costtype = device_params.get('isis_costtype', 'wide')
        
        # 先获取当前的提示符
        prompt = ssh.find_prompt()

        # 先执行screen-length disable命令禁用屏幕分页
        print(f"{prompt}screen-length disable")

        # 先打印出带设备名的命令行
        print(f"{prompt}system-view")

        # 执行system-view命令进入系统视图
        output = ssh.send_command(
            "system-view",
            strip_prompt=True,
            strip_command=True,
            expect_string=r"[\[\]]"
        )

        # 打印命令输出，并确保末尾有换行
        print(output)  # 移除end=''参数，使用默认的换行符

        # 记录命令执行情况 - 合并提示符与命令输出
        executed_commands.append({
            "command": "system-view", 
            "output": f"{prompt}system-view{'' if output.strip() == '' else ' '}{output.strip()}"  # 移除\n，根据输出是否为空添加空格
        })
        
        # 检查命令输出
        status = check_device_output.check_device_output(output)
        if status == "Failed":
            error_message = f"执行命令 'system-view' 失败，设备返回了错误信息"
            print(f"\n错误: {error_message}")
            
            # 断开连接并返回失败状态
            if ssh:
                ssh.disconnect()
            return "Failed", None, executed_commands, error_message  # 返回具体错误信息
        
        # ISIS全局配置命令
        isis_commands = [
            f"isis {isis_process_id}",  # 使用用户指定的process_id
        ]
        
        # 配置ISIS网络实体名称(NET)
        if isis_net:
            # 使用用户提供的NET
            isis_commands.append(f"network-entity {isis_net}")
        else:
            # 如果未提供NET，直接使用登录设备的hostip生成
            if 'hostip' in device_params and device_params['hostip']:
                hostip = device_params['hostip'].strip()
                try:
                    net_segment = ip_to_net_segment(hostip)
                    auto_net = f"49.0000.{net_segment}.00"
                    isis_commands.append(f"network-entity {auto_net}")
                except ValueError as e:
                    print(f"警告: 无法从登录设备IP '{hostip}' 自动生成NET: {str(e)}")
                    print("ISIS配置无法继续，必须提供有效的ISIS NET或hostip")
                    if ssh:
                        ssh.disconnect()
                    return "Failed", None, executed_commands, "无法生成ISIS NET，设备hostip格式无效"
            else:
                print("警告: 未提供ISIS NET且没有提供hostip参数")
                print("ISIS配置无法继续，必须提供有效的ISIS NET或hostip")
                if ssh:
                    ssh.disconnect()
                return "Failed", None, executed_commands, "无法生成ISIS NET，未提供hostip参数"
        
        # 配置ISIS系统级别
        if isis_islevel:
            # 统一处理两种可能的输入格式
            if isis_islevel in ['1', '2', '12']:
                level_mapping = {'1': 'level-1', '2': 'level-2', '12': 'level-1-2'}
                level = level_mapping[isis_islevel]
            elif isis_islevel in ['level-1', 'level-2', 'level-1-2']:
                level = isis_islevel
            else:
                # 默认值
                level = 'level-2'
            isis_commands.append(f"is-level {level}")
        
        # 配置ISIS开销类型
        if isis_costtype:
            cost_type = isis_costtype.lower()
            if cost_type in ['wide', 'narrow', 'compatible']:
                isis_commands.append(f"cost-style {cost_type}")
        
        # 获取isis_stack参数值
        isis_stack = device_params.get('isis_stack', 'IPv4&IPv6')

        # 根据isis_stack参数决定是否配置IPv6地址族
        # 只有选择了IPv6或IPv4&IPv6时才配置IPv6相关内容
        has_ipv6 = (isis_stack in ['IPv6', 'IPv4&IPv6'])

        # 根据是否有IPv6配置决定退出命令数量
        if has_ipv6:
            # 进入IPv6地址族并启用多拓扑
            isis_commands.append("address-family ipv6 unicast")
            isis_commands.append("multi-topology")
            # 需要两次quit: 一次退出IPv6地址族视图，一次退出ISIS视图
            isis_commands.append("quit")  # 从IPv6地址族退出到ISIS视图
            isis_commands.append("quit")  # 从ISIS视图退出到系统视图
        else:
            # 只需一次quit: 从ISIS视图退出到系统视图
            isis_commands.append("quit")
        
        # 执行ISIS全局配置命令
        for i, command in enumerate(isis_commands):
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
            
            # 添加错误检查 - 使用现有的check_device_output函数
            status = check_device_output.check_device_output(output)
            # 处理命令执行中的错误
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
                "output": f"{current_prompt}{command}{'' if output.strip() == '' else ' '}{output.strip()}"  # 根据是否有输出添加空格
            })
            
            # 特殊处理quit命令，确保显示新的提示符
            if command.lower() == "quit":
                # 减少等待时间，从0.5秒减少到0.1秒
                time.sleep(0.1)  # 大幅减少等待时间
                
                # 获取新的提示符
                new_prompt = ssh.find_prompt()
                
                # 条件打印新提示符 - 修改这里
                if "-ipv6" in current_prompt:  
                    # 从IPv6地址族退出到ISIS视图，不打印新提示符，让下一个命令处理
                    pass  
                elif i == len(isis_commands) - 1:
                    # 最后一个退出命令(退出到系统视图)，打印新提示符
                    print(f"{new_prompt}", end='')
                else:
                    # 其他情况，只在必要时打印提示符
                    # 如果当前是倒数第二个命令且下一个也是quit，则不打印
                    if i + 1 < len(isis_commands) and isis_commands[i+1].lower() == "quit":
                        pass
                    else:
                        print(f"{new_prompt}", end='')
        
        return "succeed", ssh, executed_commands, ""
        
    except Exception as e:
        print(f"\n配置执行失败：{str(e)}")
        
        # 捕获并记录错误
        error_msg = f"配置执行失败: {str(e)}"
        system_info = {}
        
        if device_name:
            try:
                version_output = get_system_info.get_system_info(ssh) if ssh else "未连接"
                system_info[device_name] = version_output
            except:
                system_info[device_name] = "获取版本信息失败"
        
        # 记录日志
        log_path = write_log.write_log("Failed", executed_commands or {}, system_info, error_msg, file_suffix="dual_isis_status")
        
        # 打印日志保存路径
        if log_path:
            print(f"\n日志已保存至: {log_path}")
        
        if ssh:
            ssh.disconnect()
        sys.exit(1)  # 立即退出程序

        return "Failed", None, [], ""

def config_interface_isis(ssh, interface, all_interfaces=None, isis_process_id='100', isis_islevel='2', isis_cost='10', 
                         isis_networktype=None, isis_stack='IPv4&IPv6', executed_commands=None, 
                         skip_vlan_creation=False, device_name="config"):
    """配置接口的ISIS参数"""
    global log_recorded
    
    # 使用传入的接口列表或从缓存获取
    if all_interfaces is None:
        all_interfaces = get_cached_interfaces(ssh)
    
    # 映射接口编号到实际接口名
    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh)
    if mapped_interfaces:
        interface = mapped_interfaces[0]  # 使用映射后的接口名
        print(f"映射后的接口名: {interface}")

    # 添加此段：检查接口模式并切换到route模式（如果是bridge模式）
    is_loopback = interface_config.is_loopback_interface(interface)
    if not is_loopback:
        # 先检查当前接口模式，只有在非route模式时才切换
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
    
    # 使用映射后的接口配置
    status, interface_executed_commands = interface_config.enter_interface_mode(
        ssh, interface, executed_commands, skip_vlan_creation)
        
    if status == "Failed":
        log_recorded = True
        return status, None
    
    # 定义ISIS特有的接口命令
    isis_commands = []

    # 根据isis_stack参数决定启用哪些ISIS功能
    if isis_stack in ['IPv4', 'IPv4&IPv6']:
        # 启用IPv4 ISIS
        isis_commands.append(f"isis enable {isis_process_id}")

    if isis_stack in ['IPv6', 'IPv4&IPv6']:
        # 启用IPv6 ISIS
        isis_commands.append(f"isis ipv6 enable {isis_process_id}")

    # 只有非环回口接口且networktype不为null或broadcast时才配置网络类型
    if (isis_networktype and 
        isis_networktype.lower() not in ["null", "broadcast"] and 
        not is_loopback):
        isis_commands.append(f"isis circuit-type {isis_networktype}")

    # 配置 ISIS circuit-level
    if isis_islevel:
        # 统一处理两种可能的输入格式
        if isis_islevel in ['1', '2', '12']:
            isis_level_map = {'1': 'level-1', '2': 'level-2', '12': 'level-1-2'}
            circuit_level = isis_level_map[isis_islevel]
        elif isis_islevel in ['level-1', 'level-2', 'level-1-2']:
            circuit_level = isis_islevel
        else:
            # 默认值
            circuit_level = 'level-2'
        isis_commands.append(f"isis circuit-level {circuit_level}")

    # 配置 ISIS cost - 根据协议栈类型决定配置哪些cost
    if isis_stack in ['IPv4', 'IPv4&IPv6']:
        # 配置IPv4 cost
        isis_commands.append(f"isis cost {isis_cost}")

    if isis_stack in ['IPv6', 'IPv4&IPv6']:
        # 配置IPv6 cost
        isis_commands.append(f"isis ipv6 cost {isis_cost}")

    # 添加退出接口配置的命令
    isis_commands.append("quit")
    
    # 使用interface_config的批量发送命令功能
    status, isis_executed_commands, error_message = interface_config.execute_commands(
        ssh, isis_commands, executed_commands, {}, is_interface_mode=True, return_error_message=True
    )

    # 添加以下代码，将ISIS命令结果合并到主命令列表
    if isis_executed_commands and isinstance(isis_executed_commands, list):
        for cmd in isis_executed_commands:
            if cmd not in executed_commands:
                executed_commands.append(cmd)
    
    # 在记录日志时使用传入的设备名
    if status == "Failed" and not log_recorded:
        log_recorded = True
        system_info = get_system_info_for_log(ssh, device_name)
            
        write_log.write_log("Failed", executed_commands, system_info, error_message, 
                          device_name=device_name, file_suffix="status")
    
    # 返回状态和错误信息
    return status, error_message

def config_dual_devices(dual_params):
    """同时配置两台设备的ISIS参数"""
    # 提取共同参数
    common_params = dual_params.get('common', {})
    isis_process_id = common_params.get('isis_process_id', '100')
    isis_islevel = common_params.get('isis_islevel', '2')
    isis_costtype = common_params.get('isis_costtype', 'wide')
    isis_stack = common_params.get('isis_stack', 'IPv4&IPv6')
    
    # 初始化PING测试状态变量
    overall_ping_status = "not_applicable"  # 默认值：不适用
    isis_peer_status = None  # ISIS邻居状态

    # 提取接口信息
    interface_params = dual_params.get('interfaces', {})
    dut1_interface = interface_params.get('dut1_interface', '')
    dut2_interface = interface_params.get('dut2_interface', '')
    
    if not dut1_interface or not dut2_interface:
        print("错误: 必须提供两台设备的接口参数 dut1_interface 和 dut2_interface")
        return "Failed", {}, {}, "缺少接口参数"

    # 创建设备参数
    devices = []
    for idx, device_key in enumerate(['dut1', 'dut2']):
        if device_key not in dual_params:
            print(f"错误: 缺少设备 {device_key} 的参数")
            return "Failed", {}, {}, f"缺少设备 {device_key} 的参数"
        
        device_params = dual_params[device_key]
        
        # 添加公共ISIS参数
        device_params['isis_process_id'] = isis_process_id
        device_params['isis_islevel'] = isis_islevel
        device_params['isis_costtype'] = isis_costtype
        device_params['isis_stack'] = isis_stack
        
        # 为设备分配接口、IP地址和掩码
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
    isis_peer_status = None
    
    # 依次配置每台设备
    for i, device_params in enumerate(devices):
        # 仅用于初始显示的临时标识
        temp_id = ['dut1', 'dut2'][i]
        print(f"\n开始配置设备 {temp_id}...")
        
        # 根据isis_stack决定是否配置IPv4和IPv6
        has_ipv4 = isis_stack in ['IPv4', 'IPv4&IPv6']
        has_ipv6 = isis_stack in ['IPv6', 'IPv4&IPv6']
        
        if not has_ipv4:
            device_params.pop('ip_address', None)
            device_params.pop('mask', None)
        
        if not has_ipv6:
            device_params.pop('ipv6_address', None)
            device_params.pop('ipv6_prefix', None)
        
        try:
            # 登录设备并配置全局ISIS参数
            status, ssh_conn, executed_commands, error_message = ssh_system_view(device_params)
            
            if status == "Failed" or ssh_conn is None:
                final_status = "Failed"
                # 获取设备名（如果可能）或使用临时ID
                device_name = device_params.get('device_name', temp_id)
                error_messages.append(f"{device_name}: {error_message}")  # 使用设备名而非temp_id
                # 记录日志并退出
                result_format = {}  # 转换命令记录格式
                log_path = write_log.write_log(final_status, result_format, all_system_info, 
                            "\n".join(error_messages), file_suffix="dual_isis_status")
                if log_path:
                    print(f"\n日志已保存至: {log_path}")
                sys.exit(1)
            
            # 获取设备名 - 使用从提示符提取的真实设备名
            device_name = device_params.get('device_name', f"device{i+1}")
            # print(f"使用实际设备名: {device_name}")
            
            # 获取系统信息供日志使用
            system_info = get_system_info_for_log(ssh_conn, device_name)
            
            # 获取接口信息
            all_interfaces = get_cached_interfaces(ssh_conn)
            
            # 处理接口参数
            interfaces = [device_params['interface']]
            ip_address = [device_params.get('ip_address', '')] if 'ip_address' in device_params else []
            mask = [device_params.get('mask', '')] if 'mask' in device_params else []
            ipv6_address = [device_params.get('ipv6_address', '')] if 'ipv6_address' in device_params else []
            ipv6_prefix = [device_params.get('ipv6_prefix', '')] if 'ipv6_prefix' in device_params else []
            
            # 获取通用参数
            interface_isis_level = common_params.get('interface_isis_level', '2')
            interface_isis_cost = common_params.get('interface_isis_cost', '10')
            isis_networktype = common_params.get('isis_networktype')
            
            # 接口映射
            mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces, ssh_conn)
            if not mapped_interfaces:
                raise Exception(f"无法映射接口名称: {interfaces[0]}")
                
            interface = mapped_interfaces[0]
            
            # 检查接口模式并切换到route模式（如果是bridge模式）
            is_loopback = interface_config.is_loopback_interface(interface)
            if not is_loopback:
                # 先检查当前接口模式，只有在非route模式时才切换
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
                    # 使用interface_config模块配置IP地址
                    result = interface_config.config_interface_ip(
                        ssh_conn, interface,
                        ip_address[0] if ip_address else None,
                        mask[0] if mask else None,
                        executed_commands,
                        current_ipv6_address, current_ipv6_prefix
                    )

                    # 简化错误检测，避免重复打印错误信息
                    if result == "Failed" or (isinstance(result, tuple) and len(result) > 0 and result[0] == "Failed"):
                        # 不再重复打印错误信息，interface_config模块已经打印过了
                        # 只记录日志并退出
                        
                        # 创建正确格式的结果字典，使用设备名作为键
                        result_format = {device_name: "\n".join(cmd.get("output", "") 
                                        for cmd in executed_commands 
                                        if isinstance(cmd, dict) and "output" in cmd)}
                        
                        # 构建错误消息用于日志记录
                        error_msg = f"配置接口 {interface} IP地址失败"
                        if isinstance(result, tuple) and len(result) > 1:
                            error_msg += f": {result[1]}"
                        
                        # 记录失败状态的日志
                        log_path = write_log.write_log("Failed", result_format, {device_name: system_info}, error_msg)
                        if log_path:
                            print(f"\n日志已保存至: {log_path}")
                        
                        # 断开连接并立即退出
                        if ssh_conn:
                            ssh_conn.disconnect()
                        sys.exit(1)  # 确保立即退出程序
                except (SystemExit, Exception) as e:  # 同时捕获SystemExit和其他所有Exception
                    # 获取错误信息
                    if isinstance(e, SystemExit):
                        error_message = f"配置接口 {interface} IP地址失败，可能是地址冲突或接口不支持该配置"
                    else:
                        error_message = str(e)
                    
                    print(f"\n错误: {error_message}")
                    
                    # 记录日志并返回正确的退出信息
                    result_format = {}
                    for dk, commands in all_executed_commands.items():
                        # 合并所有命令和输出
                        full_output = []
                        for cmd_entry in commands:
                            if isinstance(cmd_entry, dict):
                                output = cmd_entry.get("output", "")
                                if output:
                                    full_output.append(output)
                        result_format[dk] = "\n".join(full_output)
                    
                    # 添加当前设备的命令
                    full_output = []
                    for cmd_entry in executed_commands:
                        if isinstance(cmd_entry, dict):
                            output = cmd_entry.get("output", "")
                            if output:
                                full_output.append(output)
                    
                    if full_output:
                        result_format[device_name] = "\n".join(full_output)
                    
                    # 确保系统信息存在
                    all_system_info[device_name] = system_info
                    
                    # 记录错误信息
                    error_msg = f"{device_name}: {error_message}"
                    error_messages.append(error_msg)
                    final_status = "Failed"
                    
                    # 记录日志
                    log_path = write_log.write_log(
                        final_status, result_format, all_system_info,
                        "\n".join(error_messages), file_suffix="dual_isis_status"
                    )
                    
                    # 打印日志路径
                    if log_path:
                        print(f"\n日志已保存至: {log_path}")
                    
                    # 断开连接
                    if ssh_conn:
                        try:
                            ssh_conn.disconnect()
                        except:
                            pass
                    
                    # 退出程序
                    sys.exit(1)
            
            # 配置接口ISIS
            result, error_message = config_interface_isis(
                ssh_conn, interface,
                all_interfaces=all_interfaces,
                isis_process_id=isis_process_id,
                isis_islevel=interface_isis_level,
                isis_cost=interface_isis_cost,
                isis_networktype=isis_networktype,
                isis_stack=isis_stack,
                executed_commands=executed_commands,
                device_name=device_name
            )
            
            if result == "Failed":
                raise Exception(f"配置接口ISIS协议失败: {error_message}")
            
            # 在主接口配置完成后，配置环回口
            print(f"\n开始配置环回口...")
            loopback_interface = "LoopBack9"

            try:
                # 根据isis_stack确定需要配置的地址类型
                has_ipv4 = isis_stack in ['IPv4', 'IPv4&IPv6']
                has_ipv6 = isis_stack in ['IPv6', 'IPv4&IPv6']
                
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
                
                # 配置环回口ISIS参数
                print(f"配置环回口 {loopback_interface} ISIS参数...")
                
                # 使用interface_config进入环回口配置模式
                status, interface_executed_commands = interface_config.enter_interface_mode(
                    ssh_conn, loopback_interface, executed_commands, skip_vlan_creation=True)
                
                if status == "Failed":
                    raise Exception(f"进入环回口 {loopback_interface} 配置模式失败")
                
                # 定义环回口ISIS命令
                loopback_isis_commands = []
                
                # 根据isis_stack配置相应的ISIS功能
                if has_ipv4:
                    loopback_isis_commands.append(f"isis enable {isis_process_id}")
                
                if has_ipv6:
                    loopback_isis_commands.append(f"isis ipv6 enable {isis_process_id}")
                
                # 配置ISIS circuit-level
                interface_isis_level = common_params.get('interface_isis_level', '2')
                if interface_isis_level in ['1', '2', '12']:
                    isis_level_map = {'1': 'level-1', '2': 'level-2', '12': 'level-1-2'}
                    circuit_level = isis_level_map[interface_isis_level]
                elif interface_isis_level in ['level-1', 'level-2', 'level-1-2']:
                    circuit_level = interface_isis_level
                else:
                    circuit_level = 'level-2'
                loopback_isis_commands.append(f"isis circuit-level {circuit_level}")
                
                # 配置ISIS cost
                interface_isis_cost = common_params.get('interface_isis_cost', '10')
                
                # 配置 ISIS cost - 根据协议栈类型决定配置哪些cost
                if has_ipv4:
                    # 配置IPv4 cost
                    loopback_isis_commands.append(f"isis cost {interface_isis_cost}")
                
                if has_ipv6:
                    # 配置IPv6 cost
                    loopback_isis_commands.append(f"isis ipv6 cost {interface_isis_cost}")
                
                # 注意：环回口不配置isis circuit-type，因为环回口是虚拟接口
                
                # 退出接口配置模式
                loopback_isis_commands.append("quit")
                
                # 执行环回口ISIS配置命令
                status, loopback_executed_commands, error_message = interface_config.execute_commands(
                    ssh_conn, loopback_isis_commands, executed_commands, {}, 
                    is_interface_mode=True, return_error_message=True
                )
                
                if status == "Failed":
                    raise Exception(f"配置环回口ISIS参数失败: {error_message}")
                
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
            
            # 如果是第一台设备，设置默认的PING状态
            if i == 0:
                overall_ping_status = "pending"  # 等待第二台设备完成测试
                print(f"第一台设备完成，设置overall_ping_status: {overall_ping_status}")

            # 保存设备配置结果 - 使用实际设备名作为键
            all_executed_commands[device_name] = executed_commands
            all_system_info[device_name] = system_info

            print(f"\n设备 {device_name} 配置完成")

            # 如果是第二台设备配置完成，检查ISIS邻居状态
            if i == 1:
                print("\n第二台设备配置完成，等待检查ISIS邻居状态...")
                # 使用当前连接检查ISIS邻居状态
                try:
                    is_up, status = monitor_isis_neighbor_status(ssh_conn, device_name, timeout_minutes=1, check_interval=5)
                    
                    # 简化ISIS邻居状态，只记录up或down
                    isis_peer_status = "up" if is_up else "down"
                    
                    print(f"ISIS邻居状态检查结果: {isis_peer_status.upper()}")
                    
                    # 如果ISIS邻居状态为UP，执行PING连通性测试
                    ping_results = {}
                    if is_up:
                        time.sleep(10)  # 添加5秒等待时间
                        print("\nISIS邻居状态为UP，开始执行PING连通性测试...")
                        
                        # 根据isis_stack配置执行相应的PING测试
                        has_ipv4 = isis_stack in ['IPv4', 'IPv4&IPv6']
                        has_ipv6 = isis_stack in ['IPv6', 'IPv4&IPv6']
                        
                        # IPv4 PING测试
                        if has_ipv4:
                            print("执行IPv4 PING测试: 从22.22.22.22 PING 11.11.11.11")
                            try:
                                ping_cmd = "ping -a 22.22.22.22 11.11.11.11"
                                ping_output = ssh_conn.send_command(
                                    ping_cmd,
                                    delay_factor=3,
                                    expect_string=r"[>\]]",
                                    strip_prompt=False,
                                    strip_command=False
                                )
                                
                                print(f"IPv4 PING结果:\n{ping_output}")
                                
                                # 修复PING结果判断逻辑
                                if "100% packet loss" in ping_output or "100.0% packet loss" in ping_output:
                                    ping_results['ipv4_ping'] = "failed"
                                    print("IPv4 PING测试: 失败 (100% 丢包)")
                                elif any(keyword in ping_output for keyword in ["bytes from", "packet(s) received", "ms"]):
                                    ping_results['ipv4_ping'] = "success"
                                    print("IPv4 PING测试: 成功")
                                else:
                                    ping_results['ipv4_ping'] = "failed"
                                    print("IPv4 PING测试: 失败 (无响应)")
                                    
                            except Exception as e:
                                ping_results['ipv4_ping'] = "error"
                                print(f"IPv4 PING测试执行出错: {str(e)}")

                        # 在IPv4&IPv6混合环境下，IPv4测试完成后等待2秒再进行IPv6测试
                        if has_ipv4 and has_ipv6:
                            print("\nIPv4 PING测试完成，等待2秒后进行IPv6 PING测试...")
                            time.sleep(2)

                        # IPv6 PING测试 - 优化版本
                        if has_ipv6:
                            print("执行IPv6 PING测试: 从2025:22:22:22::22 PING 2025:11:11:11::11")
                            try:
                                # 方法1: 使用send_command_timing，避免过早终止
                                ping_cmd = "ping ipv6 -a 2025:22:22:22::22 2025:11:11:11::11"
                                ping_output = ssh_conn.send_command_timing(
                                    ping_cmd,
                                    delay_factor=8,  # 等待8秒让命令完整执行
                                    strip_prompt=False,
                                    strip_command=False
                                )
                                
                                print(f"IPv6 PING结果:\n{ping_output}")
                                
                                # PING结果判断逻辑
                                if "100% packet loss" in ping_output or "100.0% packet loss" in ping_output:
                                    ping_results['ipv6_ping'] = "failed"
                                    print("IPv6 PING测试: 失败 (100% 丢包)")
                                elif any(keyword in ping_output for keyword in ["bytes from", "packet(s) received", "ms", "hlim="]):
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
                            ping_status_dict = {
                                "IPv4_PING_Status": ping_results.get("ipv4_ping", "not_tested"),
                                "IPv6_PING_Status": ping_results.get("ipv6_ping", "not_tested")
                            }
                            
                            # 生成汇总状态（用于打印和向前兼容）
                            if success_count == total_count:
                                overall_ping_status = ping_status_dict
                                print(f"\nPING连通性测试完成: 全部成功 ({success_count}/{total_count})")
                            elif success_count > 0:
                                overall_ping_status = ping_status_dict
                                print(f"\nPING连通性测试完成: 部分成功 ({success_count}/{total_count})")
                                print(f"详细结果: IPv4={ping_status_dict['IPv4_PING_Status']}, IPv6={ping_status_dict['IPv6_PING_Status']}")
                            else:
                                overall_ping_status = ping_status_dict
                                print(f"\nPING连通性测试完成: 全部失败 ({success_count}/{total_count})")
                        else:
                            # 如果没有执行任何测试，仍然使用字典格式
                            overall_ping_status = {
                                "IPv4_PING_Status": "not_tested",
                                "IPv6_PING_Status": "not_tested"
                            }
                            print("\nPING连通性测试: 未执行测试")

                        # 打印总结状态
                        print(f"PING测试结果汇总后，overall_ping_status: {overall_ping_status}")
                        
                    else:
                        overall_ping_status = "skipped"
                        print("\nISIS邻居状态为DOWN，跳过PING连通性测试")
                        
                except Exception as e:
                    print(f"检查ISIS邻居状态时出错: {str(e)}")
                    isis_peer_status = "unknown"  # 出错时记录为unknown
                    overall_ping_status = {
                    "IPv4_PING_Status": "error",
                    "IPv6_PING_Status": "error"
                    }
                    
                    print(f"异常处理中设置:")
                    print(f"  isis_peer_status: {isis_peer_status}")
                    print(f"  overall_ping_status: {overall_ping_status}")

            # 配置完成后断开连接
            if ssh_conn:
                ssh_conn.disconnect()
                
        except Exception as e:
            error_msg = f"{device_name} 配置失败: {str(e)}"
            print(error_msg)
            final_status = "Failed"
            error_messages.append(error_msg)
            
            # 确保PING状态变量在异常情况下也有值
            if 'overall_ping_status' not in locals() or overall_ping_status is None:
                overall_ping_status = "error"
            
            if 'isis_peer_status' not in locals() or isis_peer_status is None:
                isis_peer_status = "unknown"
            
            # 添加调试信息
            print(f"\n异常处理中的状态:")
            print(f"overall_ping_status: {overall_ping_status}")
            print(f"isis_peer_status: {isis_peer_status}")
            
            # 确保断开连接
            if 'ssh_conn' in locals() and ssh_conn:
                try:
                    ssh_conn.disconnect()
                except:
                    pass
                
            # 转换命令记录格式并记录日志
            result_format = {}
            for dk, commands in all_executed_commands.items():
                # 合并所有命令和输出为一个完整的字符串
                full_output = []
                for cmd_entry in commands:
                    if isinstance(cmd_entry, dict):
                        output = cmd_entry.get("output", "")
                        if output:
                            full_output.append(output)
                
                # 将所有输出合并为一个字符串
                result_format[dk] = "\n".join(full_output)
                
            # 添加当前设备的命令（如果有）
            if 'executed_commands' in locals() and executed_commands:
                full_output = []
                for cmd_entry in executed_commands:
                    if isinstance(cmd_entry, dict):
                        output = cmd_entry.get("output", "")
                        if output:
                            full_output.append(output)
                
                if full_output and 'device_name' in locals():
                    result_format[device_name] = "\n".join(full_output)
            
            # 记录日志时包含PING状态
            log_path = write_log.write_log(
                final_status, 
                result_format, 
                all_system_info, 
                "\n".join(error_messages), 
                file_suffix="dual_isis_status",
                isis_peer_status=isis_peer_status,
                ping_connectivity=overall_ping_status
            )
            
            if log_path:
                print(f"\n日志已保存至: {log_path}")
            sys.exit(1)
    
    # 转换命令记录格式
    result_format = {}
    for device_name_key, commands in all_executed_commands.items():
        # 合并所有命令和输出为一个完整的字符串
        full_output = []
        for cmd_entry in commands:
            if isinstance(cmd_entry, dict):
                output = cmd_entry.get("output", "")
                if output:
                    full_output.append(output)
        
        # 将所有输出合并为一个字符串
        result_format[device_name_key] = "\n".join(full_output)

    # 确保所有状态变量都有值
    if 'overall_ping_status' not in locals():
        overall_ping_status = {
            "IPv4_PING_Status": "not_tested",
            "IPv6_PING_Status": "not_tested"
        }
        print(f"overall_ping_status未定义，设置为默认字典: {overall_ping_status}")
    elif overall_ping_status is None:
        overall_ping_status = {
            "IPv4_PING_Status": "not_tested",
            "IPv6_PING_Status": "not_tested"
        }
        print(f"overall_ping_status为None，重置为默认字典: {overall_ping_status}")

    if 'isis_peer_status' not in locals():
        isis_peer_status = "unknown"
        print(f"isis_peer_status未定义，设置为: {isis_peer_status}")
    elif isis_peer_status is None:
        isis_peer_status = "unknown"
        print(f"isis_peer_status为None，重置为: {isis_peer_status}")

    # 添加详细的调试信息
    # print(f"\n=== 准备记录日志 ===")
    # print(f"final_status: {final_status}")
    # print(f"isis_peer_status: {isis_peer_status} (类型: {type(isis_peer_status)})")
    # print(f"overall_ping_status: {overall_ping_status} (类型: {type(overall_ping_status)})")
    # print(f"overall_ping_status是否为None: {overall_ping_status is None}")
    # print(f"overall_ping_status是否为空字符串: {overall_ping_status == ''}")

    # 记录日志 - 明确传递ping_connectivity参数
    # print(f"\n即将调用write_log，参数:")
    # print(f"  ping_connectivity参数值: '{overall_ping_status}'")

    log_path = write_log.write_log(
        "Completed" if final_status == "succeed" else final_status, 
        result_format, 
        all_system_info, 
        "\n".join(error_messages) if error_messages else None,
        file_suffix="dual_isis_status", 
        isis_peer_status=isis_peer_status,
        ping_connectivity=overall_ping_status  # 确保传递非None值
    )

    print(f"\n双设备配置完成，状态: {final_status}")
    print(f"ISIS邻居状态: {isis_peer_status}")
    print(f"PING连通性: {overall_ping_status}")

    if log_path:
        print(f"日志已保存至: {log_path}")

    return final_status, all_executed_commands, all_system_info, overall_ping_status, isis_peer_status

def get_vlan_id_for_interface(device_params, interface_index):
    """
    为给定接口索引获取对应的VLAN ID
    Args:
        device_params (dict): 设备参数
        interface_index (int): 接口索引
    Returns:
        str: VLAN ID或None
    """
    if 'vlan' not in device_params:
        return None
        
    interfaces = [i.strip() for i in device_params['interface'].split(',')]
    vlans = [v.strip() for v in device_params['vlan'].split(',')]
    
    # 计算非环回口接口的VLAN索引位置
    non_loopback_count = 0
    for idx, intf in enumerate(interfaces):
        if idx == interface_index:  # 找到目标接口
            if interface_config.is_loopback_interface(intf):  # 环回口不需要VLAN
                return None
            else:  # 非环回口
                if non_loopback_count < len(vlans):
                    return vlans[non_loopback_count]
                else:
                    return None
        if not interface_config.is_loopback_interface(intf):
            non_loopback_count += 1
            
    return None

def ip_to_net_segment(ip_address):
    """
    将IPv4地址转换为ISIS NET的XXXX.XXXX.XXXX部分
    例如：192.168.55.111 -> 1921.6805.5111
    
    Args:
        ip_address (str): IPv4地址
        
    Returns:r):
        str: 格式化为ISIS NET中间段的字符串
    """
    # 基本验证
    if not ip_address or not isinstance(ip_address, str):
        raise ValueError("IP地址必须是非空字符串")
    
    ip_address = ip_address.strip()
    
    # 分割IP地址
    octets = ip_address.split('.')
    if len(octets) != 4:
        raise ValueError(f"无效的IPv4地址格式: '{ip_address}'，应为四段格式")
    
    # 转换为整数并验证
    try:
        int_octets = []
        for octet in octets:
            int_octet = int(octet.strip())
            if int_octet < 0 or int_octet > 255:
                raise ValueError(f"IP段 '{octet}' 超出有效范围(0-255)")
            int_octets.append(int_octet)
    except ValueError as e:
        if "超出有效范围" in str(e):
            raise
        raise ValueError(f"无效的IP格式: '{ip_address}'")
    
    # 获取各段的字符串表示，并补零确保至少3位
    first = str(int_octets[0]).zfill(3)
    second = str(int_octets[1]).zfill(3)
    third = str(int_octets[2]).zfill(3)
    fourth = str(int_octets[3]).zfill(3)
    
    # 构建NET的各个部分
    part1 = f"{first}{second[0]}"  # IP1的3位 + IP2的第1位
    part2 = f"{second[1:]}{third[:2]}"  # IP2的后2位 + IP3的前2位
    part3 = f"{third[2:]}{fourth}"  # IP3的最后1位 + IP4
    
    return f"{part1}.{part2}.{part3}"

def monitor_isis_neighbor_status(ssh_connection, device_name, timeout_minutes=2, check_interval=5):
    """
    监控ISIS邻居状态，定期检查直到发现UP状态或超时
    
    Args:
        ssh_connection: SSH连接对象
        device_name: 设备名称
        timeout_minutes: 超时时间(分钟)
        check_interval: 检查间隔(秒)
        
    Returns:
        tuple: (bool是否发现UP状态, str邻居状态详情)
    """
    print(f"\n开始监控ISIS邻居状态，将在{timeout_minutes}分钟内每{check_interval}秒检查一次...")
    
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
            # 获取ISIS邻居信息
            output = ssh_connection.send_command(
                "display isis peer", 
                strip_prompt=False,
                strip_command=False,
                delay_factor=2,
                expect_string=r"[>\]]"
            )
            
            print(f"ISIS邻居状态:\n{output}")
            
            # 分析输出查找State字段
            lines = output.strip().split('\n')
            for line in lines:
                # 打印每一行的调试信息，帮助排查
                line_upper = line.upper()
                if "STATE" in line_upper:
                    if "UP" in line_upper:
                        return True, "up"  # 返回(成功状态,ISIS状态)
                    else:
                        return False, "down"  # 返回(失败状态,ISIS状态)
            
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"检查ISIS邻居状态时出错: {str(e)}")
            time.sleep(check_interval)
    
    print(f"\n监控超时: 在{timeout_minutes}分钟内未发现UP状态的ISIS邻居")
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
            print('python isis_config_test.py {"hostip":"192.168.56.10,192.168.56.11","username":"admin,admin",')
            print('                           "password":"admin123,admin123","isis_process_id":"100",')
            print('                           "isis_islevel":"2","isis_costtype":"wide","isis_stack":"IPv4&IPv6",')
            print('                           "dut1_interface":"GigabitEthernet1/0/1","dut2_interface":"GigabitEthernet1/0/1"}')
            
            print("\n参数说明：")
            print("  hostip: 设备IP地址，用逗号分隔多个设备")
            print("  username: 设备用户名，用逗号分隔多个设备的用户名")
            print("  password: 设备密码，用逗号分隔多个设备的密码")
            print("  isis_process_id: ISIS进程号，默认为100")
            print("  isis_islevel: ISIS系统级别，可选值：1、2、12，默认为2")
            print("  isis_costtype: ISIS开销类型，可选值：wide、narrow、compatible，默认为wide")
            print("  isis_stack: ISIS协议栈类型，可选值：IPv4, IPv6, IPv4&IPv6，默认为IPv4&IPv6")
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
                print("\n使用简化参数格式配置双设备ISIS")
                
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
                        "password": passwords[0]
                    },
                    "dut2": {
                        "hostip": hostips[1],
                        "username": usernames[1],
                        "password": passwords[1]
                    },
                    "common": {
                        "isis_process_id": params.get("isis_process_id", "100"),
                        "isis_islevel": params.get("isis_islevel", "2"),
                        "isis_costtype": params.get("isis_costtype", "wide"),
                        "isis_stack": params.get("isis_stack", "IPv4&IPv6"),
                        "interface_isis_level": params.get("interface_isis_level", "2"),
                        "interface_isis_cost": params.get("interface_isis_cost", "10"),
                        "isis_networktype": params.get("isis_networktype", "p2p")
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
                
                # 配置双设备ISIS
                print("\n启动双设备ISIS配置...")
                status, executed_commands, system_info, ping_status, isis_peer_status = config_dual_devices(dual_params)
                
                if status == "Failed":
                    print(f"\n双设备配置失败: {ping_status}")  # ping_status在失败情况下可能包含错误信息
                    sys.exit(1)
                else:
                    print("\n双设备配置完成!")
                    
                    # 使用单独的结果记录代码确保显示日志保存路径
                    result_format = {}
                    for device_key, commands in executed_commands.items():
                        # 合并所有命令和输出为一个完整的字符串
                        full_output = []
                        for cmd_entry in commands:
                            if isinstance(cmd_entry, dict):
                                output = cmd_entry.get("output", "")
                                if output:
                                    full_output.append(output)
                        
                        # 将所有输出合并为一个字符串
                        result_format[device_key] = "\n".join(full_output)
                    
                    # 确保ping_status不为None，避免传递None到write_log
                    if ping_status is None:
                        ping_status = {
                            "IPv4_PING_Status": "not_tested",
                            "IPv6_PING_Status": "not_tested"
                        }
                        print(f"警告: ping_status为None，设置为默认值: {ping_status}")
                    
                    # 修改这里，添加ping_connectivity参数
                    log_path = write_log.write_log(
                        "Completed" if status == "succeed" else status, 
                        result_format, 
                        system_info, 
                        None,
                        file_suffix="dual_isis_status", 
                        isis_peer_status=isis_peer_status,  # 直接使用前面检测的实际邻居状态
                        ping_connectivity=ping_status
                    )

                    print(f"\n日志已保存至: {log_path}")
                    print(f"PING状态: {ping_status}")  # 添加PING状态的输出
                
            else:
                # 单设备配置逻辑
                print("\n使用单设备模式配置...")
                
                # 构建单设备参数
                device_params = {
                    "hostip": params.get("hostip", ""),
                    "username": params.get("username", "admin"),
                    "password": params.get("password", "admin"),
                    "isis_process_id": params.get("isis_process_id", "100"),
                    "isis_islevel": params.get("isis_islevel", "2"),
                    "isis_costtype": params.get("isis_costtype", "wide"),
                    "isis_stack": params.get("isis_stack", "IPv4&IPv6"),
                    "interface": params.get("interface", ""),
                    # 添加与双设备模式一致的接口参数
                    "interface_isis_level": params.get("interface_isis_level", "2"),
                    "interface_isis_cost": params.get("interface_isis_cost", "10"),
                    "isis_networktype": params.get("isis_networktype", "broadcast")
                }
                
                # 检查接口参数是否存在
                if not device_params["interface"]:
                    print("错误: 单设备模式必须提供interface参数")
                    sys.exit(1)
                
                # 登录设备并配置ISIS全局参数
                print("\n开始配置ISIS全局参数...")
                status, ssh_conn, executed_commands, error_message = ssh_system_view(device_params)
                
                if status == "Failed" or ssh_conn is None:
                    print(f"\n配置失败: {error_message}")
                    sys.exit(1)
                
                # 获取设备名
                device_name = device_params.get('device_name', "config")
                
                # 获取系统信息
                system_info = get_system_info_for_log(ssh_conn, device_name)
                
                # 获取接口信息
                all_interfaces = get_cached_interfaces(ssh_conn)
                
                # 修改单设备接口配置部分 - 添加IP地址配置
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

                # 自动生成所有接口的IP地址 - 一次性为所有接口生成
                auto_ipv4 = []
                auto_mask = []
                auto_ipv6 = []
                auto_ipv6_prefix = []
                if (not has_ipv4 or not has_mask) or (device_params["isis_stack"] in ["IPv6", "IPv4&IPv6"] and (not has_ipv6 or not has_ipv6_prefix)):
                    print("未提供足够的IP地址参数，使用interface_config模块自动生成IP地址...")
                    auto_ipv4, auto_mask, auto_ipv6, auto_ipv6_prefix = interface_config.generate_ip_addresses(
                        interfaces,  # 传入所有接口列表
                        device_params.get('hostip', '192.168.1.1'),  # 提供设备IP
                        device_params["isis_stack"]  # 使用ISIS协议栈类型
                    )
                    print(f"自动生成IPv4地址: {auto_ipv4}/{auto_mask[0] if auto_mask else ''}")
                    if auto_ipv6:
                        print(f"自动生成IPv6地址: {auto_ipv6}/{auto_ipv6_prefix[0] if auto_ipv6_prefix else ''}")

                # 遍历配置每个接口
                for interface_idx, interface in enumerate(interfaces):
                    print(f"\n配置接口 {interface} ({interface_idx+1}/{len(interfaces)})...")
                    
                    # 映射接口名称
                    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, [interface], ssh_conn)
                    if mapped_interfaces:
                        interface = mapped_interfaces[0]
                        print(f"映射后的接口名: {interface}")

                    # 步骤1: 先检查接口模式并切换到route模式（如果是bridge模式）
                    is_loopback = interface_config.is_loopback_interface(interface)
                    if not is_loopback:
                        # 先检查当前接口模式，只有在非route模式时才切换
                        current_mode = interface_config.check_interface_mode(ssh_conn, interface)
                        if current_mode and current_mode.lower() != "route":
                            print(f"接口 {interface} 当前模式为 {current_mode}，需要切换到route模式")
                            switch_result = interface_config.switch_interface_to_route_mode(ssh_conn, interface, executed_commands)
                            if switch_result is False:
                                print(f"\n错误: 将接口 {interface} 切换到route模式失败")
                                if ssh_conn:
                                    ssh_conn.disconnect()
                                sys.exit(1)
                        else:
                            print(f"接口 {interface} 已经是route模式，跳过切换")
                    else:
                        print(f"接口 {interface} 是环回口，跳过模式检查")
                    
                    # 步骤2: 只有在接口模式正确后，才配置IP地址
                    try:
                        # 获取当前接口需要配置的IP地址
                        current_ip = None
                        current_mask = None
                        if has_ipv4 and has_mask:
                            ip_addresses = params["ip_address"].split(',')
                            masks = params["mask"].split(',')
                            if interface_idx < len(ip_addresses):
                                current_ip = ip_addresses[interface_idx]
                                current_mask = masks[min(interface_idx, len(masks)-1)]
                        elif auto_ipv4 and auto_mask and interface_idx < len(auto_ipv4):
                            # 使用为当前接口预先生成的IP地址
                            current_ip = auto_ipv4[interface_idx]
                            current_mask = auto_mask[min(interface_idx, len(auto_mask)-1)]
                            print(f"接口 {interface} 使用自动生成的IPv4地址: {current_ip}/{current_mask}")

                        # 获取IPv6地址
                        current_ipv6 = None
                        current_ipv6_prefix = None
                        if has_ipv6 and has_ipv6_prefix:
                            ipv6_addresses = params["ipv6_address"].split(',')
                            ipv6_prefixes = params["ipv6_prefix"].split(',')
                            if interface_idx < len(ipv6_addresses):
                                current_ipv6 = ipv6_addresses[interface_idx]
                                current_ipv6_prefix = ipv6_prefixes[min(interface_idx, len(ipv6_prefixes)-1)]
                        elif device_params["isis_stack"] in ["IPv6", "IPv4&IPv6"] and not current_ipv6:
                            # 使用自动生成的IPv6地址
                            if auto_ipv6 and auto_ipv6_prefix:
                                current_ipv6 = auto_ipv6[interface_idx]
                                current_ipv6_prefix = auto_ipv6_prefix[interface_idx]
                                print(f"自动生成IPv6地址: {current_ipv6}/{current_ipv6_prefix}")

                        # 使用interface_config模块配置IP地址
                        # 如果IP不提供，模块会自行处理
                        result = interface_config.config_interface_ip(
                            ssh_conn, interface,
                            current_ip, current_mask, 
                            executed_commands,
                            current_ipv6, current_ipv6_prefix
                        )
                        
                        # 简化错误检测，避免重复打印错误信息
                        if result == "Failed" or (isinstance(result, tuple) and len(result) > 0 and result[0] == "Failed"):
                            # 不再重复打印错误信息，interface_config模块已经打印过了
                            # 只记录日志并退出
                            
                            # 创建正确格式的结果字典，使用设备名作为键
                            result_format = {device_name: "\n".join(cmd.get("output", "") 
                                            for cmd in executed_commands 
                                            if isinstance(cmd, dict) and "output" in cmd)}
                            
                            # 构建错误消息用于日志记录
                            error_msg = f"配置接口 {interface} IP地址失败"
                            if isinstance(result, tuple) and len(result) > 1:
                                error_msg += f": {result[1]}"
                            
                            # 记录失败状态的日志
                            log_path = write_log.write_log("Failed", result_format, {device_name: system_info}, error_msg)
                            if log_path:
                                print(f"\n日志已保存至: {log_path}")
                            
                            # 断开连接并立即退出
                            if ssh_conn:
                                ssh_conn.disconnect()
                            sys.exit(1)  # 确保立即退出程序
                    except Exception as e:
                        print(f"\n接口 {interface} IP地址配置时发生错误: {str(e)}")
                        if ssh_conn:
                            ssh_conn.disconnect()
                        sys.exit(1)
                        
                    # 配置接口ISIS参数
                    result, error_message = config_interface_isis(
                        ssh_conn, interface,
                        all_interfaces=all_interfaces,
                        isis_process_id=device_params["isis_process_id"],
                        isis_islevel=device_params.get("interface_isis_level", "2"),
                        isis_cost=device_params.get("interface_isis_cost", "10"),
                        isis_networktype=device_params.get("isis_networktype"),
                        isis_stack=device_params["isis_stack"],
                        executed_commands=executed_commands,
                        device_name=device_name
                    )
                    
                    if result == "Failed":
                        print(f"\n接口 {interface} 配置失败: {error_message}")
                        if ssh_conn:
                            ssh_conn.disconnect()
                        sys.exit(1)
                
                # 断开连接
                if ssh_conn:
                    ssh_conn.disconnect()
                
                print("\n单设备配置完成!")
                    
                # 转换命令记录格式
                result_format = {}
                full_output = []
                for cmd_entry in executed_commands:
                    if isinstance(cmd_entry, dict):
                        output = cmd_entry.get("output", "")
                        if output:
                            full_output.append(output)
                
                result_format[device_name] = "\n".join(full_output)
                
                # 记录日志
                log_path = write_log.write_log("Completed", result_format, {device_name: system_info}, None,
                          file_suffix="single_isis_status")
                
                print(f"\n日志已保存至: {log_path}")
                
        except json.JSONDecodeError as e:
            print("JSON格式错误，请使用正确的JSON格式")
            print(f"错误详情: {str(e)}")
            
            # 记录错误日志并打印路径
            error_msg = f"JSON格式错误: {str(e)}"
            log_path = write_log.write_log("Failed", {}, {}, error_msg)
            if log_path:
                print(f"\n日志已保存至: {log_path}")

            sys.exit(1)


        except Exception as e:
            print(f"执行失败：{str(e)}")
            
            # 记录错误日志时尝试获取设备名称
            device_name = None
            
            # 尝试从locals()中获取已提取的设备名
            if 'device_name' in locals() and device_name:
                device_name = locals()['device_name']
            elif 'device_params' in locals() and 'device_name' in locals()['device_params']:
                device_name = locals()['device_params']['device_name']
            
            # 尝试从已连接的设备中提取名称
            if not device_name and 'ssh_conn' in locals() and locals()['ssh_conn']:
                try:
                    device_name = extract_device_name(locals()['ssh_conn'])
                except:
                    pass
            
            # 构建系统信息字典，使用实际设备名
            system_info = {}
            if device_name:
                system_info = {device_name: f"设备 {device_name} 配置失败"}
            
            error_msg = f"程序执行失败: {str(e)}"
            log_path = write_log.write_log("Failed", {}, system_info, error_msg)
            if log_path:
                print(f"\n日志已保存至: {log_path}")

            sys.exit(1)


    except Exception as e:
        print(f"执行失败：{str(e)}")

        error_msg = f"程序执行失败: {str(e)}"
        log_path = write_log.write_log("Failed", {}, {}, error_msg)
        if log_path:
            print(f"\n日志已保存至: {log_path}")

        sys.exit(1)
        

if __name__ == "__main__":
    main()