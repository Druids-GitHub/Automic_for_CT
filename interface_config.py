#写一个H3C交换机和路由器进行接口IP地址配置的脚本，要求如下：
#1.调用login_args模块登录设备
#2.通过用户传递的设备类型来判断设备类型是交换机还是路由器
#3.如果是交换机，那么就先创建vlan，然后基于vlan接口配置IP
#4.如果是路由器，然后选择设备的具体接口，再输入IP地址，最后确认是否配置
#5.配置完成后，调用write_log、check_device_output、get_system_info模块记录配置日志
#6.退出登录

# 导入自定义模块，需要添加os和sys模块，添加路径
import os
import sys
import json
import time
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import login_args
import check_device_output
import get_system_info
import write_log
import re
import ipaddress

# 添加日志路径过滤
import builtins
original_print = builtins.print
_logged_paths = set()

def filtered_print(*args, **kwargs):
    """过滤重复的日志保存消息"""
    text = ' '.join(str(arg) for arg in args if arg is not None)
    if "日志已保存至" in text:
        # 提取日志路径
        path = text.split("日志已保存至:")[-1].strip()
        if path in _logged_paths:
            return  # 已经打印过这个路径，跳过
        _logged_paths.add(path)
    original_print(*args, **kwargs)

# 替换系统print函数
builtins.print = filtered_print

# 在文件开头添加全局变量
_log_message_printed = False

# 修改设备类型定义
DEVICE_TYPES = {
    "V7-Switch": "switch_v7",
    "V9-Switch": "switch_v9",
    "V7-Router": "router_v7",
    "V9-Router": "router_v9"
}

# 添加设备类型分类判断函数
def is_switch_device(device_type):
    """判断设备类型是否为交换机"""
    return device_type in ["switch_v7", "switch_v9", "V7-Switch", "V9-Switch", "1"]

def is_router_device(device_type):
    """判断设备类型是否为路由器"""
    return device_type in ["router_v7", "router_v9", "V7-Router", "V9-Router", "2"]

def map_interface_number_to_name(interfaces, interface_numbers, ssh=None):
    """将接口编号部分映射到完整的接口名"""
    result = []
    
    for num in interface_numbers:
        # 1. 处理LoopBack接口 - 当输入纯数字时，直接映射为LoopBack接口
        if num.isdigit():
            result.append(f"LoopBack{num}")
            print(f"将纯数字'{num}'映射为: LoopBack{num}")
            continue
            
        # 新增: 判断是否已经是环回口名称(不区分大小写)
        if num.lower().startswith("loopback") or num.lower().startswith("loop"):
            # 标准化环回口名称格式为"LoopBack数字"
            loopback_match = re.search(r'(\d+)', num)
            if loopback_match:
                loopback_num = loopback_match.group(1)
                standardized_name = f"LoopBack{loopback_num}"
                result.append(standardized_name)
                print(f"将环回口名称'{num}'标准化为: {standardized_name}")
                continue
        
        # 2. 从设备上实际获取的接口列表中查找精确匹配
        matched_interfaces = []
        for intf in interfaces:
            # 检查接口名称是否以编号结尾
            if intf.endswith(num):
                matched_interfaces.append(intf)
        
        # 如果找到匹配的接口
        if matched_interfaces:
            if len(matched_interfaces) > 1:
                print(f"警告: 接口编号'{num}'匹配多个接口: {matched_interfaces}")
                print(f"使用第一个匹配项: {matched_interfaces[0]}")
            
            result.append(matched_interfaces[0])
            print(f"将接口编号'{num}'映射为实际接口: {matched_interfaces[0]}")
            continue
            
        # 3. 对于已经是完整接口名的情况，直接使用
        # 检查是否为完整的接口名(增加检查环回口的条件)
        if any(prefix in num for prefix in ["GigabitEthernet", "XGE", "WGE", "TenGigabitEthernet", 
                                           "FortyGigE", "HundredGigE", "LoopBack", "Serial", "BAGG",
                                            "Bridge-Aggregation", "RAGG", "Route-Aggregation", "Twenty-FiveGigE"
                                           ]):
            result.append(num)
            print(f"使用完整接口名: {num}")
            continue
            
        # 4. 尝试构建可能的接口名并与设备上的接口进行比较
        # 常见接口类型前缀
        possible_prefixes = ["GigabitEthernet", "XGE", "WGE", "TenGigabitEthernet", 
                             "FortyGigE", "HundredGigE", "RAGG", "Ser", "BAGG", "HGE", "GE", "FGE"]
        
        found_match = False
        for prefix in possible_prefixes:
            possible_intf = f"{prefix}{num}"
            # 检查是否与设备上的接口匹配（不区分大小写）
            for actual_intf in interfaces:
                if possible_intf.lower() == actual_intf.lower() or actual_intf.lower().endswith(num.lower()):
                    result.append(actual_intf)  # 使用实际接口名（保留原始大小写）
                    print(f"将接口编号'{num}'映射为: {actual_intf}")
                    found_match = True
                    break
            if found_match:
                break
                
        # 5. 如果仍未找到匹配，给出明确的错误信息并使用GigabitEthernet作为默认前缀
        if not found_match:
            print(f"警告: 未找到与编号'{num}'匹配的接口，使用默认前缀")
            default_interface = f"GigabitEthernet{num}"
            result.append(default_interface)
            print(f"使用默认接口名: {default_interface}")
    
    return result

def get_device_interfaces(ssh):
    """获取设备上的所有接口列表"""
    print("\n正在获取设备接口列表...")
    
    # 首先关闭分页显示，确保获取完整输出
    try:
        ssh.send_command(
            "screen-length disable",
            strip_prompt=True,
            strip_command=True,
            expect_string=r"[>\]]"
        )
    except Exception as e:
        print(f"尝试关闭分页显示时出错: {str(e)}，将继续尝试获取接口")
    
    # 修改命令，添加ADM捕获administratively down的接口
    commands = [
        "display interface brief | include UP|DOWN|ADM", # 捕获所有状态的接口
        "display interface brief"  # 备选命令：不使用过滤器，获取全部接口
    ]
    
    all_interfaces = set()  # 使用集合避免重复接口
    
    for cmd in commands:
        try:
            print(f"尝试命令: {cmd}")
            output = ssh.send_command(
                cmd,
                strip_prompt=True,
                strip_command=True,
                delay_factor=15,         # 增加延迟因子，给设备足够响应时间
                max_loops=100,            # 增加循环次数，处理大量输出
                expect_string=r"[>\]]"   # 添加明确的终止字符
            )
            
            # 解析输出，提取接口名（现有代码保持不变）
            for line in output.splitlines():
                if not line.strip():
                    continue
                    
                parts = line.split()
                if not parts:
                    continue
                    
                # 提取可能的接口名
                interface_name = parts[0]
                
                # 排除明显不是接口的行
                if interface_name in ["Interface", "Type:", "Name:", "Current", "brief:", "Total:"]:
                    continue
                    
                # 排除可能的表头
                if any(word in line for word in ["Speed", "Description", "Physical", "Protocol"]):
                    continue
                
                # 检查是否为接口名
                if any(prefix in interface_name for prefix in [
                    "GigabitEthernet", "TenGigabitEthernet", "FortyGigE", "HundredGigE", "WGE", "HGE",
                     "Loop", "Serial", "GE", "XGE", "Ser",  "NULL",
                    "REG", "Vlan", "Bridge", "Tunnel", "Dialer", "Virtual"
                ]):
                    all_interfaces.add(interface_name)
                else:
                    # 如果没有明确的前缀，但看起来像接口，也添加它
                    if re.match(r'^[A-Za-z]+\d+(/\d+)*$', interface_name):
                        all_interfaces.add(interface_name)
                    
            # 如果已经找到了接口，就不再尝试下一个命令
            if all_interfaces:
                break
                    
        except Exception as e:
            print(f"命令 '{cmd}' 执行出错: {str(e)}，尝试下一个命令")
    
    # 删除默认接口列表代码部分，如果获取不到接口就直接返回空列表
    
    # 按字母顺序排序接口，便于查看
    interfaces = sorted(list(all_interfaces))
    
    # 打印接口列表供用户参考
    if interfaces:
        print("\n设备上的可用接口:")
        for intf in interfaces:
            print(f"- {intf}")
    else:
        print("\n警告: 未能从设备获取到任何接口")
    
    return interfaces

def parse_interface_params(device_params, ssh=None):
    """解析并验证接口参数，支持仅提供接口编号部分"""
    # 如果SSH连接有效，先获取设备上的所有接口
    all_interfaces = []
    if ssh:
        all_interfaces = get_device_interfaces(ssh)
    
    # 检查参数中是否包含interface_numbers
    if 'interface_numbers' in device_params:
        if not all_interfaces and ssh:
            all_interfaces = get_device_interfaces(ssh)
            
        # 转换接口编号为接口名
        interface_numbers = [n.strip() for n in device_params['interface_numbers'].split(',') if n.strip()]
        interfaces = map_interface_number_to_name(all_interfaces, interface_numbers, ssh)
        
        # 打印选择的接口并处理映射失败情况
        if interfaces:
            print(f"\n已选择的接口: {', '.join(interfaces)}")
        else:
            print("\n错误: 没有成功映射任何接口")
            print("请尝试以下方式:")
            print("1. 使用完整接口名，如 'GigabitEthernet1/0/1'")
            print("2. 确认设备上存在您指定的接口编号")
            # 不再直接退出，而是返回默认值
            # 使用常见接口作为默认值
            interfaces = [f"GigabitEthernet{num}" for num in interface_numbers]
            print(f"使用默认接口名: {', '.join(interfaces)}")
        
        return interfaces
    
    # 如果使用常规interface参数
    elif 'interface' in device_params:
        interface_values = [i.strip() for i in device_params['interface'].split(',') if i.strip()]
        print(f"\n处理接口参数: {', '.join(interface_values)}")
        
        # 检查是否需要将接口值映射为完整接口名
        need_mapping = False
        for intf in interface_values:
            # LoopBack接口特别处理
            if intf.lower().startswith("loop") or intf.lower().startswith("loopback"):
                continue
                
            # 如果不是标准接口格式，需要映射
            if not any(prefix in intf for prefix in ["GigabitEthernet", "TenGigabitEthernet", 
                                                  "FortyGigE", "HundredGigE"]):
                need_mapping = True
                break
        
        # 如果需要映射，使用相同的映射逻辑
        if need_mapping:
            print("检测到接口参数可能需要映射，尝试映射为完整接口名...")
            interfaces = map_interface_number_to_name(all_interfaces, interface_values, ssh)
            print(f"\n已映射的接口: {', '.join(interfaces)}")
        else:
            # 直接使用指定的接口名
            interfaces = interface_values
            print(f"\n使用指定的接口: {', '.join(interfaces)}")
        
        return interfaces
    
    # 如果两种参数都未提供
    else:
        print("错误: 没有提供接口参数，请使用interface或interface_numbers参数")
        # 使用默认接口作为备选
        interfaces = ["GigabitEthernet1/0/1"]
        print(f"使用默认接口: {', '.join(interfaces)}")
        return interfaces

# 修改login_and_enter_system_view函数，在连接后立即提取设备名称
def login_and_enter_system_view(device_params):
    """
    登录设备并进入系统视图
    """
    # 记录所有执行的命令
    executed_commands = []
    
    # 登录设备
    ssh = login_args.run_script(device_params)
    
    # 判断是否登录成功
    if not ssh:
        print("设备登录失败")
        return "Failed", None, executed_commands, {}  # 确保返回空字典
    
    try:    
        # 清除缓冲区
        ssh.clear_buffer()
        
        # 初始化系统信息字典
        system_info = {}
        
        # 获取并显示当前视图（设备的第一条回显）
        current_prompt = ssh.find_prompt()
        print(current_prompt, end='')
        
        # 从提示符中提取设备名 - 提前获取设备名称
        device_name = None
        if '<' in current_prompt and '>' in current_prompt:
            device_name = re.search(r'<([^>]+)>', current_prompt).group(1)
            if device_name:
                print(f"从提示符中提取到设备名称: {device_name}")
                system_info["device_name"] = device_name
        elif '[' in current_prompt and ']' in current_prompt:
            device_name = re.search(r'\[([^\]]+)\]', current_prompt).group(1)
            if device_name:
                print(f"从提示符中提取到设备名称: {device_name}")
                system_info["device_name"] = device_name
                
        # 如果从提示符中没提取到设备名，尝试从配置中提取
        if not device_name:
            try:
                sysname_output = ssh.send_command(
                    "display current-configuration | include sysname",
                    strip_prompt=False, strip_command=False
                )
                if "sysname" in sysname_output:
                    sysname_match = re.search(r'sysname\s+(\S+)', sysname_output)
                    if sysname_match:
                        device_name = sysname_match.group(1)
                        print(f"从配置中提取到设备名称: {device_name}")
                        system_info["device_name"] = device_name
            except Exception as e:
                print(f"尝试从配置中提取设备名称时出错: {str(e)}")
        
        # 进入系统视图
        output = ssh.send_command_timing(
            "system-view",
            strip_prompt=False,
            strip_command=False,
            delay_factor=1
        )
        print(output.rstrip(), end='')
        
        # 提取提示符和命令输出
        prompt = output.strip().splitlines()[-1] if output.strip() else ""
        cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
        executed_commands.append({"command": "system-view", "output": f"{prompt}\nsystem-view" if prompt else output.strip()})
        
        # 检查system-view命令输出
        status = check_device_output.check_device_output(output)
        if status == "Failed":
            error_message = "进入系统视图失败"
            log_with_message_control(status, executed_commands, system_info, error_message)
            return status, ssh, executed_commands, system_info
            
        return "succeed", ssh, executed_commands, system_info
        
    except Exception as e:
        print(f"\n登录或进入系统视图失败：{str(e)}")
        if ssh:
            ssh.disconnect()
        return "Failed", None, executed_commands, {}  # 确保返回空字典

def create_vlan(ssh, vlan_id, executed_commands):
    """
    创建 VLAN
    """
    cmd = f"vlan {vlan_id}"
    output = ssh.send_command(
        cmd,
        strip_prompt=False,
        strip_command=False,
        expect_string=r"]"
    )
    print(output.rstrip(), end='')
    # 提取提示符和命令输出
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查命令输出
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"创建VLAN {vlan_id} 失败，设备可能不支持该VLAN或已存在冲突配置"
        print(f"\n错误: {error_message}")
        log_with_message_control(status, executed_commands, {}, error_message)
        return status
    return status

def config_interface_ip(ssh, interface, ip=None, mask=None, executed_commands=None, ipv6=None, ipv6_prefix=None, verbose=True):
    """配置接口IP地址"""
    try:
        # 进入接口配置模式
        cmd = f"interface {interface}"
        output = ssh.send_command(
            cmd,
            strip_prompt=False,
            strip_command=False,
            expect_string=r"]"
        )
        print(output.rstrip(), end='')
        
        # 提取提示符和命令输出
        prompt = output.strip().splitlines()[-1] if output.strip() else ""
        cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
        executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
        
        # 检查进入接口是否成功
        status = check_device_output.check_device_output(output)
        if status == "Failed":
            error_message = f"进入接口 {interface} 配置模式失败，请检查接口名称是否正确或设备是否支持该接口类型"
            print(f"\n错误: {error_message}")
            log_with_message_control(status, executed_commands, {}, error_message)
            return "Failed", error_message  # 返回具体错误信息
        
        # 配置 IPv4 地址
        if ip and mask:
            cmd = f"ip address {ip} {mask}"
            output = ssh.send_command(
                cmd,
                strip_prompt=False,
                strip_command=False,
                expect_string=r"]"
            )
            print(output.rstrip(), end='')
            
            # 提取提示符和命令输出
            prompt = output.strip().splitlines()[-1] if output.strip() else ""
            cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
            executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
            
            # 检查IP配置是否成功
            status = check_device_output.check_device_output(output)
            if status == "Failed":
                if verbose:
                    print(f"错误: 配置接口 {interface} IPv4地址 {ip}/{mask} 失败！可能是地址冲突或接口不支持该配置")
                return "Failed", f"配置接口 {interface} IPv4地址 {ip}/{mask} 失败！可能是地址冲突或接口不支持该配置"
        
        # IPv6配置（如果有）
        if ipv6 and ipv6_prefix:
            cmd = f"ipv6 address {ipv6} {ipv6_prefix}"
            output = ssh.send_command(
                cmd,
                strip_prompt=False,
                strip_command=False,
                expect_string=r"]"
            )
            print(output.rstrip(), end='')
            
            prompt = output.strip().splitlines()[-1] if output.strip() else ""
            cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
            executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
            
            status = check_device_output.check_device_output(output)
            if status == "Failed":
                error_message = f"配置接口 {interface} IPv6地址 {ipv6}/{ipv6_prefix} 失败！可能是地址冲突或接口不支持该配置"
                print(f"\n错误: {error_message}")
                log_with_message_control(status, executed_commands, {}, error_message)
                return "Failed", error_message  # 返回具体错误信息
        
        # 退出接口配置
        cmd = "quit"
        output = ssh.send_command(cmd, strip_prompt=False, strip_command=False, expect_string=r"]")
        print(output.rstrip(), end='')
        
        prompt = output.strip().splitlines()[-1] if output.strip() else ""
        cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
        executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
        
        return "succeed"
        
    except Exception as e:
        error_message = f"配置接口 {interface} 时发生异常: {str(e)}"
        print(f"\n错误: {error_message}")
        log_with_message_control("Failed", executed_commands, {}, error_message)
        return "Failed", error_message  # 返回具体错误信息

def config_port_vlan(ssh, interface, vlan_id, executed_commands):
    """配置接口的 VLAN"""
    # 进入接口配置
    cmd = f"interface {interface}"
    output = ssh.send_command(
        cmd,
        strip_prompt=False,
        strip_command=False,
        expect_string=r"]"
    )
    print(output.rstrip(), end='')
    
    # 使用统一的方式处理输出格式
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查命令输出
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"进入接口 {interface} 配置模式失败"
        print(f"\n错误: {error_message}")
        log_with_message_control(status, executed_commands, {}, error_message)
        return status
    
    # 配置接口 VLAN
    cmd = f"port access vlan {vlan_id}"
    output = ssh.send_command(
        cmd,
        strip_prompt=False,
        strip_command=False,
        expect_string=r"]"
    )
    print(output.rstrip(), end='')
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查命令输出
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"接口 {interface} 配置VLAN {vlan_id} 失败，可能是接口类型不支持或VLAN不存在"
        print(f"\n错误: {error_message}")
        log_with_message_control(status, executed_commands, {}, error_message)
        return status
        
    # 添加quit命令，退出接口配置
    cmd = "quit"
    output = ssh.send_command(
        cmd,
        strip_prompt=False,
        strip_command=False,
        expect_string=r"]"
    )
    print(output.rstrip(), end='')
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    return status

def config_ip(ssh, system_info, interface, ip_address, mask, 
             vlan_id=None, executed_commands=None, ipv6_address=None, ipv6_prefix=None):
    """配置IP地址 - 基于是否提供VLAN来决定配置方式"""
    try:
        if executed_commands is None:
            executed_commands = []
            
        # 如果是环回接口，直接配置IP地址
        if is_loopback_interface(interface):
            result = config_interface_ip(ssh, interface, ip_address, mask, executed_commands,
                                      ipv6_address, ipv6_prefix)
            return result
        
        # 判断配置逻辑：基于是否提供VLAN，而不是设备类型
        if vlan_id:
            # 有VLAN ID - 配置VLAN和VLAN接口
            # 创建VLAN
            status = create_vlan(ssh, vlan_id, executed_commands)
            if status == "Failed":
                return status
            
            # 退出VLAN配置视图
            cmd = "quit"
            output = ssh.send_command(cmd, strip_prompt=False, strip_command=False, expect_string=r"]")
            print(output.rstrip(), end='')
            prompt = output.strip().splitlines()[-1] if output.strip() else ""
            cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
            executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
            
            # 配置接口的VLAN
            status = config_port_vlan(ssh, interface, vlan_id, executed_commands)
            if status == "Failed":
                return status
            
            # 配置VLAN接口的IP地址
            vlan_interface = f"Vlan-interface{vlan_id}"
            status = config_interface_ip(ssh, vlan_interface, ip_address, mask, executed_commands, 
                                       ipv6_address, ipv6_prefix)
            return status
        else:
            # 没有VLAN ID - 检查物理接口模式并直接配置
            interface_mode = check_interface_mode(ssh, interface)
            if interface_mode == "bridge":
                if not switch_interface_to_route_mode(ssh, interface, executed_commands):
                    error_message = f"无法将接口 {interface} 切换到route模式"
                    print(f"\n错误: {error_message}")
                    log_with_message_control("Failed", executed_commands, {}, error_message)
                    return "Failed"
            
            # 直接在物理接口上配置IP地址
            status = config_interface_ip(ssh, interface, ip_address, mask, executed_commands,
                                       ipv6_address, ipv6_prefix)
            return status

        return "succeed"
    except Exception as e:
        error_msg = f"配置接口 {interface} 时发生异常: {str(e)}"
        print(f"\n错误: {error_msg}")
        log_with_message_control("Failed", executed_commands, {}, error_msg)
        return "Failed"

def check_ipv6(ip_str):
    """
    检查是否是有效的IPv6地址
    Args:
        ip_str: IPv6地址字符串
    Returns:
        bool: 是否是有效的IPv6地址
    """
    try:
        import ipaddress
        ipaddress.IPv6Address(ip_str)
        return True
    except:
        return False

def validate_ip_addresses(ip_addresses, ipv6_addresses=None, masks=None, ipv6_prefixes=None):
    """
    验证IP地址、掩码和前缀的合法性
    
    Args:
        ip_addresses (list): IPv4地址列表
        ipv6_addresses (list): IPv6地址列表，可选
        masks (list): IPv4掩码位数列表
        ipv6_prefixes (list): IPv6前缀长度列表，可选
        
    Returns:
        bool: 所有IP地址是否都合法
    """
    # 验证IPv4地址格式
    for ip in ip_addresses:
        if not login_args.check_ip(ip):
            print(f"IPv4地址格式错误: {ip}")
            return False
    
    # 验证掩码位数
    if masks:
        for mask in masks:
            if not re.match(r'^\d{1,2}$', mask) or not 0 <= int(mask) <= 32:
                print(f"掩码位数错误: {mask}")
                return False
    
    # 验证IPv6地址格式
    if ipv6_addresses:
        for ipv6 in ipv6_addresses:
            if not check_ipv6(ipv6):
                print(f"IPv6地址格式错误: {ipv6}")
                return False
    
    # 验证IPv6前缀长度
    if ipv6_prefixes:
        for prefix in ipv6_prefixes:
            if not re.match(r'^\d{1,3}$', prefix) or not 0 <= int(prefix) <= 128:
                print(f"IPv6前缀长度错误: {prefix}")
                return False
    
    return True

def is_loopback_interface(interface):
    """
    检查接口是否为环回口
    
    Args:
        interface (str): 接口名称
        
    Returns:
        bool: 是否为环回口
    """
    return interface.lower().startswith("loopback")

def check_interface_mode(ssh, interface):
    """
    检查接口的link-mode
    
    Args:
        ssh: SSH连接对象
        interface: 接口名称
        
    Returns:
        str: "bridge"或"route"或"unknown"
    """
    try:
        # 先进入接口配置模式
        ssh.send_command(f"interface {interface}", expect_string=r"]")
        
        # 使用display this命令查看接口配置
        output = ssh.send_command("display this", expect_string=r"]")
        
        # 添加调试信息
        print(f"DEBUG - 接口 {interface} 的display this输出:")
        print(f"'{output}'")
        
        # 退出接口配置模式
        ssh.send_command("quit", expect_string=r"]")
        
        # 检查接口模式 - 扩展匹配模式
        if any(keyword in output.lower() for keyword in ["port link-mode bridge", "link-mode bridge", "bridge"]):
            print(f"检测到接口 {interface} 为bridge模式")
            return "bridge"
        elif any(keyword in output.lower() for keyword in ["port link-mode route", "link-mode route", "route"]):
            print(f"检测到接口 {interface} 为route模式")
            return "route"
        else:
            print(f"警告: 接口 {interface} 模式未知，输出内容: {output[:100]}...")
            return "unknown"
            
    except Exception as e:
        print(f"检查接口 {interface} 模式时出错: {str(e)}")
        return "unknown"

def switch_interface_to_route_mode(ssh, interface, executed_commands):
    """
    将接口切换至route模式
    """
    # 进入接口视图
    cmd = f"interface {interface}"
    output = ssh.send_command(cmd, strip_prompt=False, strip_command=False, expect_string=r"]")
    print(output.rstrip(), end='')
    
    # 记录命令
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查接口命令执行结果
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"进入接口 {interface} 失败，可能接口不存在或命名错误"
        print(f"\n错误: {error_message}")
        return False
    
    # 执行模式切换命令
    cmd = "port link-mode route"
    output = ssh.send_command(cmd, strip_prompt=False, strip_command=False, expect_string=r"(\]|Y\/N\:|Y\/N\])", delay_factor=2)
    print(output.rstrip(), end='')

    # 检查是否需要确认 - 支持多种确认提示格式
    if "Continue? [Y/N]:" in output or "choose 'YES' or 'NO'[Y/N]:" in output or "[Y/N]" in output:
        # 需要确认，立即发送Y - 不要等待
        y_response = ssh.send_command("Y", strip_prompt=False, strip_command=False, expect_string=r"]", delay_factor=2)
 
        # 过滤掉响应中的重复接口信息行
        filtered_lines = []
        for line in y_response.splitlines():
            # 忽略仅包含接口名称的行
            if not (line.strip() == f"interface {interface}"):
                filtered_lines.append(line)
        
        filtered_response = "\n".join(filtered_lines)
        print(filtered_response.rstrip(), end='')
        
        # 将过滤后的响应添加到输出中
        output += filtered_response
               
        #等待3秒以确保接口模式切换完成
        print("\n等待3秒以确保接口模式切换完成...")
        time.sleep(3)
        
    else:
        # 即使不需要确认，也添加3秒等待时间
        print("\n等待3秒以确保接口模式切换完成...")
        time.sleep(3)
    
    # 记录命令
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查命令执行结果
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"无法将接口 {interface} 切换到route模式"
        print(f"\n错误: {error_message}")
        return False
        
    return True

def switch_interface_to_bridge_mode(ssh, interface, executed_commands):
    """
    将接口切换至bridge模式
    """
    # 进入接口视图
    cmd = f"interface {interface}"
    output = ssh.send_command(cmd, strip_prompt=False, strip_command=False, expect_string=r"]")
    print(output.rstrip(), end='')
    
    # 记录命令
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查接口命令执行结果
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"进入接口 {interface} 失败，可能接口不存在或命名错误"
        print(f"\n错误: {error_message}")
        return False
    
    # 执行模式切换命令
    cmd = "port link-mode bridge"
    output = ssh.send_command(cmd, strip_prompt=False, strip_command=False, expect_string=r"(\]|Y\/N\:|Y\/N\])", delay_factor=2)
    print(output.rstrip(), end='')

    # 检查是否需要确认 - 支持多种确认提示格式
    if "Continue? [Y/N]:" in output or "choose 'YES' or 'NO'[Y/N]:" in output or "[Y/N]" in output:
        # 需要确认，立即发送Y
        y_response = ssh.send_command("Y", strip_prompt=False, strip_command=False, expect_string=r"]", delay_factor=2)
 
        # 过滤掉响应中的重复接口信息行
        filtered_lines = []
        for line in y_response.splitlines():
            # 忽略仅包含接口名称的行
            if not (line.strip() == f"interface {interface}"):
                filtered_lines.append(line)
        
        filtered_response = "\n".join(filtered_lines)
        print(filtered_response.rstrip(), end='')
        
        # 将过滤后的响应添加到输出中
        output += filtered_response
               
        # 等待3秒以确保接口模式切换完成
        print("\n等待3秒以确保接口模式切换完成...")
        time.sleep(3)
    else:
        # 即使不需要确认，也添加3秒等待时间
        print("\n等待3秒以确保接口模式切换完成...")
        time.sleep(3)
    
    # 记录命令
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查命令执行结果
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"无法将接口 {interface} 切换到bridge模式"
        print(f"\n错误: {error_message}")
        return False
        
    return True

def execute_commands(ssh, commands, executed_commands=None, system_info=None, is_interface_mode=False, return_error_message=False):
    """执行一系列命令并处理输出"""
    if executed_commands is None:
        executed_commands = []
        
    executed_cmd_list = []
    
    try:
        for cmd in commands:
            # 检查SSH连接是否有效
            if not ssh.is_alive():
                error_message = "SSH连接已关闭，无法执行命令"
                print(f"\n错误: {error_message}")
                if return_error_message:
                    return "Failed", executed_cmd_list, error_message
                return "Failed", executed_cmd_list
            
            # 执行命令
            output = ssh.send_command(
                cmd,
                strip_prompt=False,
                strip_command=False,
                expect_string=r"]"
            )
            print(output.rstrip(), end='')
            
            # 提取提示符和命令输出
            prompt = output.strip().splitlines()[-1] if output.strip() else ""
            cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
            executed_cmd_list.append({"command": cmd, "output": f"{prompt}\n{output.strip()}" if output.strip() else prompt})
            
            # 检查命令输出
            status = check_device_output.check_device_output(output)
            if status == "Failed":
                error_message = f"执行命令 '{cmd}' 失败，设备返回了错误信息"
                print(f"\n错误: {error_message}")
                log_with_message_control(status, executed_commands, system_info, error_message)
                if return_error_message:
                    return status, executed_cmd_list, error_message
                return status, executed_cmd_list
                
        if return_error_message:
            return "succeed", executed_cmd_list, None
        return "succeed", executed_cmd_list
        
    except Exception as e:
        print(f"\n错误: 命令执行过程中发生异常: {str(e)}")
        if return_error_message:
            return "Failed", executed_cmd_list, str(e)
        return "Failed", executed_cmd_list


def generate_ip_addresses(interfaces, hostip="192.168.1.1", ip_stack="IPv4&IPv6"):
    """
    根据接口列表和设备IP自动生成IP地址
    
    Args:
        interfaces (list): 接口列表
        hostip (str): 设备IP地址，格式如192.168.56.n
        ip_stack (str): IP协议栈类型，可选值：IPv4, IPv6, IPv4&IPv6
        
    Returns:
        tuple: (ip_addresses, masks, ipv6_addresses, ipv6_prefixes)
    """
    # 初始化结果列表
    ip_addresses = []
    masks = []
    ipv6_addresses = []
    ipv6_prefixes = []
    
    # 从设备IP提取第四段作为n值
    try:
        ip_segments = hostip.strip().split('.')
        if len(ip_segments) == 4:
            n = ip_segments[3]  # 第四段
        else:
            n = "1"  # 默认值
            print(f"警告: 设备IP格式无效: {hostip}，使用默认值1")
    except:
        n = "1"  # 出错时使用默认值
        print(f"警告: 无法从设备IP提取第四段: {hostip}，使用默认值1")
    
    # 根据接口列表生成IP地址
    for i, interface in enumerate(interfaces):
        # 默认将x初始化为接口序号
        x = i + 1
        
        # 判断是否为环回口
        is_loopback = is_loopback_interface(interface)
        
        # 如果是环回口，尝试从接口名称提取编号
        if is_loopback:
            loopback_match = re.search(r'(\d+)', interface)
            if loopback_match:
                # 关键修复：确保环回口编号被正确提取并使用
                x = int(loopback_match.group(1))
                print(f"从环回口名称提取编号: {x}，将使用此编号生成IP地址")
        
        # 根据IP协议栈类型生成对应IP地址
        if ip_stack in ["IPv4", "IPv4&IPv6"]:
            if is_loopback:
                # 环回口使用10.n.x.1/32格式，确保x就是环回口编号
                ip_addresses.append(f"10.{n}.{x}.1")
                masks.append("32")
                print(f"为环回口 {interface} 生成IPv4地址: 10.{n}.{x}.1/32")
            else:
                # 普通接口使用172.n.x.1/24格式 (保持不变)
                ip_addresses.append(f"172.{n}.{x}.1")
                masks.append("24")
        
        if ip_stack in ["IPv6", "IPv4&IPv6"]:
            if is_loopback:
                # 环回口IPv6使用2025:10:n:x::1/128格式
                ipv6_addresses.append(f"2025:10:{n}:{x}::1")
                ipv6_prefixes.append("128")
                print(f"为环回口 {interface} 生成IPv6地址: 2025:10:{n}:{x}::1/128")
            else:
                # 普通接口IPv6使用2025:172:{n}:{x}::1/64格式 (保持不变)
                ipv6_addresses.append(f"2025:172:{n}:{x}::1")
                ipv6_prefixes.append("64")
    
    # 返回生成的IP地址和掩码
    return (ip_addresses, masks, ipv6_addresses, ipv6_prefixes)


# 修复log_with_message_control函数，统一使用device_name

def log_with_message_control(status, executed_commands, system_info, error_message=None):
    """调用write_log并控制消息打印"""
    global _log_message_printed
    
    # 确保system_info是字典
    if not isinstance(system_info, dict):
        system_info = {}
    
    # 1. 提取设备名称
    device_name = None
    for field in ["device_name", "devicename"]:
        if field in system_info:
            device_name = system_info[field]
            break
    
    # 2. 创建用于传递给write_log的数据结构
    processed_system_info = {}
    
    # 3. 将executed_commands转换为纯字符串格式
    if isinstance(executed_commands, list) and executed_commands:
        # 检查是否为结构化格式
        if isinstance(executed_commands[0], dict) and "output" in executed_commands[0]:
            # 提取所有output字段并合并为单个字符串
            output_strings = []
            for cmd in executed_commands:
                if "output" in cmd:
                    output_strings.append(cmd["output"])
            commands_string = "\n".join(output_strings)
        else:
            # 如果已经是字符串列表，直接合并
            commands_string = "\n".join(str(cmd) for cmd in executed_commands)
    else:
        commands_string = str(executed_commands) if executed_commands else ""
    
    if device_name:
        # 如果有设备信息，使用设备名作为键保存到system_info中
        if "device" in system_info:
            processed_system_info[device_name] = system_info["device"]
        elif "config" in system_info:
            processed_system_info[device_name] = system_info["config"]
        elif device_name in system_info:
            processed_system_info[device_name] = system_info[device_name]
        
        # 关键修复：将字符串格式的命令输出重新包装，使用设备名而不是"config"
        device_commands = {device_name: commands_string}
        
        # 调用write_log，传递重新组织的命令结构
        result = write_log.write_log(status, device_commands, processed_system_info, error_message)
    else:
        # 没有设备名时，使用原始数据
        result = write_log.write_log(status, commands_string, system_info, error_message)
    
    _log_message_printed = True
    return result

def main():
    global _log_message_printed
    _log_message_printed = False

    if len(sys.argv) != 2:
        print("使用方法:")
        print('  * 如未提供IP地址和掩码，将自动根据设备IP生成')
        print('  * 设备IP为192.168.56.n时，自动生成IP地址为172.n.x.1/24')
        print('  * 第一个接口为172.n.1.1/24，第二个为172.n.2.1/24，依此类推')
        print('  * IPv6地址生成规则为2025:172:n:x::1/64')
        print('  * IP地址、掩码数量必须与接口数量严格匹配')
        print('  * 提供vlan时，将在物理接口配置access模式，并在VLAN接口上配置IP')
        print('  * 不提供vlan时，将直接在物理接口上配置IP(可能需要自动切换接口模式)')
        print('  * 环回接口不使用VLAN参数，直接配置IP')

        # 添加环回口配置示例
        print('\n环回口配置示例:')
        print('python interface_config.py {"ip":"192.168.1.100","username":"admin","password":"password123",' 
              '"interface":"LoopBack0,GigabitEthernet1/0/1","vlan":"10",'
              '"ip_address":"10.0.0.1,192.168.10.1","mask":"32,24"}')

        # 在帮助信息中添加新参数说明
        print("使用方法:")
        print('  * 可通过interface指定完整接口名称，如"GigabitEthernet1/0/1"')
        print('  * 或通过interface_numbers指定接口编号部分，如"1/0/1"')
        print('  * 对于环回接口，可以使用"0"代替"LoopBack0"')

        # 添加使用示例
        print('\n使用接口编号示例:')
        print('python interface_config.py {"ip":"192.168.1.100","username":"admin","password":"password123",' 
              '"interface_numbers":"1/0/1,1/0/2","ip_address":"192.168.10.1,192.168.20.1","mask":"24,24"}')
        sys.exit(1)

    try:
        # 处理输入参数
        json_str = sys.argv[1]
        
        # 确保JSON字符串格式正确
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
            
        try:
            device_params = json.loads(json_str)
        except json.JSONDecodeError:
            print("\nJSON格式错误！请检查：")
            print("1. 所有属性名必须使用双引号")
            print("2. 所有值必须使用双引号")
            print("3. 不要在最后一个属性后加逗号")
            print("\n正确的格式示例：")
            print('IPv4配置示例:')
            print('python interface_config.py {"ip":"192.168.1.100","username":"admin","password":"password123",' 
                  '"device_type":"1","interface":"GigabitEthernet1/0/1","vlan":"10",'
                  '"ip_address":"192.168.10.1","mask":"24"}')
            print('\nIPv6配置示例:')
            print('python interface_config.py {"ip":"192.168.1.100","username":"admin","password":"password123",' 
                  '"device_type":"2","interface":"GigabitEthernet1/0/1",'
                  '"ip_address":"192.168.10.1","mask":"24",'
                  '"ipv6_address":"2001:db8::1","ipv6_prefix":"64"}')
            print('\n多接口配置示例:')
            print('python interface_config.py {"ip":"192.168.1.100","username":"admin","password":"password123",' 
                  '"device_type":"1","interface":"GigabitEthernet1/0/1,GigabitEthernet1/0/2","vlan":"10,20",'
                  '"ip_address":"192.168.10.1,192.168.20.1","mask":"24,24"}')
            sys.exit(1)

        # 基本必需参数验证
        base_params = ['hostip', 'username', 'password', 'interface']
        if not all(param in device_params for param in base_params):
            print("缺少基本参数，需要包含：", base_params)
            sys.exit(1)

        # 登录设备并进入系统视图
        status, ssh, executed_commands, system_info = login_and_enter_system_view(device_params)
        if status == "Failed":
            sys.exit(1)

        # 修改main函数中的接口处理部分
        # 使用新的接口参数解析函数
        interfaces = parse_interface_params(device_params, ssh)
        if not interfaces:
            print("错误: 未能获取有效的接口列表，使用默认接口")
            # 使用默认接口而不是退出程序
            interfaces = ["GigabitEthernet1/0/1"]
            print(f"使用默认接口: {', '.join(interfaces)}")
            # 仍然记录日志但不退出
            log_with_message_control("Warning", [], system_info, "未能获取有效的接口列表，使用默认接口")

        # 用映射后的接口名覆盖device_params['interface']，确保后续都用真实接口名
        device_params['interface'] = ','.join(interfaces)

        # 检查是否需要自动生成IP地址
        ip_stack = device_params.get('ip_stack', 'IPv4&IPv6')
        need_auto_ipv4 = ('ip_address' not in device_params) and (ip_stack in ['IPv4', 'IPv4&IPv6'])
        need_auto_ipv6 = ('ipv6_address' not in device_params) and (ip_stack in ['IPv6', 'IPv4&IPv6'])

        if need_auto_ipv4 or need_auto_ipv6:
            print("\n未提供IP地址，将根据isis_stack自动生成...")
            # 使用新的IP地址生成函数，传入设备IP
            auto_ipv4, auto_mask, auto_ipv6, auto_prefix = generate_ip_addresses(
                interfaces, 
                device_params.get('hostip', '192.168.1.1'),  # 提供设备IP
                ip_stack
            )
            
            # 根据isis_stack更新device_params
            if need_auto_ipv4:
                ip_address = auto_ipv4
                mask = auto_mask
                device_params['ip_address'] = ','.join(auto_ipv4)
                device_params['mask'] = ','.join(auto_mask)
                print("自动生成IPv4地址:")
                for i, (intf, ip, m) in enumerate(zip(interfaces, auto_ipv4, auto_mask)):
                    print(f"  接口 {intf}: {ip}/{m}")
            
            if need_auto_ipv6:
                ipv6_address = auto_ipv6
                ipv6_prefix = auto_prefix
                device_params['ipv6_address'] = ','.join(auto_ipv6)
                device_params['ipv6_prefix'] = ','.join(auto_prefix)
                print("自动生成IPv6地址:")
                for i, (intf, ip, p) in enumerate(zip(interfaces, auto_ipv6, auto_prefix)):
                    print(f"  接口 {intf}: {ip}/{p}")

        # 解析接口和IP地址参数
        ip_addresses = [i.strip() for i in device_params['ip_address'].split(',')]
        masks = [m.strip() for m in device_params['mask'].split(',')]

        # 检查IP地址数量与接口数量是否匹配
        if len(ip_addresses) != len(interfaces):
            print(f"\n错误: IP地址数量({len(ip_addresses)})与接口数量({len(interfaces)})不匹配")
            print(f"接口列表: {interfaces}")
            print(f"IP地址列表: {ip_addresses}")
            sys.exit(1)

        # 检查掩码数量与接口数量是否匹配
        if len(masks) != len(interfaces):
            print(f"\n错误: 掩码数量({len(masks)})与接口数量({len(interfaces)})不匹配")
            print(f"接口列表: {interfaces}")
            print(f"掩码列表: {masks}")
            sys.exit(1)

        # IPv6参数检查
        if 'ipv6_address' in device_params and 'ipv6_prefix' in device_params:
            ipv6_addresses = [i.strip() for i in device_params['ipv6_address'].split(',')]
            ipv6_prefixes = [p.strip() for p in device_params['ipv6_prefix'].split(',')]
            
            # 检查IPv6地址数量与接口数量是否匹配
            if len(ipv6_addresses) != len(interfaces):
                print(f"\n错误: IPv6地址数量({len(ipv6_addresses)})与接口数量({len(interfaces)})不匹配")
                sys.exit(1)
            
            # 检查IPv6前缀数量与接口数量是否匹配
            if len(ipv6_prefixes) != len(interfaces):
                print(f"\n错误: IPv6前缀数量({len(ipv6_prefixes)})与接口数量({len(interfaces)})不匹配")
                sys.exit(1)

        # 解析可选的VLAN参数
        vlans = None
        if 'vlan' in device_params and device_params['vlan']:
            vlans = [v.strip() for v in device_params['vlan'].split(',')]
            
            # 检查VLAN参数数量是否与非环回口接口数量匹配
            non_loopback_count = sum(1 for intf in interfaces if not is_loopback_interface(intf))
            if len(vlans) != non_loopback_count:
                print(f"\n错误: VLAN参数数量({len(vlans)})与非环回口接口数量({non_loopback_count})不匹配")
                print("每个物理接口必须对应一个VLAN参数，请重新检查输入")
                print(f"物理接口: {[intf for intf in interfaces if not is_loopback_interface(intf)]}")
                print(f"VLAN参数: {vlans}")
                sys.exit(1)  # 退出程序

        # 设备类型判断 - 完全可选，不影响配置逻辑
        device_type = None
        if 'device_type' in device_params:
            device_type_input = device_params['device_type']
            # 只保留设备类型输入验证，但不强制使用
            if not (is_switch_device(device_type_input) or is_router_device(device_type_input)):
                print(f"警告: 设备类型 '{device_type_input}' 不受支持，但将继续执行配置")
                # 不退出程序，继续执行

        # 检查所有IP地址是否合法
        for ip in ip_addresses:
            if not login_args.check_ip(ip):
                print(f"IP地址格式错误: {ip}")
                sys.exit(1)

        # 检查所有掩码位数是否合法
        for mask in masks:
            if not re.match(r'^\d{1,2}$', mask) or not 0 <= int(mask) <= 32:
                print(f"掩码位数错误: {mask}")
                sys.exit(1)

        # 检查所有IPv6地址是否合法（如果提供了）
        ipv6_addresses = None
        ipv6_prefixes = None
        if 'ipv6_address' in device_params and 'ipv6_prefix' in device_params:
            ipv6_addresses = [i.strip() for i in device_params['ipv6_address'].split(',')]
            ipv6_prefixes = [p.strip() for p in device_params['ipv6_prefix'].split(',')]
            if len(interfaces) != len(ipv6_addresses) or len(interfaces) != len(ipv6_prefixes):
                print("配置错误：interface、ipv6_address和ipv6_prefix参数数量不匹配")
                sys.exit(1)
                
            # 使用我们自己定义的函数验证IPv6地址
            for ipv6 in ipv6_addresses:
                if not check_ipv6(ipv6):
                    print(f"IPv6地址格式错误: {ipv6}")
                    sys.exit(1)
                    
            # 验证IPv6前缀长度
            for prefix in ipv6_prefixes:
                if not re.match(r'^\d{1,3}$', prefix) or not 0 <= int(prefix) <= 128:
                    print(f"IPv6前缀长度错误: {prefix}")
                    sys.exit(1)

        # 在main函数中添加对IP地址的验证
        # 验证IP地址格式
        if not validate_ip_addresses(ip_addresses, ipv6_addresses, masks, ipv6_prefixes):
            sys.exit(1)

        try:
            executed_commands = []  # 记录所有执行的命令
            
            # 配置结果
            final_result = "succeed"
            last_error_message = ""  # 添加变量存储最后一个错误信息
            
            # 修改第1065-1112行的错误处理
            for i in range(len(interfaces)):
                # 获取当前接口相关信息
                current_interface = interfaces[i]
                is_loopback = is_loopback_interface(current_interface)
                
                # 获取IPv6地址和前缀（如果有）
                current_ipv6_address = ipv6_addresses[i] if ipv6_addresses and i < len(ipv6_addresses) else None
                current_ipv6_prefix = ipv6_prefixes[i] if ipv6_prefixes and i < len(ipv6_prefixes) else None
                
                # 获取当前接口对应的VLAN（如果有）
                current_vlan = None
                if vlans and i < len(vlans) and not is_loopback:
                    current_vlan = vlans[i]
                
                print(f"\n正在配置接口 {current_interface}...")
                
                # 统一配置逻辑，不区分设备类型，只看是否有VLAN参数
                result = config_ip(ssh, system_info, current_interface, ip_addresses[i], masks[i], 
                                   current_vlan, executed_commands, 
                                   current_ipv6_address, current_ipv6_prefix)
                
                # 处理返回值，可能是字符串或元组
                if isinstance(result, tuple):
                    status, actual_error_message = result
                else:
                    status = result
                    # 只有在没有具体错误信息时才构造通用错误信息
                    if status == "Failed":
                        if current_vlan:
                            vlan_interface = f"Vlan-interface{current_vlan}"
                            actual_error_message = f"为接口 {vlan_interface} 配置IPv4地址 {ip_addresses[i]}/{masks[i]} 失败"
                        else:
                            actual_error_message = f"为接口 {current_interface} 配置IPv4地址 {ip_addresses[i]}/{masks[i]} 失败"
                    else:
                        actual_error_message = None
                
                # 错误处理 - 使用实际的错误信息
                if status == "Failed":
                    final_result = "Failed"
                    last_error_message = actual_error_message
                    
                    # 确保system_info是字典类型并获取版本信息
                    if not isinstance(system_info, dict):
                        system_info = {}

                    # 获取系统信息
                    try:
                        # 使用get_system_info模块获取系统信息，而不是手动执行命令
                        system_info_from_module = get_system_info.get_system_info(ssh)
                        
                        if isinstance(system_info_from_module, dict):
                            # 保留已有的device_name
                            device_name = system_info.get("device_name")
                            system_info = system_info_from_module
                            if device_name and "device_name" not in system_info:
                                system_info["device_name"] = device_name
                        else:
                            system_info["device"] = str(system_info_from_module)
                    except Exception as e:
                        error_msg = f"获取系统信息失败: {str(e)}"
                        print(error_msg)
                        system_info["device"] = error_msg

                    # 确保system_info不为空
                    if not system_info:
                        system_info = {"device": "未能获取设备信息"}

                    log_with_message_control("Failed", executed_commands, system_info, last_error_message)
                    break

            # 修改main函数中获取系统信息的部分，约在第1170-1220行

            if final_result == "succeed":
                print("\n配置完成，3秒后自动退出...")
                
                # 确保system_info是字典
                if not isinstance(system_info, dict):
                    system_info = {}
                
                try:
                    # 使用get_system_info模块获取完整的系统信息
                    system_info_from_module = get_system_info.get_system_info(ssh)
                    
                    # 确保返回的是字典类型
                    if isinstance(system_info_from_module, dict):
                        # 合并字典，保留已有的设备名称
                        device_name = system_info.get("device_name")
                        system_info = system_info_from_module
                        if device_name and "device_name" not in system_info:
                            system_info["device_name"] = device_name
                    else:
                        # 如果不是字典，则保留原有system_info，只添加版本信息
                        print("警告: get_system_info返回的不是字典类型")
                        system_info["device"] = str(system_info_from_module)
                except Exception as e:
                    error_msg = f"获取系统信息失败: {str(e)}"
                    print(f"\n警告: {error_msg}")
                    system_info["device"] = error_msg
                
                log_with_message_control(final_result, executed_commands, system_info)
                time.sleep(3)
                sys.exit(0)
            else:
                # 确保错误情况下也有正确的system_info
                if not isinstance(system_info, dict):
                    system_info = {}
                
                try:
                    # 使用get_system_info模块获取系统信息
                    system_info_from_module = get_system_info.get_system_info(ssh)
                    
                    # 确保返回的是字典类型
                    if isinstance(system_info_from_module, dict):
                        # 合并字典，保留已有的设备名称
                        device_name = system_info.get("device_name")
                        system_info = system_info_from_module
                        if device_name and "device_name" not in system_info:
                            system_info["device_name"] = device_name
                    else:
                        system_info["device"] = str(system_info_from_module)
                except Exception as e:
                    error_msg = f"获取系统信息失败: {str(e)}"
                    system_info["device"] = error_msg
                
                # 确保有设备信息
                if not system_info:
                    system_info = {"device": "配置失败，未能获取设备信息"}
                    
                log_with_message_control(final_result, executed_commands, system_info, last_error_message)
                sys.exit(1)
                
        finally:
            # 确保在最后关闭SSH连接
            if ssh:
                ssh.disconnect()

    except Exception as e:
        print(f"执行出错：{str(e)}")
        sys.exit(1)  # 发生异常时立即退出

if __name__ == "__main__":
    main()

# 在文件末尾添加这些新函数

def enter_interface_mode(ssh, interface, executed_commands=None, skip_vlan_creation=False):
    """
    进入接口配置模式
    
    Args:
        ssh: SSH连接对象
        interface (str): 接口名称
        executed_commands (list): 记录已执行命令的列表，可选
        skip_vlan_creation (bool): 是否跳过VLAN创建，可选
        
    Returns:
        tuple: (status, executed_cmd_list)
               status为"succeed"或"Failed"，executed_cmd_list为执行的命令列表
    """
    if executed_commands is None:
        executed_commands = []
        
    executed_cmd_list = []
    
    # 进入接口配置
    cmd = f"interface {interface}"
    output = ssh.send_command(
        cmd,
        strip_prompt=False,
        strip_command=False,
        expect_string=r"]"
    )
    print(output.rstrip(), end='')
    
    # 提取提示符和命令输出
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_cmd_list.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 检查命令输出
    status = check_device_output.check_device_output(output)
    if status == "Failed":
        error_message = f"进入接口 {interface} 配置模式失败，请检查接口名称是否正确或设备是否支持该接口类型"
        print(f"\n错误: {error_message}")
        log_with_message_control(status, executed_commands, {}, error_message)
        return status, executed_cmd_list
        
    return "succeed", executed_cmd_list

def create_vlan_and_add_interface(ssh, vlan_id, interface, executed_commands=None):
    """
    创建VLAN并将物理接口加入VLAN
    
    Args:
        ssh: SSH连接对象
        vlan_id (str): VLAN ID
        interface (str): 物理接口名称
        executed_commands (list): 记录已执行命令的列表，可选
        
    Returns:
        str: 执行状态，"succeed"或"Failed"
    """
    if executed_commands is None:
        executed_commands = []
        
    # 创建VLAN
    status = create_vlan(ssh, vlan_id, executed_commands)
    if status == "Failed":
        return status
        
    # 退出VLAN配置视图
    cmd = "quit"
    output = ssh.send_command(
        cmd,
        strip_prompt=False,
        strip_command=False,
        expect_string=r"]"
    )
    print(output.rstrip(), end='')
    prompt = output.strip().splitlines()[-1] if output.strip() else ""
    cmd_output = output.strip()[:-len(prompt)].strip() if prompt else output.strip()
    executed_commands.append({"command": cmd, "output": f"{prompt}\n{cmd_output}" if prompt else output.strip()})
    
    # 将物理接口加入VLAN
    status = config_port_vlan(ssh, interface, vlan_id, executed_commands)
    if status == "Failed":
        return status
        
    return "succeed"

def get_vlan_id_for_interface(device_params, interface_index):
    """
    获取指定接口对应的VLAN ID
    
    Args:
        device_params (dict): 包含设备参数的字典
        interface_index (int): 接口索引
        
    Returns:
        str: VLAN ID，如果不存在则返回None
    """
    if 'vlan' not in device_params:
        return None
        
    vlan_param = device_params['vlan']
    
    # 处理列表形式的VLAN参数
    if isinstance(vlan_param, list):
        if interface_index < len(vlan_param):
            return vlan_param[interface_index]
    # 处理字符串形式的VLAN参数
    elif isinstance(vlan_param, str):
        if ',' in vlan_param:
            vlan_list = [v.strip() for v in vlan_param.split(',')]
            if interface_index < len(vlan_list):
                return vlan_list[interface_index]
        else:
            return vlan_param
            
    return None