# 配置H3C设备VRRP的Python脚本
# 1.使用login_args.py中的login函数登录到设备
# 2.设备的角色有两个，第一个是VRRP的主设备，另一个是VRRP的备份设备
# 3.主设备和备份设备的配置是不同的，主设备需要配置优先级和虚拟IP地址，备份设备只需要配置虚拟IP地址
# 4.所有操作都需要调用现成模块记录日志

import sys
import time
import os
import re
import json
import login_args
import interface_config
import check_device_output
import get_system_info
import write_log

def vrrp_config(hostip, username, password, role, interface_name, virtual_ip, ip_address, mask, priority=None, vlan=None):
    """
    配置H3C设备的VRRP功能 - 移除状态检查部分
    """
    # 记录执行的命令
    executed_commands = []
    device_name = None  # 添加设备名称变量
    
    # 登录到设备
    net_connect = login_args.login(hostip, username, password)
    if not net_connect:
        print(f"错误: 登录设备 {hostip} 失败。")
        return False, executed_commands, None, f"登录设备 {hostip} 失败", device_name
    
    # 获取系统信息
    system_info = get_system_info.get_system_info(net_connect)
    if not system_info:
        print(f"错误: 获取设备 {hostip} 系统信息失败。")
        return False, executed_commands, None, f"获取设备 {hostip} 系统信息失败", device_name
    
    # 新增：记录Running状态日志，不包含具体输出和系统信息
    try:
        # 预先确定设备角色作为设备名称
        temp_device_name = role.lower() if role else hostip
        # 创建空的结果字典和系统信息字典
        empty_results = {}
        empty_system_info = {}
        # 重定向标准输出以捕获write_log可能打印的内容
        import io
        import sys
        original_stdout = sys.stdout
        sys.stdout = io.StringIO()  # 创建临时输出缓冲区
        
        # 记录Running状态
        write_log.write_log("Running", empty_results, empty_system_info, file_suffix="status")
        
        # 恢复标准输出
        sys.stdout = original_stdout

    except Exception as e:
        print(f"记录运行状态日志失败: {str(e)}")
        # 仅打印错误，继续主流程
    
    try:
        # 定义execute_command函数 - 最终修复方案
        def execute_command(cmd, expect_string=r"\[.*\]"):
            """执行命令并显示输出 - 最终修复方案"""
            nonlocal current_prompt
            
            # 打印命令 - 每条命令单独一行
            print(f"{current_prompt}{cmd}")
            
            # 设置合适的expect_string
            if cmd.strip() == "quit":
                actual_expect_string = r"[>#\]]"
            elif cmd.strip() == "return":
                actual_expect_string = r">"
            else:
                actual_expect_string = expect_string
            
            # 执行命令部分
            try:
                output = net_connect.send_command(
                    cmd,
                    expect_string=actual_expect_string,
                    strip_command=True,
                    strip_prompt=True,
                    delay_factor=2
                )
            except Exception as e:
                # 确保异常打印在新行
                print(f"错误: 命令 '{cmd}' 执行过程中出现连接问题: {str(e)}")
                
                # 记录命令和错误输出
                executed_commands.append({"command": cmd, "output": f"连接错误: {str(e)}"})
                
                # 立即记录错误日志并退出程序
                error_msg = f"命令 '{cmd}' 执行失败: {str(e)}"
                result_format = {device_name or hostip: "\n".join([cmd["output"] for cmd in executed_commands])}
                log_path = write_log.write_log("Failed", result_format, {device_name or hostip: system_info}, error_msg)
                if log_path:
                    print(f"\n日志已保存至: {log_path}")
                
                # 断开连接并立即退出程序
                if net_connect:
                    net_connect.disconnect()
                sys.exit(1)  # 立即终止程序
            
            # 错误检查部分修改
            if check_device_output.check_device_output(output) == "Failed":
                # 添加醒目的错误提示
                print(f"错误: 命令 '{cmd}' 执行失败，设备返回错误信息:")
                print(output.strip())
                
                # 记录错误日志
                error_log = f"{current_prompt}{cmd}\n{output}"
                executed_commands.append({"command": cmd, "output": error_log})
                
                # 立即记录错误日志并退出程序
                error_msg = f"命令 '{cmd}' 执行失败: {output.strip()}"
                result_format = {device_name or hostip: "\n".join([cmd["output"] for cmd in executed_commands])}
                log_path = write_log.write_log("Failed", result_format, {device_name or hostip: system_info}, error_msg)
                if log_path:
                    print(f"\n日志已保存至: {log_path}")
                
                # 断开连接并立即退出程序
                if net_connect:
                    net_connect.disconnect()
                sys.exit(1)  # 立即终止程序
            
            # 修改输出处理 - 关键修复
            clean_output = output.strip()
            if clean_output:
                # 有输出时，在新行显示
                print(clean_output)
            # 无输出时，不做任何处理 (不添加print())
            
            # 日志记录
            log_output = f"{current_prompt}{cmd}\n{output}" if output.strip() else f"{current_prompt}{cmd}"
            executed_commands.append({"command": cmd, "output": log_output})
            
            # 提示符更新不变
            if cmd == "system-view":
                current_prompt = "[H3C]"
            elif cmd.startswith("sysname "):
                new_name = cmd.split(" ")[1]
                current_prompt = f"[{new_name}]"
            elif cmd.startswith("interface "):
                interface = cmd.split(" ")[1]
                # 修复提示符重复添加问题
                if '-' in current_prompt:
                    # 已经在接口视图，需要先退回基本提示符
                    base_prompt = current_prompt.split('-')[0]
                    current_prompt = f"{base_prompt}-{interface}]"
                else:
                    # 首次进入接口视图
                    parts = current_prompt.split(']')
                    current_prompt = f"{parts[0]}-{interface}]"
            elif cmd == "quit":
                # 从接口视图返回到系统视图
                if '-' in current_prompt:
                    current_prompt = current_prompt.split('-')[0] + ']'
                # 其他退出处理不变
            else:
                # 只有绝对必要时才使用find_prompt()
                try:
                    # 使用静默方式执行，完全隐藏交互
                    with open(os.devnull, 'w') as f:
                        old_stdout = sys.stdout
                        sys.stdout = f
                        current_prompt = net_connect.find_prompt()
                        sys.stdout = old_stdout
                except:
                    # 如果获取失败，保持提示符不变
                    pass
            
            return output
        
        # 获取初始提示符
        try:
            current_prompt = net_connect.find_prompt()
        except:
            net_connect.write_channel('\n')
            time.sleep(0.5)
            current_prompt = net_connect.read_until_pattern(r"[>\]]$").strip()
        
        # 进入系统视图
        execute_command("system-view")
        
        # 根据角色设置系统名称，并保存设备名称
        if role.lower() == 'master':
            execute_command("sysname master")
            device_name = "master"  # 保存设备名称
        elif role.lower() == 'backup':
            execute_command("sysname backup")
            device_name = "backup"  # 保存设备名称
        
        # 接口映射功能 - 在确定实际接口前添加此段代码
        print(f"\n正在为设备 {device_name if device_name else hostip} 获取接口列表...")
        try:
            # 保存当前命令列表状态
            original_commands_len = len(executed_commands)
            
            # 获取设备所有接口
            all_interfaces = interface_config.get_device_interfaces(net_connect)
            
            # 尝试映射接口名称
            if interface_name and not interface_name.lower().startswith(('gigabitethernet', 'ge', 'ten-gigabitethernet', 'xe')):
                # 如果用户输入的是简单接口编号
                interfaces_to_map = [interface_name]
                
                # 映射接口名称
                mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces_to_map, net_connect)
                
                if mapped_interfaces and mapped_interfaces[0]:
                    original_interface = interface_name
                    interface_name = mapped_interfaces[0]
                    print(f"接口映射成功: {original_interface} -> {interface_name}")
                else:
                    print(f"警告: 无法映射接口 '{interface_name}'，将使用原始输入")
            else:
                print(f"使用完整接口名称: {interface_name}")
            
            # 恢复命令列表，移除接口查询相关命令
            if len(executed_commands) > original_commands_len:
                executed_commands = executed_commands[:original_commands_len]
                
        except Exception as e:
            print(f"接口映射过程中出错: {str(e)}")
            print("将使用原始接口名称")
        
        # 确定实际要配置的接口
        actual_interface = interface_name

        if vlan:
            # 创建VLAN并将接口加入VLAN
            # 记录当前提示符状态，确保create_vlan后能恢复正确提示符
            pre_vlan_prompt = current_prompt
            
            # 执行VLAN模块功能
            if not interface_config.create_vlan(net_connect, vlan, executed_commands):
                print(f"错误: 创建VLAN {vlan}失败")
                return False, executed_commands, system_info, f"创建VLAN {vlan}失败", device_name
            
            # 恢复正确的提示符
            current_prompt = pre_vlan_prompt
            
            # 同样处理接口VLAN配置
            if not interface_config.config_port_vlan(net_connect, interface_name, vlan, executed_commands):
                print(f"错误: 将接口 {interface_name} 加入VLAN {vlan}失败")
                return False, executed_commands, system_info, f"将接口加入VLAN失败", device_name
            
            # 恢复正确的提示符
            current_prompt = pre_vlan_prompt
            
            # 使用VLAN接口作为配置VRRP的接口
            actual_interface = f"Vlan-interface {vlan}"
            
            # 如果VLAN接口不存在，创建并进入该接口
            execute_command(f"interface {actual_interface}")
        
        else:
            # 对物理接口进行类型检查和转换
            interface_mode = interface_config.check_interface_mode(net_connect, interface_name)
            
            # 如果是bridge模式，则切换为route模式
            if interface_mode == "bridge":
                if not interface_config.switch_interface_to_route_mode(net_connect, interface_name, executed_commands):
                    print(f"错误: 无法将接口 {interface_name} 切换为route模式")
                    return False, executed_commands, system_info, f"将接口 {interface_name} 切换为route模式失败", device_name

        # 进入接口视图
        execute_command(f"interface {actual_interface}")
        
        # 配置接口IP地址
        if ip_address and mask:
            execute_command(f"ip address {ip_address} {mask}")
        
        # VRRP配置部分
        if role.lower() == 'master':
            if priority is None:
                print(f"错误: 设备 {hostip} (主设备) 必须指定优先级。")
                return False, executed_commands, system_info, "主设备未指定优先级", device_name
            
            execute_command(f"vrrp vrid 1 virtual-ip {virtual_ip}")
            execute_command(f"vrrp vrid 1 priority {priority}")
        
        elif role.lower() == 'backup':
            execute_command(f"vrrp vrid 1 virtual-ip {virtual_ip}")
        
        else:
            print(f"错误: 设备 {hostip} 角色无效。请使用 'master' 或 'backup'。")
            return False, executed_commands, system_info, f"无效的设备角色: {role}", device_name
        
        # 退出接口视图
        execute_command("quit")
        
        # 返回成功结果和执行命令，不包含VRRP状态信息
        return True, executed_commands, system_info, None, device_name
    
    except Exception as e:
        # 打印自定义错误信息
        error_msg = f"错误: 设备 {hostip} 执行命令失败，{str(e)}"
        print(error_msg)
        # 返回失败结果
        return False, executed_commands, system_info, error_msg, device_name
    finally:
        if net_connect:
            net_connect.disconnect()

def check_vrrp_status(net_connect, device_role, executed_commands):
    """
    检查VRRP状态
    Args:
        net_connect: Netmiko连接对象
        device_role: 设备角色 ('master' 或 'backup')
        executed_commands: 执行命令记录列表
    Returns:
        tuple: (状态正常与否的布尔值, 状态信息)
    """
    try:
        # 等待VRRP状态稳定
        print("\n等待20秒让VRRP状态稳定...")
        time.sleep(20)
        
        # 执行display vrrp verbose命令
        print("\n正在检查VRRP状态...")
        cmd = "display vrrp verbose"
        output = net_connect.send_command(
            cmd,
            strip_prompt=False,
            strip_command=False,
            delay_factor=2
        )
        
        # 记录命令
        executed_commands.append({"command": cmd, "output": output})
        
        # 打印输出
        print(output)
        
        # 解析输出，提取State字段
        state = None
        for line in output.split("\n"):
            if "State" in line:
                state = line.split(":")[-1].strip()
                break
        
        # 如果找不到State字段
        if not state:
            return False, {"role": device_role, "state": "Unknown", "raw_output": output}
        
        # 根据角色检查状态
        if device_role.lower() == "master":
            is_correct = state.lower() == "master"
            expected_state = "Master"
        elif device_role.lower() == "backup":
            is_correct = state.lower() == "backup" 
            expected_state = "Backup"
        else:
            return False, {"role": device_role, "state": state, "expected_state": "Unknown", "raw_output": output}
        
        status_info = {
            "role": device_role,
            "state": state,
            "expected_state": expected_state,
            "status": "正常" if is_correct else "异常",
        }
        
        return is_correct, status_info
        
    except Exception as e:
        print(f"\n检查VRRP状态时出错: {str(e)}")
        return False, {"role": device_role, "state": "Error", "error_message": str(e)}

def check_all_vrrp_status(devices, all_vrrp_status):
    """
    在所有设备配置完成后，检查VRRP状态
    Args:
        devices: 设备列表
        all_vrrp_status: 用于存储VRRP状态的字典
    Returns:
        tuple: (是否成功, 错误消息列表)
    """
    print("\n所有设备配置完成，等待20秒让VRRP状态稳定...")
    time.sleep(20)
    
    error_msgs = []
    success = True
    
    # 依次检查每个设备的VRRP状态
    for device in devices:
        hostip = device.get('hostip')
        username = device.get('username')
        password = device.get('password')
        role = device.get('role')
        device_name = role.lower() if role else hostip  # 使用角色作为设备名称
        
        print(f"\n正在检查设备 {device_name} ({hostip}) 的VRRP状态...")
        
        # 登录设备
        net_connect = login_args.login(hostip, username, password)
        if not net_connect:
            error_msg = f"登录设备 {hostip} 失败，无法检查VRRP状态"
            print(f"错误: {error_msg}")
            error_msgs.append(error_msg)
            success = False
            continue
            
        try:
            # 执行display vrrp verbose命令
            print(f"在设备 {device_name} 上执行: display vrrp verbose")
            cmd = "display vrrp verbose"
            output = net_connect.send_command(
                cmd,
                strip_prompt=False,
                strip_command=False,
                delay_factor=2
            )
            
            # 打印输出
            print(output)
            
            # 解析输出，提取State字段
            state = None
            for line in output.split("\n"):
                if "State" in line:
                    state = line.split(":")[-1].strip()
                    break
            
            # 记录状态信息
            status_info = {
                "role": role,
                "state": state if state else "Unknown",
            }
            
            # 检查是否符合预期
            is_correct = False
            if role.lower() == "master" and state and state.lower() == "master":
                is_correct = True
            elif role.lower() == "backup" and state and state.lower() == "backup":
                is_correct = True
                
            status_info["status"] = "正常" if is_correct else "异常"
            status_info["expected_state"] = role.capitalize()
            
            # 保存状态
            all_vrrp_status[device_name] = status_info
            
            # 检查状态是否正确
            if not is_correct:
                error_msg = f"设备 {device_name} 的VRRP状态 ({state if state else 'Unknown'}) 不是预期的 {role.capitalize()}"
                print(f"错误: {error_msg}")
                error_msgs.append(error_msg)
                success = False
            else:
                print(f"设备 {device_name} 的VRRP状态正常: {state}")
                
        except Exception as e:
            error_msg = f"检查设备 {device_name} 的VRRP状态失败: {str(e)}"
            print(f"错误: {error_msg}")
            error_msgs.append(error_msg)
            success = False
            all_vrrp_status[device_name] = {
                "role": role,
                "state": "Error",
                "error_message": str(e)
            }
            
        finally:
            if net_connect:
                net_connect.disconnect()
    
    return success, error_msgs

def main():
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("使用方法:")
        print(f'python {os.path.basename(__file__)} \'{{参数}}\'')
        print("\n参数格式:")
        print('"hostip":"192.168.1.1,192.168.1.2"')
        print('"username":"admin" (单个值将应用于所有设备)')
        print('"password":"password" (单个值将应用于所有设备)')
        # 删除role参数说明，因为默认第一台设备为master，第二台为backup
        print('"dut1_interface":"1/0/1" (第一台设备的接口)')
        print('"dut2_interface":"1/0/2" (第二台设备的接口)')
        print('"dut1_interface_ip":"192.168.1.1" (可选，默认为172.172.1.252)')
        print('"dut2_interface_ip":"192.168.1.2" (可选，默认为172.172.1.253)')
        print('"mask":"24,24" (可选，默认为24,24)')
        print('"virtual_ip":"192.168.1.254" (可选，默认为172.172.1.254)')
        print('"priority":"120" (可选，master设备的优先级值，默认为150)')
        print('"vlan":"10,10" (可选参数)')
        
        print("\n完整示例:")
        print(f'python {os.path.basename(__file__)} \'{{"hostip":"192.168.1.1,192.168.1.2","username":"admin","password":"password","dut1_interface":"1/0/1","dut2_interface":"1/0/2","dut1_interface_ip":"192.168.1.1","dut2_interface_ip":"192.168.1.2","mask":"24,24","virtual_ip":"192.168.1.254","priority":"120","vlan":"10,10"}}\'')
        sys.exit(1)
    
    # 解析JSON参数
    try:
        json_str = sys.argv[1]
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
        config = json.loads(json_str)
        
        # 获取基本参数
        hostips = config.get('hostip', '').split(',')
        usernames = config.get('username', '').split(',')
        passwords = config.get('password', '').split(',')
        
        # 修改用户名和密码处理，确保列表长度足够
        # 确保usernames和passwords列表长度与hostips一致
        if len(usernames) == 1 and len(hostips) > 1:
            usernames = usernames * len(hostips)
        if len(passwords) == 1 and len(hostips) > 1:
            passwords = passwords * len(hostips)
        
        # 自动分配角色
        if len(hostips) == 1:
            roles = ['master']
        else:
            roles = ['master', 'backup'] + ['backup'] * (len(hostips) - 2)
            roles = roles[:len(hostips)]  # 确保角色列表长度与设备数量匹配
        print(f"自动分配角色: 第一台设备为master，其余设备为backup")
        
        # 获取接口名称 - 采用新的参数名
        interface_names = []
        if len(hostips) >= 1:
            dut1_interface = config.get('dut1_interface', '')
            interface_names.append(dut1_interface)
        if len(hostips) >= 2:
            dut2_interface = config.get('dut2_interface', '')
            interface_names.append(dut2_interface)
        
        # 为额外的设备添加默认接口名
        for i in range(2, len(hostips)):
            extra_interface = config.get(f'dut{i+1}_interface', '')
            if not extra_interface:
                print(f"警告: 未提供设备{i+1}的接口名称，将使用默认值")
                extra_interface = "1/0/1"
            interface_names.append(extra_interface)
        
        # 获取IP地址 - 采用CIDR格式
        ip_addresses = []
        masks = []

        if len(hostips) >= 1:
            dut1_ip_cidr = config.get('dut1_interface_ip', '172.172.1.252/24')
            # 从CIDR格式中提取IP和掩码
            if '/' in dut1_ip_cidr:
                ip, mask = dut1_ip_cidr.split('/')
                ip_addresses.append(ip)
                masks.append(mask)
            else:
                # 如果没有提供CIDR格式，使用默认值
                ip_addresses.append(dut1_ip_cidr)
                masks.append('24')

        if len(hostips) >= 2:
            dut2_ip_cidr = config.get('dut2_interface_ip', '172.172.1.253/24')
            # 从CIDR格式中提取IP和掩码
            if '/' in dut2_ip_cidr:
                ip, mask = dut2_ip_cidr.split('/')
                ip_addresses.append(ip)
                masks.append(mask)
            else:
                # 如果没有提供CIDR格式，使用默认值
                ip_addresses.append(dut2_ip_cidr)
                masks.append('24')
            
        # 为额外的设备添加默认IP和掩码
        for i in range(2, len(hostips)):
            extra_ip_cidr = config.get(f'dut{i+1}_interface_ip', '')
            if not extra_ip_cidr:
                # 生成默认IP和掩码: 172.172.1.(254+i)/24
                extra_ip = f'172.172.1.{253+i}'
                extra_mask = '24'
                print(f"警告: 未提供设备{i+1}的IP地址，将使用默认值: {extra_ip}/{extra_mask}")
            else:
                # 从CIDR格式中提取IP和掩码
                if '/' in extra_ip_cidr:
                    extra_ip, extra_mask = extra_ip_cidr.split('/')
                else:
                    extra_ip = extra_ip_cidr
                    extra_mask = '24'
                    
            ip_addresses.append(extra_ip)
            masks.append(extra_mask)
        
        # 添加默认虚拟IP处理  
        virtual_ips = config.get('virtual_ip', '').split(',')
        if not virtual_ips or virtual_ips[0] == '':
            virtual_ips = ['172.172.1.254'] * len(hostips)  # 为所有设备使用相同的默认虚拟IP
            print(f"未提供虚拟IP，使用默认值: {virtual_ips[0]}")
        elif len(virtual_ips) == 1 and len(hostips) > 1:
            # 如果只提供一个虚拟IP，复制应用到所有设备
            virtual_ips = virtual_ips * len(hostips)
            print(f"使用相同的虚拟IP {virtual_ips[0]} 应用于所有设备")
        
        # 获取优先级参数
        priority = config.get('priority', '').strip()
        if not priority:
            priority = '150'  # 设置默认值
            print(f"未提供优先级值，使用默认值: 150")
        
        vlans = config.get('vlan', '').split(',') if 'vlan' in config else []

        # 以下代码与原脚本相同...
        # 创建设备列表
        devices = []
        for i in range(len(hostips)):
            # 处理priority参数 - 只给master设备设置priority
            if roles[i].strip().lower() == 'master':
                device_priority = priority  # 直接使用单个priority值
            else:
                device_priority = None
            
            # 处理可能的空VLAN
            vlan = vlans[i] if i < len(vlans) and vlans[i].strip() else None
            
            # 创建设备配置
            device = {
                'hostip': hostips[i].strip(),
                'username': usernames[i % len(usernames)].strip() if usernames else '',
                'password': passwords[i % len(passwords)].strip() if passwords else '',
                'role': roles[i % len(roles)].strip() if roles else '',
                'interface_name': interface_names[i % len(interface_names)].strip() if i < len(interface_names) else '',
                'ip_address': ip_addresses[i % len(ip_addresses)].strip() if ip_addresses else '',
                'mask': masks[i % len(masks)].strip() if masks else '',
                'virtual_ip': virtual_ips[i % len(virtual_ips)].strip() if virtual_ips else '',
                'priority': device_priority,
                'vlan': vlan
            }
            devices.append(device)
        
        # 初始化设备结果收集字典
        all_commands = {}
        all_system_info = {}
        all_vrrp_status = {}
        final_status = "succeed"
        error_msgs = []
        
        # 执行配置
        for i, device in enumerate(devices):
            # 提取必要参数
            hostip = device.get('hostip')
            username = device.get('username')
            password = device.get('password')
            role = device.get('role')
            interface_name = device.get('interface_name')
            ip_address = device.get('ip_address')
            mask = device.get('mask')
            virtual_ip = device.get('virtual_ip')
            priority = device.get('priority')
            vlan = device.get('vlan')
            
            # 检查必须的参数
            missing = []
            if not hostip: missing.append('hostip')
            if not username: missing.append('username')  
            if not password: missing.append('password')
            if not role: missing.append('role')
            if not interface_name: missing.append('interface_name')
            
            if missing:
                print(f"错误: 设备 {hostip if hostip else i+1} 缺少必要参数: {', '.join(missing)}")
                # 跳过当前设备继续处理下一个
                continue
            
            # 执行VRRP配置，注意返回值修改
            success, executed_commands, system_info, error_msg, device_name = vrrp_config(
                hostip, username, password, role, interface_name, 
                virtual_ip, ip_address, mask, priority, vlan
            )
            
            # 使用设备名称作为键，如果没有设备名称则使用IP
            device_key = device_name if device_name else hostip
            
            # 收集设备结果
            all_commands[device_key] = executed_commands
            all_system_info[device_key] = system_info
            
            # 只更新状态，不立即写日志
            if not success:
                final_status = "Failed"
                if error_msg:
                    error_msgs.append(f"{device_key}: {error_msg}")
        
        # 所有设备配置完成后，转换命令记录格式为设备原始回显
        result_format = {}
        for device_name, commands in all_commands.items():
            # 合并所有命令和输出为一个完整的字符串
            device_outputs = [cmd["output"] for cmd in commands]
            result_format[device_name] = "\n".join(device_outputs)

        # 所有设备配置完成后，统一检查VRRP状态
        if final_status == "succeed":
            print("\n所有设备配置完成，开始检查VRRP状态...")
            vrrp_success, vrrp_errors = check_all_vrrp_status(devices, all_vrrp_status)
            
            if not vrrp_success:
                final_status = "VRRP状态异常"
                error_msgs.extend(vrrp_errors)
        
        # 所有设备配置完成后，统一写一次日志
        error_message = "\n".join(error_msgs) if error_msgs else None
        log_path = write_log.write_log(final_status, {"result": result_format}, all_system_info, error_message, 
                               vrrp_status=all_vrrp_status)

        # 添加日志保存路径提示
        if log_path:
            print(f"\n日志已保存至: {log_path}")
        else:
            # 如果write_log没有返回路径，则使用默认路径格式
            log_dir = os.path.join("D:", "PY自动化", "result", "temp")
            log_file = f"VRRP_CONFIG_TEST_status.log"
            log_path = os.path.join(log_dir, log_file)
            print(f"\n日志已保存至: {log_path}")
            
    except json.JSONDecodeError as e:
        print(f"JSON格式错误: {str(e)}")
        print("请确保所有参数都使用双引号，且符合JSON格式要求。")
        sys.exit(1)
    except Exception as e:
        print(f"发生错误: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()