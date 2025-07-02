#写一个适用于H3C交换机和路由器的BGP配置脚本，实现以下功能：
#1. 使用现成的login_args.py中的login函数来实现登录认证等功能
#2. 登录成功后，默认下发system-view命令，用来进入系统视图
#3. 用户的输入参数里面有一个可选参数bgp_local_as，如果用户输入这个参数，那么下发bgp {bgp_local_as}命令，用来进入BGP进程的视图，如果用户不输入bgp_local_as参数，则默认为100
#4. 用户的输入参数里面有一个必选参数peer_ip和可选参数bgp_peer_as，下发peer {peer_ip} as-number {bgp_peer_as}命令，用来添加对等体。如果用户没有输入bgp_peer_as参数，则默认为100，否则使用用户输入的bgp_peer_as参数
#5. 用户的输入参数里面有一个可选参数conn_interface，如果用户输入这个参数，那么下发peer {peer_ip} connect-interface {conn_interface}命令，用来指定对等体的连接接口，否则不下发这个命令
#6. 用户的输入参数里面有一个必选参数address_type，参数的值可以是ipv4 unicast、ipv6 unicast、vpnv4、vpnv6、l2vpn evpn中的，下发address-family {address_type}命令，用来进入对应的地址族视图
#7. 在进入到地址簇视图后，执行peer {peer_ip} enable命令，启用对等体
#8. 用户输入的参数里面有两个可选参数network和prefix，当{address_type}的值为ipv4 unicast或ipv6 unicast时，用户输入的network和prefix才生效。当输入的network值为IPv4类型时，那么在ipv4 unicast地址簇视图下执行network {network} {prefix}命令，如果用户输入的network类型为IPv6类型时，那么在ipv6 unicast地址簇视图下执行network {network} {prefix}命令，用来通告网段信息。如果用户没有输入这个参数，则不下发这个命令。其中，如果用户输入的network为IPv4地址，那么在address-family ipv4 unicast视图下下发这个命令，如果用户输入的network为IPv6地址，那么在address-family ipv6 unicast视图下下发这个命令
#9. 所有命令下发完成后，调用write_log、check_device_output、get_system_info这三个模块用来保存日志，如果命令全部下发成功，那么打印"配置完成，3秒后自动退出..."，然后等待三秒后退出，如果有任何一个命令下发失败，那么打印"配置失败，即将退出..."，然后马上退出

import time
import re
from netmiko import ConnectHandler
import os
import sys
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import login_args
import write_log
import check_device_output
import get_system_info
import interface_config

# 在文件开头添加全局变量
cached_interfaces = {}
log_recorded = False

def bgp_config(hostip, username, password, bgp_local_as=100, peer_ip=None, bgp_peer_as=100, conn_interface=None, address_type=None, network_advertise=None):
    """配置BGP"""
    # 先建立SSH连接
    net_connect = login_args.login(hostip, username, password)
    
    # 处理输出格式的函数 - 移到前面来
    def clean_output(output):
        """清理设备输出中的多余换行和格式问题"""
        # 移除末尾的空白字符和换行符
        output = output.rstrip()
        
        # 处理设备提示符与命令之间的多余换行
        output = re.sub(r'(<[A-Za-z0-9\-_]+>)\r?\n', r'\1', output)
        output = re.sub(r'(\[[A-Za-z0-9\-_]+\])\r?\n', r'\1', output)
        
        return output
    
    # 配置前清除缓冲区
    net_connect.clear_buffer()
    
    # 读取初始提示符以获取设备名
    net_connect.write_channel('\n')
    time.sleep(0.5)  # 减少等待时间
    output = net_connect.read_channel()
    output = clean_output(output)
    print(output, end='')  # 使用end=''避免额外换行
    
    # 提取设备名称 - 从提示符中获取
    device_name = "unknown"
    if output:
        # 尝试从提示符中提取设备名
        if '<' in output and '>' in output:
            try:
                device_name = re.search(r'<([^>]+)>', output).group(1)
            except:
                pass
        elif '[' in output and ']' in output:
            try:
                device_name = re.search(r'\[([^\]]+)\]', output).group(1)
            except:
                pass
    
    print(f"提取到的设备名称: {device_name}")
    
    if output:
        # 创建命令记录列表 - 先创建，不要立即记录Running状态
        executed_commands = []
        
        # 记录脚本启动状态为Running - 确保使用空列表，不影响后续命令记录
        initial_commands = []  # 使用单独的列表，与executed_commands隔离
        write_log.write_log("Running", initial_commands, {})
        
        # 修改execute_command函数，添加错误处理和消息格式
        def execute_command(command, wait_time=0.2):
            """执行命令并处理输出"""
            # 直接执行命令并获取输出，设置strip_command=True删除输出中的命令回显
            cmd_output = net_connect.send_command(
                command,
                expect_string=r"[\]\>]\s*$",
                delay_factor=0.5,
                strip_prompt=False,
                strip_command=True  # 关键修改：不在输出中包含命令本身
            )
            
            # 清理输出
            cmd_output = clean_output(cmd_output)
            
            # 为了控制台显示正确，我们需要手动添加命令
            print(f"{command}\n{cmd_output}", end='')
            
            # 修改日志记录格式，正确处理提示符和命令顺序
            match = re.search(r'(\[[A-Za-z0-9\-_]+\])$', cmd_output)
            if match:
                prompt = match.group(1)
                # 只保留实际输出，不含提示符和重复命令
                actual_output = cmd_output.replace(prompt, '')
                # 记录格式：[提示符]命令\n实际输出
                log_output = f"{prompt}{command}\n{actual_output}"
                executed_commands.append({"command": command, "output": log_output})
            else:
                # 如果无法识别提示符格式，使用简单格式
                executed_commands.append({"command": command, "output": f"{command}\n{cmd_output}"})
            
            # 检查命令是否执行成功
            status = check_device_output.check_device_output(cmd_output)
            if status == "Failed":
                error_message = f"执行命令 '{command}' 失败，设备返回了错误信息"
                print(f"\n错误: {error_message}")
                
                # 使用get_system_info模块获取系统信息（而不是直接执行命令）
                system_info = get_system_info.get_system_info(net_connect)
                
                write_log.write_log('Failed', executed_commands, system_info, error_message)
                net_connect.disconnect()
                sys.exit(1)
                
            return cmd_output
        
        # ---------------- 接口映射和配置部分 ----------------
        # 如果有连接接口，需要进行接口映射和IP配置
        if conn_interface and conn_interface.strip():
            print(f"\n检查BGP连接接口 {conn_interface}...")
            
            try:
                # 保存当前命令列表，避免接口查询命令混入BGP配置日志
                original_commands = executed_commands.copy()
                
                # 获取设备上的所有接口并进行映射
                all_interfaces = interface_config.get_device_interfaces(net_connect)
                print(f"成功获取到接口列表，共{len(all_interfaces)}个接口")
                
                # 进行接口映射
                interfaces_to_map = [conn_interface]
                mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces_to_map, net_connect)
                
                # 恢复命令列表，删除接口查询相关命令
                executed_commands = original_commands.copy()
                
                if mapped_interfaces and mapped_interfaces[0]:
                    original_interface = conn_interface
                    conn_interface = mapped_interfaces[0]
                    print(f"接口映射: {original_interface} -> {conn_interface}")
                    
                    # 检查接口类型（环回口或物理接口）
                    is_loopback = interface_config.is_loopback_interface(conn_interface)
                    print(f"接口 {conn_interface} {'是' if is_loopback else '不是'} 环回口")
                    
                    # 进入系统视图
                    execute_command("system-view")
                    
                    # 进入接口配置模式
                    execute_command(f"interface {conn_interface}")
                    
                    # 根据接口类型进行不同的配置
                    if is_loopback:
                        # 为环回口配置IP地址
                        ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                            [conn_interface], 
                            hostip=hostip, 
                            ip_stack="IPv4"
                        )
                        if ip_addresses and masks:
                            print(f"为环回口生成IP地址: {ip_addresses[0]}/{masks[0]}")
                            execute_command(f"ip address {ip_addresses[0]} {masks[0]}")
                    else:
                        # 处理物理接口
                        # 检查物理接口模式
                        interface_mode = interface_config.check_interface_mode(net_connect, conn_interface)
                        
                        # 如果是桥接模式，先转为路由模式
                        if interface_mode == "bridge":
                            print(f"接口 {conn_interface} 是桥接模式，将转换为路由模式")
                            try:
                                # 在进入接口配置模式后执行模式转换命令
                                execute_command("port link-mode route")
                                time.sleep(2)  # 等待模式转换完成
                                print(f"接口 {conn_interface} 已成功转换为路由模式")
                            except Exception as e:
                                print(f"转换接口模式时出错: {str(e)}")
                        
                        # 为物理接口配置IP
                        ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                            [conn_interface], 
                            hostip=hostip, 
                            ip_stack="IPv4"
                        )
                        if ip_addresses and masks:
                            print(f"为接口生成IP地址: {ip_addresses[0]}/{masks[0]}")
                            execute_command(f"ip address {ip_addresses[0]} {masks[0]}")
                    
                    # 退出接口配置模式
                    execute_command("quit")
                else:
                    print(f"警告: 无法映射接口 '{conn_interface}'，将使用原始输入名称")
                    execute_command("system-view")
                    execute_command(f"interface {conn_interface}")
                    execute_command("quit")
                    
            except Exception as e:
                print(f"接口 {conn_interface} 配置失败: {str(e)}")
                # 确保断开连接
                if 'net_connect' in locals():
                    try:
                        net_connect.disconnect()
                    except:
                        pass
                return "Failed", executed_commands, system_info, f"接口配置失败: {str(e)}"
        else:
            execute_command("system-view")
        
        # ---------------- 开始BGP配置 ----------------        
        # bgp命令
        if bgp_local_as:
            execute_command(f'bgp {bgp_local_as}')
        
        # peer as-number命令
        if peer_ip:
            execute_command(f'peer {peer_ip} as-number {bgp_peer_as}')
            
            # 连接接口命令 - 使用映射后的conn_interface
            if conn_interface and conn_interface.strip():
                execute_command(f'peer {peer_ip} connect-interface {conn_interface}')
        
        # 地址族命令部分修改
        if address_type:
            execute_command(f'address-family {address_type}')
            
            # 启用对等体
            execute_command(f'peer {peer_ip} enable')
            
            # 网络通告
            if network_advertise:
                if address_type == 'ipv4 unicast' or address_type == 'ipv6 unicast':
                    network = network_advertise["network"]
                    prefix = network_advertise["prefix"]
                    
                    execute_command(f'network {network} {prefix}')
            
            # 添加quit命令，退出地址族视图
            execute_command('quit')

        # 添加end命令，直接退出配置视图回到用户视图
        execute_command('end')
        
        # 收集最后的设备输出
        final_output = net_connect.read_channel()
        if final_output:
            print(final_output)
        
        # 在配置完成后获取系统信息
        system_info = get_system_info.get_system_info(net_connect)
            
        # 配置成功完成
        print("\n配置完成，3秒后自动退出...")
        write_log.write_log('succeed', executed_commands, system_info)
        time.sleep(3)
        net_connect.disconnect()
    else:
        system_info = {device_name: "无法获取设备版本信息"}
        write_log.write_log('Failed', '无法获取设备提示符', system_info)
        print("\n配置失败，即将退出...")
        sys.exit(1)

def bgp_config_single_device(device_params):
    """配置单台设备的BGP参数"""
    executed_commands = []
    system_info = {}
    
    # 【修复】先声明global，再使用变量
    global log_recorded
    
    # 【新增】记录脚本启动状态为Running（如果函数被直接调用）
    if not log_recorded:  # 使用全局变量避免重复记录
        write_log.write_log("Running", [], {})
        log_recorded = True
    
    try:
        # 提取参数
        hostip = device_params.get('hostip')
        username = device_params.get('username')
        password = device_params.get('password')
        bgp_local_as = device_params.get('bgp_local_as', 100)
        peer_ip = device_params.get('peer_ip')
        bgp_peer_as = device_params.get('bgp_peer_as', 100)
        conn_interface = device_params.get('conn_interface')
        address_type = device_params.get('address_type')
        network_advertise = device_params.get('network_advertise')
        local_ip = device_params.get('local_ip')
        
        # 登录设备
        net_connect = login_args.login(hostip, username, password)
        
        if not net_connect:
            return "Failed", [], {}, "登录失败"
        
        # 获取设备名称
        net_connect.write_channel('\n')
        time.sleep(0.5)
        output = net_connect.read_channel()
        
        device_name = "unknown"
        if output:
            if '<' in output and '>' in output:
                try:
                    device_name = re.search(r'<([^>]+)>', output).group(1)
                except:
                    pass
            elif '[' in output and ']' in output:
                try:
                    device_name = re.search(r'\[([^\]]+)\]', output).group(1)
                except:
                    pass
        
        device_params['device_name'] = device_name
        
        # 获取系统信息
        try:
            system_info = get_system_info.get_system_info(net_connect)
            print(f"获取到系统信息: {system_info.keys() if isinstance(system_info, dict) else 'Not a dict'}")
        except Exception as e:
            print(f"获取系统信息失败: {str(e)}")
            system_info = {device_name: f"获取系统信息失败: {str(e)}"}
        
        # 定义命令执行函数，显示设备原始回显
        def execute_bgp_command(command, timeout=30):
            """执行BGP配置命令并显示原始回显"""
            try:
                cmd_output = net_connect.send_command(
                    command,
                    expect_string=r'[>#\]\[]',
                    read_timeout=timeout,
                    strip_prompt=False,
                    strip_command=False
                )
                
                # 【核心修复】更全面地清理设备输出中的多余换行
                # 1. 移除末尾空白字符
                clean_output = cmd_output.rstrip()
                
                # 2. 通过多个替换处理不同情况的多余换行
                clean_output = re.sub(r'\r?\n\r?\n+', r'\r\n', clean_output)  # 多个连续换行变为单个
                
                # 3. 处理提示符后的换行 [XXX]\n -> [XXX] 
                clean_output = re.sub(r'(\[[^\]]+\])\s*\r?\n', r'\1 ', clean_output)
                clean_output = re.sub(r'(<[^>]+>)\s*\r?\n', r'\1 ', clean_output)
                
                # 4. 【关键】使用end=''避免print自己添加换行
                print(clean_output, end='')
                
                # 其他代码保持不变
                status = check_device_output.check_device_output(clean_output)
                if status == "Failed":
                    error_lines = [line for line in clean_output.splitlines() if "Error" in line or "error" in line or "This subnet" in line]
                    error_detail = ": " + " ".join(error_lines) if error_lines else ""
                    
                    executed_commands.append({
                        "command": command, 
                        "output": clean_output
                    })
                    raise Exception(f"命令执行失败{error_detail}")
                
                executed_commands.append({
                    "command": command, 
                    "output": clean_output
                })
                
                return clean_output
                
            except Exception as e:
                # 保存命令输出（如果有）
                executed_commands.append({
                    "command": command, 
                    "output": cmd_output if 'cmd_output' in locals() else f"执行失败: {str(e)}"
                })
                raise  # 直接重新抛出异常，保留原始错误信息
        
        # ------------- 接口映射和配置部分 -------------
        # 如果有连接接口，需要进行接口映射和IP配置
        if conn_interface and conn_interface.strip():
            print(f"\n检查BGP连接接口 {conn_interface}...")
            
            try:
                # 保存当前命令列表，避免接口查询命令混入BGP配置日志
                original_commands = executed_commands.copy()
                
                # 获取设备上的所有接口并进行映射
                all_interfaces = interface_config.get_device_interfaces(net_connect)
                print(f"成功获取到接口列表，共{len(all_interfaces)}个接口")
                
                # 进行接口映射
                interfaces_to_map = [conn_interface]
                mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces_to_map, net_connect)
                
                # 恢复命令列表，删除接口查询相关命令
                executed_commands = original_commands.copy()
                
                if mapped_interfaces and mapped_interfaces[0]:
                    original_interface = conn_interface
                    conn_interface = mapped_interfaces[0]
                    print(f"接口映射: {original_interface} -> {conn_interface}")
                    
                    # 检查接口类型（环回口或物理接口）
                    is_loopback = interface_config.is_loopback_interface(conn_interface)
                    print(f"接口 {conn_interface} {'是' if is_loopback else '不是'} 环回口")
                    
                    # 进入系统视图
                    execute_bgp_command("system-view")
                    
                    # 进入接口配置模式
                    execute_bgp_command(f"interface {conn_interface}")
                    
                    # 根据接口类型进行不同的配置
                    if is_loopback:
                        # 为环回口配置IP地址
                        if local_ip:
                            execute_bgp_command(f"ip address {local_ip} 255.255.255.255")
                        else:
                            # 如果没有指定local_ip，生成一个
                            ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                                [conn_interface], 
                                hostip=hostip, 
                                ip_stack="IPv4"
                            )
                            if ip_addresses and masks:
                                print(f"为环回口生成IP地址: {ip_addresses[0]}/{masks[0]}")
                                execute_bgp_command(f"ip address {ip_addresses[0]} {masks[0]}")
                    else:
                        # 处理物理接口
                        # 检查物理接口模式
                        interface_mode = interface_config.check_interface_mode(net_connect, conn_interface)
                        
                        # 打印检测结果
                        print(f"检测到接口 {conn_interface} 为{interface_mode}模式")
                        
                        # 重新进入接口配置模式，因为check_interface_mode会退出接口配置模式
                        execute_bgp_command(f"interface {conn_interface}")
                        
                        # 如果是桥接模式，先转为路由模式
                        if interface_mode == "bridge":
                            print(f"接口 {conn_interface} 是桥接模式，将转换为路由模式")
                            try:
                                # 使用interface_config模块中的函数进行模式转换
                                result = interface_config.switch_interface_to_route_mode(net_connect, conn_interface, executed_commands)
                                if result is False:
                                    raise Exception(f"将接口 {conn_interface} 转换为路由模式失败")
                                print(f"接口 {conn_interface} 已成功转换为路由模式")
                            except Exception as e:
                                print(f"转换接口模式时出错: {str(e)}")
                                raise  # 重新抛出异常，终止执行
                        
                        # 为物理接口配置IP
                        if local_ip:
                            execute_bgp_command(f"ip address {local_ip} 255.255.255.0")
                        else:
                            # 如果没有指定local_ip，生成一个
                            ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                                [conn_interface], 
                                hostip=hostip, 
                                ip_stack="IPv4"
                            )
                            if ip_addresses and masks:
                                print(f"为接口生成IP地址: {ip_addresses[0]}/{masks[0]}")
                                execute_bgp_command(f"ip address {ip_addresses[0]} {masks[0]}")
                    
                    # 退出接口配置模式
                    execute_bgp_command("quit")
                else:
                    print(f"警告: 无法映射接口 '{conn_interface}'，将使用原始输入名称")
                    execute_bgp_command("system-view")
                    execute_bgp_command(f"interface {conn_interface}")
                    execute_bgp_command("quit")
                    
            except Exception as e:
                print(f"接口 {conn_interface} 配置失败: {str(e)}")
                # 确保断开连接
                if 'net_connect' in locals():
                    try:
                        net_connect.disconnect()
                    except:
                        pass
                return "Failed", executed_commands, system_info, f"接口配置失败: {str(e)}"
        else:
            execute_bgp_command("system-view")
        
        # ------------- BGP配置部分 -------------
        # 配置BGP
        bgp_cmd = f"bgp {bgp_local_as}"
        execute_bgp_command(bgp_cmd)
        
        # 配置对等体
        peer_cmd = f"peer {peer_ip} as-number {bgp_peer_as}"
        execute_bgp_command(peer_cmd)

        # 【新增】检查是否为EBGP（AS号不同），如果是则添加ebgp-max-hop命令
        if str(bgp_local_as) != str(bgp_peer_as):
            ebgp_hop_cmd = f"peer {peer_ip} ebgp-max-hop 255"
            execute_bgp_command(ebgp_hop_cmd)
        
        # 配置连接接口 - 使用映射后的conn_interface
        if conn_interface:
            conn_cmd = f"peer {peer_ip} connect-interface {conn_interface}"
            execute_bgp_command(conn_cmd)
        
        # 进入地址族
        af_cmd = f"address-family {address_type}"
        execute_bgp_command(af_cmd)
        
        # 启用对等体
        enable_cmd = f"peer {peer_ip} enable"
        execute_bgp_command(enable_cmd)
        
        # 网络宣告
        if network_advertise:
            network = network_advertise.get("network")
            prefix = network_advertise.get("prefix")
            if network and prefix:
                network_cmd = f"network {network} {prefix}"
                execute_bgp_command(network_cmd)
        
        # 退出配置
        execute_bgp_command("quit")  # 退出地址族
        execute_bgp_command("quit")  # 退出BGP
        execute_bgp_command("quit")  # 退出系统视图
        
        net_connect.disconnect()
        
        return "succeed", executed_commands, system_info, ""
        
    except Exception as e:
        error_msg = f"配置设备时出错: {str(e)}"
        
        if 'net_connect' in locals():
            try:
                net_connect.disconnect()
            except:
                pass
                
        return "Failed", executed_commands, system_info, error_msg

def configure_physical_interface(device_params):
    """仅配置物理接口的函数"""
    executed_commands = []
    system_info = {}
    
    try:
        # 提取参数
        hostip = device_params.get('hostip')
        username = device_params.get('username')
        password = device_params.get('password')
        conn_interface = device_params.get('conn_interface')
        local_ip = device_params.get('local_ip')
        
        # 登录设备
        net_connect = login_args.login(hostip, username, password)
        
        if not net_connect:
            return "Failed", [], {}, "登录失败"
        
        # 获取设备名称
        net_connect.write_channel('\n')
        time.sleep(0.5)
        output = net_connect.read_channel()
        
        device_name = "unknown"
        if output:
            if '<' in output and '>' in output:
                try:
                    device_name = re.search(r'<([^>]+)>', output).group(1)
                except:
                    pass
            elif '[' in output and ']' in output:
                try:
                    device_name = re.search(r'\[([^\]]+)\]', output).group(1)
                except:
                    pass
        
        device_params['device_name'] = device_name
        
        # 获取系统信息
        try:
            system_info = get_system_info.get_system_info(net_connect)
        except Exception as e:
            print(f"获取系统信息失败: {str(e)}")
            system_info = {device_name: f"获取系统信息失败: {str(e)}"}
        
        # 定义命令执行函数，显示设备原始回显
        def execute_command(command, timeout=30):
            """执行配置命令并显示原始回显"""
            try:
                cmd_output = net_connect.send_command(
                    command,
                    expect_string=r'[>#\]\[]',
                    read_timeout=timeout,
                    strip_prompt=False,
                    strip_command=False
                )
                
                # 清理设备输出中的多余换行
                clean_output = cmd_output.rstrip()
                clean_output = re.sub(r'\r?\n\r?\n+', r'\r\n', clean_output)
                clean_output = re.sub(r'(\[[^\]]+\])\s*\r?\n', r'\1 ', clean_output)
                clean_output = re.sub(r'(<[^>]+>)\s*\r?\n', r'\1 ', clean_output)
                
                print(clean_output, end='')
                
                status = check_device_output.check_device_output(clean_output)
                if status == "Failed":
                    error_lines = [line for line in clean_output.splitlines() if "Error" in line or "error" in line or "This subnet" in line]
                    error_detail = ": " + " ".join(error_lines) if error_lines else ""
                    
                    executed_commands.append({
                        "command": command, 
                        "output": clean_output
                    })
                    raise Exception(f"命令执行失败{error_detail}")
                
                executed_commands.append({
                    "command": command, 
                    "output": clean_output
                })
                
                return clean_output
                
            except Exception as e:
                executed_commands.append({
                    "command": command, 
                    "output": cmd_output if 'cmd_output' in locals() else f"执行失败: {str(e)}"
                })
                raise
        
        # 接口映射和配置部分
        if conn_interface and conn_interface.strip():
            print(f"\n配置物理接口 {conn_interface}...")
            
            # 保存当前命令列表，避免接口查询命令混入配置日志
            original_commands = executed_commands.copy()
            
            # 获取设备上的所有接口并进行映射
            all_interfaces = interface_config.get_device_interfaces(net_connect)
            print(f"成功获取到接口列表，共{len(all_interfaces)}个接口")
            
            # 进行接口映射
            interfaces_to_map = [conn_interface]
            mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces_to_map, net_connect)
            
            # 恢复命令列表，删除接口查询相关命令
            executed_commands = original_commands.copy()
            
            if mapped_interfaces and mapped_interfaces[0]:
                original_interface = conn_interface
                conn_interface = mapped_interfaces[0]
                print(f"接口映射: {original_interface} -> {conn_interface}")
                
                # 检查接口类型（环回口或物理接口）
                is_loopback = interface_config.is_loopback_interface(conn_interface)
                print(f"接口 {conn_interface} {'是' if is_loopback else '不是'} 环回口")
                
                # 进入系统视图
                execute_command("system-view")
                
                # 进入接口配置模式
                execute_command(f"interface {conn_interface}")
                
                # 根据接口类型进行不同的配置
                if is_loopback:
                    # 为环回口配置IP地址
                    if local_ip:
                        execute_command(f"ip address {local_ip} 255.255.255.255")
                    else:
                        ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                            [conn_interface], 
                            hostip=hostip, 
                            ip_stack="IPv4"
                        )
                        if ip_addresses and masks:
                            print(f"为环回口生成IP地址: {ip_addresses[0]}/{masks[0]}")
                            execute_command(f"ip address {ip_addresses[0]} {masks[0]}")
                else:
                    # 处理物理接口
                    interface_mode = interface_config.check_interface_mode(net_connect, conn_interface)
                    print(f"检测到接口 {conn_interface} 为{interface_mode}模式")
                    
                    # 重新进入接口配置模式
                    execute_command(f"interface {conn_interface}")
                    
                    # 如果是桥接模式，先转为路由模式
                    if interface_mode == "bridge":
                        print(f"接口 {conn_interface} 是桥接模式，将转换为路由模式")
                        result = interface_config.switch_interface_to_route_mode(net_connect, conn_interface, executed_commands)
                        if result is False:
                            raise Exception(f"将接口 {conn_interface} 转换为路由模式失败")
                    
                    # 为物理接口配置IP
                    address_type = device_params.get('address_type', 'ipv4 unicast')
                    is_ipv6 = address_type == 'ipv6 unicast'
                    is_evpn = address_type == 'l2vpn evpn'
                    dual_stack = device_params.get('dual_stack', False)

                    if is_evpn or dual_stack:
                        # L2VPN EVPN场景同时配置IPv4和IPv6
                        # 配置IPv4地址
                        if local_ip:
                            execute_command(f"ip address {local_ip} 255.255.255.0")
                        else:
                            ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                                [conn_interface], 
                                hostip=hostip, 
                                ip_stack="IPv4"
                            )
                            if ip_addresses and masks:
                                print(f"为接口生成IPv4地址: {ip_addresses[0]}/{masks[0]}")
                                execute_command(f"ip address {ip_addresses[0]} {masks[0]}")
                        
                        # 配置IPv6地址
                        ipv6_local_ip = device_params.get('ipv6_local_ip')
                        if ipv6_local_ip:
                            execute_command(f"ipv6 address {ipv6_local_ip}/64")
                        else:
                            _, _, ipv6_addresses, ipv6_prefixes = interface_config.generate_ip_addresses(
                                [conn_interface], 
                                hostip=hostip, 
                                ip_stack="IPv6"
                            )
                            if ipv6_addresses and ipv6_prefixes:
                                print(f"为接口生成IPv6地址: {ipv6_addresses[0]}/{ipv6_prefixes[0]}")
                                execute_command(f"ipv6 address {ipv6_addresses[0]}/{ipv6_prefixes[0]}")


                    elif is_ipv6:
                        # 配置IPv6地址
                        if local_ip and ':' in local_ip:  # 检查是否为IPv6格式
                            execute_command(f"ipv6 address {local_ip}/64")
                        else:
                            # 生成IPv6地址
                            _, _, ipv6_addresses, ipv6_prefixes = interface_config.generate_ip_addresses(
                                [conn_interface], 
                                hostip=hostip, 
                                ip_stack="IPv6"
                            )
                            if ipv6_addresses and ipv6_prefixes:
                                print(f"为接口生成IPv6地址: {ipv6_addresses[0]}/{ipv6_prefixes[0]}")
                                execute_command(f"ipv6 address {ipv6_addresses[0]}/{ipv6_prefixes[0]}")
                    else:
                        # 配置IPv4地址
                        if local_ip:
                            execute_command(f"ip address {local_ip} 255.255.255.0")
                        else:
                            ip_addresses, masks, _, _ = interface_config.generate_ip_addresses(
                                [conn_interface], 
                                hostip=hostip, 
                                ip_stack="IPv4"
                            )
                            if ip_addresses and masks:
                                print(f"为接口生成IP地址: {ip_addresses[0]}/{masks[0]}")
                                execute_command(f"ip address {ip_addresses[0]} {masks[0]}")
                
                # 退出接口配置模式
                execute_command("quit")
            else:
                print(f"警告: 无法映射接口 '{conn_interface}'，将使用原始输入名称")
                execute_command("system-view")
                execute_command(f"interface {conn_interface}")
                execute_command("quit")
        else:
            # 仅进入系统视图
            execute_command("system-view")
            
        # 退出系统视图
        execute_command("quit")
        
        # 断开连接
        net_connect.disconnect()
        
        device_params['mapped_interface'] = conn_interface  # 保存映射后的接口名称
        return "succeed", executed_commands, system_info, ""
        
    except Exception as e:
        error_msg = f"物理接口配置出错: {str(e)}"
        
        if 'net_connect' in locals():
            try:
                net_connect.disconnect()
            except:
                pass
                
        return "Failed", executed_commands, system_info, error_msg

def configure_bgp(device_params):
    """仅配置BGP参数的函数"""
    executed_commands = []
    system_info = {}
    
    try:
        # 提取参数
        hostip = device_params.get('hostip')
        username = device_params.get('username')
        password = device_params.get('password')
        bgp_local_as = device_params.get('bgp_local_as', 100)
        peer_ip = device_params.get('peer_ip')
        bgp_peer_as = device_params.get('bgp_peer_as', 100)
        conn_interface = device_params.get('mapped_interface', device_params.get('conn_interface'))
        address_type = device_params.get('address_type')
        network_advertise = device_params.get('network_advertise')
        
        # 登录设备
        net_connect = login_args.login(hostip, username, password)
        
        if not net_connect:
            return "Failed", [], {}, "登录失败"
        
        # 获取设备名称
        net_connect.write_channel('\n')
        time.sleep(0.5)
        output = net_connect.read_channel()
        
        device_name = "unknown"
        if output:
            if '<' in output and '>' in output:
                try:
                    device_name = re.search(r'<([^>]+)>', output).group(1)
                except:
                    pass
            elif '[' in output and ']' in output:
                try:
                    device_name = re.search(r'\[([^\]]+)\]', output).group(1)
                except:
                    pass
        
        # 定义命令执行函数
        def execute_command(command, timeout=30):
            """执行配置命令并显示原始回显"""
            try:
                cmd_output = net_connect.send_command(
                    command,
                    expect_string=r'[>#\]\[]',
                    read_timeout=timeout,
                    strip_prompt=False,
                    strip_command=False
                )
                
                # 清理设备输出中的多余换行
                clean_output = cmd_output.rstrip()
                clean_output = re.sub(r'\r?\n\r?\n+', r'\r\n', clean_output)
                clean_output = re.sub(r'(\[[^\]]+\])\s*\r?\n', r'\1 ', clean_output)
                clean_output = re.sub(r'(<[^>]+>)\s*\r?\n', r'\1 ', clean_output)
                
                print(clean_output, end='')
                
                status = check_device_output.check_device_output(clean_output)
                if status == "Failed":
                    error_lines = [line for line in clean_output.splitlines() if "Error" in line or "error" in line or "This subnet" in line]
                    error_detail = ": " + " ".join(error_lines) if error_lines else ""
                    
                    executed_commands.append({
                        "command": command, 
                        "output": clean_output
                    })
                    raise Exception(f"命令执行失败{error_detail}")
                
                executed_commands.append({
                    "command": command, 
                    "output": clean_output
                })
                
                return clean_output
                
            except Exception as e:
                executed_commands.append({
                    "command": command, 
                    "output": cmd_output if 'cmd_output' in locals() else f"执行失败: {str(e)}"
                })
                raise
        
        # 进入系统视图
        execute_command("system-view")
        
        # 配置BGP
        bgp_cmd = f"bgp {bgp_local_as}"
        execute_command(bgp_cmd)

        # 检查是否为EVPN/双栈配置
        is_evpn = address_type == 'l2vpn evpn'
        dual_stack = device_params.get('dual_stack', False)
        
        # 配置IPv4对等体
        peer_cmd = f"peer {peer_ip} as-number {bgp_peer_as}"
        execute_command(peer_cmd)
        
        # 【新增】检查是否为EBGP（AS号不同），如果是则添加ebgp-max-hop命令
        if str(bgp_local_as) != str(bgp_peer_as):
            ebgp_hop_cmd = f"peer {peer_ip} ebgp-max-hop 255"
            execute_command(ebgp_hop_cmd)

        # 配置连接接口
        if conn_interface:
            conn_cmd = f"peer {peer_ip} connect-interface {conn_interface}"
            execute_command(conn_cmd)

        # 如果是EVPN或双栈，额外配置IPv6对等体
        if is_evpn or dual_stack:
            ipv6_peer_ip = device_params.get('ipv6_peer_ip')
            if ipv6_peer_ip:
                ipv6_peer_cmd = f"peer {ipv6_peer_ip} as-number {bgp_peer_as}"
                execute_command(ipv6_peer_cmd)
                
                if conn_interface:
                    ipv6_conn_cmd = f"peer {ipv6_peer_ip} connect-interface {conn_interface}"
                    execute_command(ipv6_conn_cmd)    
        
        # 进入地址族
        af_cmd = f"address-family {address_type}"
        execute_command(af_cmd)
        
        # 启用对等体
        enable_cmd = f"peer {peer_ip} enable"
        execute_command(enable_cmd)

        # 如果是EVPN或双栈，启用IPv6对等体
        if (is_evpn or dual_stack) and device_params.get('ipv6_peer_ip'):
            ipv6_enable_cmd = f"peer {device_params.get('ipv6_peer_ip')} enable"
            execute_command(ipv6_enable_cmd)
        
        # 网络宣告
        if network_advertise:
            network = network_advertise.get("network")
            prefix = network_advertise.get("prefix")
            if network and prefix:
                # 检查是IPv4还是IPv6地址格式
                if address_type == 'ipv6 unicast':
                    # 对于IPv6，确保使用正确的前缀长度格式
                    if not prefix.startswith('/'):
                        prefix_value = f"{prefix}"
                    else:
                        prefix_value = prefix.replace('/', '')
                    network_cmd = f"network {network} {prefix_value}"
                else:
                    # IPv4保持原样
                    network_cmd = f"network {network} {prefix}"
                
                execute_command(network_cmd)
        
        # 退出配置
        execute_command("quit")  # 退出地址族
        execute_command("quit")  # 退出BGP
        execute_command("quit")  # 退出系统视图
        
        net_connect.disconnect()
        
        return "succeed", executed_commands, system_info, ""
        
    except Exception as e:
        error_msg = f"BGP配置出错: {str(e)}"
        
        if 'net_connect' in locals():
            try:
                net_connect.disconnect()
            except:
                pass
                
        return "Failed", executed_commands, system_info, error_msg

def config_dual_devices(dual_params):
    """同时配置两台设备的BGP参数"""
    # 提取共同参数
    common_params = dual_params.get('common', {})
    bgp_local_as = common_params.get('bgp_local_as', '100')
    bgp_peer_as = common_params.get('bgp_peer_as', '100')
    address_type = common_params.get('address_type', 'ipv4 unicast')
    
    # 【新增】记录脚本启动状态为Running
    initial_commands = []  # 使用空列表，不影响后续命令记录
    write_log.write_log("Running", initial_commands, {}, file_suffix="dual_bgp_status")
    
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
        
        # 添加公共BGP参数
        if device_key == 'dut1':
            # 第一台设备使用配置中的local_as和peer_as
            device_params['bgp_local_as'] = bgp_local_as
            device_params['bgp_peer_as'] = bgp_peer_as
        else:
            # 第二台设备交换AS号码，本地AS使用peer_as，对等体AS使用local_as
            device_params['bgp_local_as'] = bgp_peer_as
            device_params['bgp_peer_as'] = bgp_local_as

        device_params['address_type'] = address_type
        
        # 为设备分配接口和对等体IP
        # 为设备分配接口和对等体IP，根据地址类型使用IPv4或IPv6地址
        if address_type == 'ipv6 unicast':
            # 只有纯IPv6单播地址族才使用IPv6地址
            if device_key == 'dut1':
                device_params['conn_interface'] = dut1_interface
                device_params['peer_ip'] = '2025:172:16:1::2'  # DUT1的BGP对等体是DUT2
                device_params['local_ip'] = '2025:172:16:1::1'  # 不包含前缀，在接口配置时添加
            else:
                device_params['conn_interface'] = dut2_interface
                device_params['peer_ip'] = '2025:172:16:1::1'  # DUT2的BGP对等体是DUT1
                device_params['local_ip'] = '2025:172:16:1::2'
        elif address_type == 'l2vpn evpn':
            # L2VPN EVPN需要同时配置IPv4和IPv6
            if device_key == 'dut1':
                device_params['conn_interface'] = dut1_interface
                device_params['peer_ip'] = '172.16.1.2'  # 主要BGP对等体使用IPv4
                device_params['local_ip'] = '172.16.1.1'
                device_params['ipv6_local_ip'] = '2025:172:16:1::1'  # 额外的IPv6地址
                device_params['ipv6_peer_ip'] = '2025:172:16:1::2'  # 额外的IPv6对等体
                device_params['dual_stack'] = True  # 标记为双栈配置
            else:
                device_params['conn_interface'] = dut2_interface
                device_params['peer_ip'] = '172.16.1.1'
                device_params['local_ip'] = '172.16.1.2'
                device_params['ipv6_local_ip'] = '2025:172:16:1::2'
                device_params['ipv6_peer_ip'] = '2025:172:16:1::1'
                device_params['dual_stack'] = True
        else:
            # IPv4单播、VPNv4和VPNv6都使用IPv4地址建立邻居
            if device_key == 'dut1':
                device_params['conn_interface'] = dut1_interface
                device_params['peer_ip'] = '172.16.1.2'  # DUT1的BGP对等体是DUT2
                device_params['local_ip'] = '172.16.1.1'
            else:
                device_params['conn_interface'] = dut2_interface
                device_params['peer_ip'] = '172.16.1.1'  # DUT2的BGP对等体是DUT1
                device_params['local_ip'] = '172.16.1.2'
        
        # 添加网络宣告参数
        if address_type == 'ipv4 unicast':
            # 仅IPv4单播配置才添加网络宣告
            if device_key == 'dut1':
                device_params['network_advertise'] = {
                    'network': '11.11.11.11',
                    'prefix': '32'
                }
            else:
                device_params['network_advertise'] = {
                    'network': '22.22.22.22', 
                    'prefix': '32'
                }
        elif address_type == 'ipv6 unicast':
            # 仅IPv6单播配置才添加网络宣告
            if device_key == 'dut1':
                device_params['network_advertise'] = {
                    'network': '2025:11:11:11::11',
                    'prefix': '128'
                }
            else:
                device_params['network_advertise'] = {
                    'network': '2025:22:22:22::22', 
                    'prefix': '128'
                }
        else:
            # VPNv4和VPNv6不需要network命令通告网段
            device_params['network_advertise'] = None
        
        devices.append(device_params)
    
    # 保存两台设备的执行命令和系统信息
    all_executed_commands = {}
    all_system_info = {}
    final_status = "succeed"
    error_messages = []
    bgp_peer_status = None  # 初始化为None，表示未检查
    ping_connectivity = None  # 关键修复：确保变量总是被初始化
    
    # 依次配置每台设备
    for i, device_params in enumerate(devices):
        device_id = i + 1
        temp_id = ['dut1', 'dut2'][i]
        print(f"\n开始配置设备 {temp_id}...")
        
        try:
            # 1. 首先配置物理接口
            status, interface_commands, interface_system_info, error_message = configure_physical_interface(device_params)
            
            # 保存设备名和系统信息
            device_name = device_params.get('device_name', f"device{device_id}")
            
            # 保存命令和系统信息
            if interface_commands:
                all_executed_commands[device_name] = interface_commands
            if interface_system_info:
                all_system_info[device_name] = interface_system_info
            
            # 如果物理接口配置失败，立即中断
            if status == "Failed":
                final_status = "Failed"
                error_messages.append(f"{device_name}: {error_message}")
                break
                
            # 2. 然后配置环回口接口           
            # 重新建立SSH连接以配置环回口
            net_connect = login_args.login(device_params['hostip'], device_params['username'], device_params['password'])
            if not net_connect:
                print(f"无法连接到设备 {device_name} 配置环回口")
                continue
                
            # 定义本地执行命令函数
            loopback_commands = []
            def execute_loopback_command(command):
                output = net_connect.send_command(
                    command,
                    expect_string=r'[>#\]\[]',
                    strip_prompt=False,
                    strip_command=False
                )
                # 清理输出中的多余换行
                clean_output = output.rstrip()
                clean_output = re.sub(r'\r?\n\r?\n+', r'\r\n', clean_output)
                clean_output = re.sub(r'(\[[^\]]+\])\s*\r?\n', r'\1 ', clean_output)
                clean_output = re.sub(r'(<[^>]+>)\s*\r?\n', r'\1 ', clean_output)
                
                print(clean_output, end='')
                loopback_commands.append({"command": command, "output": clean_output})
                return clean_output
            
            # 进入系统视图
            execute_loopback_command("system-view")
            
            # 创建环回口LoopBack9
            loopback_interface = "LoopBack9"
            execute_loopback_command(f"interface {loopback_interface}")
            
            # 根据address_type确定需要配置的地址类型
            has_ipv4 = address_type in ['ipv4 unicast', 'vpnv4', 'l2vpn evpn']
            has_ipv6 = address_type in ['ipv6 unicast', 'vpnv6', 'l2vpn evpn']
            
            # 根据设备索引设置不同IP
            if i == 0:  # 第一台设备
                if has_ipv4:
                    execute_loopback_command("ip address 11.11.11.11 255.255.255.255")
                if has_ipv6:
                    execute_loopback_command("ipv6 address 2025:11:11:11::11/128")
            else:  # 第二台设备
                if has_ipv4:
                    execute_loopback_command("ip address 22.22.22.22 255.255.255.255")
                if has_ipv6:
                    execute_loopback_command("ipv6 address 2025:22:22:22::22/128")
            
            # 退出接口和配置模式
            execute_loopback_command("quit")
            execute_loopback_command("quit")
            
            # 断开连接
            net_connect.disconnect()
            
            # 将环回口命令添加到现有命令列表
            if device_name in all_executed_commands:
                all_executed_commands[device_name].extend(loopback_commands)
            else:
                all_executed_commands[device_name] = loopback_commands
            
            # 3. 最后配置BGP
            status, bgp_commands, bgp_system_info, error_message = configure_bgp(device_params)
            
            # 将BGP命令添加到现有命令列表
            if device_name in all_executed_commands:
                all_executed_commands[device_name].extend(bgp_commands)
            else:
                all_executed_commands[device_name] = bgp_commands
            
            # 如果BGP配置失败，立即中断
            if status == "Failed":
                final_status = "Failed"
                error_messages.append(f"{device_name}: {error_message}")
                break
            
            print(f"\n设备 {device_name} 配置完成")
            
        except Exception as e:
            device_name = device_params.get('device_name', f"device{device_id}")
            error_msg = f"{device_name} 配置失败: {str(e)}"
            print(error_msg)
            final_status = "Failed"
            error_messages.append(error_msg)
            break
    
    # 【关键修复】只有当两台设备都配置成功时，才检查BGP邻居状态
    if final_status == "succeed" and len(all_executed_commands) == 2:
        print("\n两台设备均配置成功，开始检查BGP邻居状态...")
        ssh_conn = None
        try:
            # 重新建立SSH连接以检查BGP邻居状态
            ssh_conn = login_args.login(devices[1]['hostip'], devices[1]['username'], devices[1]['password'])
            if ssh_conn:
                is_up, status = monitor_bgp_neighbor_status(
                    ssh_conn, devices[1].get('device_name', 'device2'), 
                    address_type,  # 使用当前地址族类型
                    timeout_minutes=1, check_interval=5
                )
                
                # 记录BGP邻居状态
                bgp_peer_status = status
                
                print(f"BGP邻居状态检查结果: {bgp_peer_status}")
                
                # 如果BGP状态是Established，执行ping测试
                if status == "Established":
                    # 对于VPNv4和VPNv6地址族，跳过PING测试
                    if address_type in ['vpnv4', 'vpnv6', 'l2vpn evpn']:
                        print(f"\nBGP邻居状态已建立，{address_type}地址族不执行Ping测试")
                        ping_connectivity = None
                    else:
                        print("\nBGP邻居状态已建立，执行Ping测试...")
                        
                        # 初始化PING测试结果字典
                        ping_results = {}
                        
                        # 根据地址族类型决定ping命令
                        has_ipv4 = address_type == 'ipv4 unicast'
                        has_ipv6 = address_type == 'ipv6 unicast'
                        
                        # IPv4 PING测试
                        if has_ipv4:
                            print("执行IPv4 PING测试: 从22.22.22.22 PING 11.11.11.11")
                            try:
                                # 清除缓冲区
                                ssh_conn.clear_buffer()
                                
                                # 使用 -c 5 参数确保执行5次PING
                                ping_cmd = "ping -a 22.22.22.22 11.11.11.11\n"
                                
                                # 直接发送命令到通道
                                ssh_conn.write_channel(ping_cmd)
                                
                                # 等待足够时间完成所有5次PING (每次约1秒)
                                time.sleep(5)
                                
                                # 读取通道中的所有输出
                                ping_output = ssh_conn.read_channel()
                                
                                print(f"IPv4 PING结果:\n{ping_output}")
                                
                                # 完全按照ISIS模块的判断逻辑
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

                        # IPv6 PING测试
                        if has_ipv6:
                            # 等待3秒再测试IPv6
                            if has_ipv4:
                                print("\nIPv4 PING测试完成，等待3秒后进行IPv6 PING测试...")
                                time.sleep(3)
                                
                            print("执行IPv6 PING测试: 从2025:22:22:22::22 PING 2025:11:11:11::11")
                            try:
                                # 清除缓冲区
                                ssh_conn.clear_buffer()
                                
                                # 使用 -c 5 参数确保执行5次PING
                                ping_cmd = "ping ipv6 -a 2025:22:22:22::22 2025:11:11:11::11\n"
                                
                                # 直接发送命令到通道
                                ssh_conn.write_channel(ping_cmd)
                                
                                # 等待足够时间完成所有5次PING
                                time.sleep(5)  # IPv6可能需要更长时间
                                
                                # 读取通道中的所有输出
                                ping_output = ssh_conn.read_channel()
                                
                                print(f"IPv6 PING结果:\n{ping_output}")
                                
                                # 完全按照ISIS模块的判断逻辑
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
                        
                        # 生成PING连通性结果字典
                        ping_connectivity = {}
                        if "ipv4_ping" in ping_results:
                            ping_connectivity["IPv4_PING_Status"] = ping_results["ipv4_ping"]
                        if "ipv6_ping" in ping_results:
                            ping_connectivity["IPv6_PING_Status"] = ping_results["ipv6_ping"]

                        # 只有当ping_connectivity不为空时才记录
                        print(f"\nPING测试结果汇总: {ping_connectivity}" if ping_connectivity else "\n未执行PING测试")
                else:
                    ping_connectivity = None  # 不包含任何PING测试结果
                    print("\nBGP邻居未建立，跳过PING连通性测试")
                
                # 断开连接
                if ssh_conn:
                    ssh_conn.disconnect()
            else:
                print("无法建立SSH连接进行BGP邻居状态检查")
                
        except Exception as e:
            print(f"检查BGP邻居状态时出错: {str(e)}")
            if ssh_conn:
                try:
                    ssh_conn.disconnect()
                except:
                    pass
    
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
    
    # 记录日志 - 修改为包含ping_result
    log_path = write_log.write_log(
        "Completed" if final_status == "succeed" else final_status, 
        result_format,  # 包含所有命令输出
        all_system_info,  # 包含所有系统信息
        "\n".join(error_messages) if error_messages else None,
        file_suffix="dual_bgp_status",
        bgp_peer_status=bgp_peer_status if final_status == "succeed" else None,  # 只有成功时才记录状态
        ping_connectivity=ping_connectivity if ping_connectivity and len(ping_connectivity) > 0 else None
    )

    print(f"\n双设备BGP配置完成，状态: {final_status}")
    if bgp_peer_status and final_status == "succeed":
        print(f"BGP邻居状态: {bgp_peer_status}")
    if error_messages:
        print(f"错误信息: {'; '.join(error_messages)}")

    if log_path:
        print(f"日志已保存至: {log_path}")

    # 如果有错误，最后才退出
    if final_status == "Failed":
        sys.exit(1)

    return final_status, all_executed_commands, all_system_info

def monitor_bgp_neighbor_status(ssh_connection, device_name, address_type, timeout_minutes=1, check_interval=5):
    """监控BGP邻居状态，直到达到Established状态或超时"""
    print(f"\n开始监控设备 {device_name} 的BGP邻居状态...")
    print(f"将等待最多 {timeout_minutes} 分钟，检查间隔 {check_interval} 秒")
    
    # 定义标准BGP状态值（不区分大小写）
    bgp_states = ['established', 'connect', 'active', 'idle', 'opensent', 'openconfirm', 'Idle(Admin)']
    
    # 根据地址族类型选择对应的命令
    if address_type == "ipv4 unicast":
        command = "display bgp peer ipv4 unicast"
    elif address_type == "ipv6 unicast":
        command = "display bgp peer ipv6 unicast"
    elif address_type == "l2vpn evpn":
        command = "display bgp peer l2vpn evpn"
    elif address_type == "vpnv4":
        command = "display bgp peer vpnv4"
    elif address_type == "vpnv6":
        command = "display bgp peer vpnv6"
    else:
        print(f"不支持的地址族类型: {address_type}")
        return False, "不支持的地址族类型"
    
    start_time = time.time()
    end_time = start_time + (timeout_minutes * 60)

    # 定义更强大的状态提取函数
    def extract_bgp_state(output):
        """提取BGP邻居状态"""
        
        # 第一优先级：匹配表格中的实际状态
        # 对于IPv6地址，需要特殊处理，因为IPv6地址包含冒号
        ipv6_table_pattern = r'([\da-fA-F:]+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+:\d+:\d+\s+(\S+)(?:\s*$|\s*\r?$)'
        ipv6_match = re.search(ipv6_table_pattern, output)
        if ipv6_match:
            print(f"从IPv6表格中提取到BGP状态: {ipv6_match.group(2)} (对等体: {ipv6_match.group(1)})")
            return ipv6_match.group(2)
        
        # IPv4模式保持不变，作为备份
        ipv4_table_pattern = r'\d+\.\d+\.\d+\.\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+:\d+:\d+\s+(\S+)(?:\s*$|\s*\r?$)'
        ipv4_match = re.search(ipv4_table_pattern, output)
        if ipv4_match:
            print(f"从IPv4表格中提取到BGP状态: {ipv4_match.group(1)}")
            return ipv4_match.group(1)
        
        # 第二优先级：更精确地匹配State字段，避开"Peers in established state"
        # 不要使用"State"作为搜索词，它太通用，使用更具体的模式
        # 确保匹配行不包含"peers in"以避开"Peers in established state: 0"
        for line in output.split('\n'):
            # 跳过包含"peers in"的行
            if "peers in" in line.lower():
                continue
                
            # 找出具体的BGP对等体状态行
            if "state" in line.lower() and ":" in line:
                # 尝试提取冒号后面的状态值
                state_match = re.search(r'state\s*:\s*([a-zA-Z0-9()_]+)', line, re.IGNORECASE)
                if state_match:
                    return state_match.group(1)
        
        # 第三优先级：在表格数据行中查找标准BGP状态
        bgp_states = ['established', 'connect', 'active', 'idle', 'opensent', 'openconfirm']
        for line in output.split('\n'):
            # 跳过包含"peers in"的行
            if "peers in" in line.lower():
                continue
                
            # 检查行中是否有BGP对等体IP和状态
            has_ip = bool(re.search(r'[\da-fA-F.:]+', line))  # 匹配IPv4或IPv6地址
            if has_ip:
                for state in bgp_states:
                    if re.search(r'\b' + re.escape(state) + r'\b', line.lower()):
                        return state.capitalize()
        
        return "Unknown"  # 如果所有方法都失败，返回Unknown
    
    while time.time() < end_time:
        try:
            print(f"\n执行命令: {command}")
            # 修改send_command调用，确保显示完整输出
            output = ssh_connection.send_command(
                command,
                expect_string=r'[>#\]\[]',  # 等待匹配提示符
                delay_factor=2,  # 增加延迟因子
                strip_prompt=False,  # 不删除提示符
                strip_command=False  # 不删除命令本身
            )
            # 打印完整输出，确保可见
            print("\n命令输出结果:")
            print("-" * 40)
            print(output)
            print("-" * 40)
            
            # 【关键修复】先提取状态，再判断是否为Established
            current_status = extract_bgp_state(output)
            
            print(f"\n提取到的BGP状态为: {current_status}")

            # 修改状态判断逻辑，使用严格的相等比较
            if current_status.lower() == "established":
                print("\n找到Established状态的BGP邻居")
                return True, "Established"
            else:
                print(f"当前邻居状态: {current_status}，继续等待...")
                # 添加额外判断，对于Idle(Admin)状态提供更清晰的信息
                if "idle" in current_status.lower() and "admin" in current_status.lower():
                    print("检测到Idle(Admin)状态，可能需要手动启用BGP对等体")
                
            time.sleep(check_interval)
        except Exception as e:
            print(f"检查BGP邻居状态时出错: {str(e)}")
            time.sleep(check_interval)
    
    # 超时处理部分需要同样的修改
    try:
        print("\n监控超时，最后检查一次状态...")
        final_output = ssh_connection.send_command(
            command,
            expect_string=r'[>#\]\[]',
            delay_factor=2,
            strip_prompt=False,
            strip_command=False
        )
        print("\n最后命令输出:")
        print("-" * 40)
        print(final_output)
        print("-" * 40)
        final_status = extract_bgp_state(final_output)
    except Exception as e:
        final_status = f"Error: {str(e)}"
    
    print(f"\n监控超时: 在{timeout_minutes}分钟内未发现Established状态的BGP邻居")
    print(f"最终BGP状态: {final_status}")
    return False, final_status

# 修改main函数以支持双设备配置
if __name__ == '__main__':

    if len(sys.argv) != 2:
        print("使用方法:")
        print('单设备配置:')
        print('python BGP_CONFIG_TEST.py {"hostip":"设备IP地址","username":"用户名","password":"密码",'
              '"bgp_local_as":"100","peer_ip":"10.0.0.2","bgp_peer_as":"200",'
              '"conn_interface":"LoopBack0","address_type":"ipv4 unicast",'
              '"network":"192.168.0.0","prefix":"24"}')
        print('\n双设备配置:')
        print('python BGP_CONFIG_TEST.py {"hostip":"192.168.56.10,192.168.56.11","username":"admin","password":"h3c.com123",'
              '"bgp_local_as":"100","bgp_peer_as":"100","address_type":"ipv4 unicast",'
              '"dut1_interface":"GigabitEthernet1/0/1","dut2_interface":"GigabitEthernet1/0/1"}')
        sys.exit(1)

    try:
        # 处理输入参数
        json_str = sys.argv[1]
        
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
        
        try:
            params = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {str(e)}")
            sys.exit(1)
        
        try:
            # 检查是否为双设备配置
            if "hostip" in params and "," in params["hostip"]:
                # 双设备配置逻辑
                hostips = [ip.strip() for ip in params["hostip"].split(",")]
                
                if len(hostips) != 2:
                    print("错误: 双设备配置需要提供两个IP地址，用逗号分隔")
                    sys.exit(1)
                
                # 构建双设备参数
                dual_params = {
                    "common": {
                        "bgp_local_as": params.get("bgp_local_as", "100"),
                        "bgp_peer_as": params.get("bgp_peer_as", "100"),
                        "address_type": params.get("address_type", "ipv4 unicast")
                    },
                    "interfaces": {
                        "dut1_interface": params.get("dut1_interface", ""),
                        "dut2_interface": params.get("dut2_interface", "")
                    },
                    "dut1": {
                        "hostip": hostips[0],
                        "username": params.get("username", "admin"),
                        "password": params.get("password", "")
                    },
                    "dut2": {
                        "hostip": hostips[1],
                        "username": params.get("username", "admin"),
                        "password": params.get("password", "")
                    }
                }
                
                # 执行双设备配置
                config_dual_devices(dual_params)
                
            else:
                # 单设备配置逻辑
                # 提取必需参数
                hostip = params.get('hostip')
                username = params.get('username')
                password = params.get('password')
                peer_ip = params.get('peer_ip')
                address_type = params.get('address_type')
                
                # 验证必需参数
                required_params = ['hostip', 'username', 'password', 'peer_ip', 'address_type', 'conn_interface']
                missing_params = [param for param in required_params if param not in params]
                
                if missing_params:
                    print(f"缺少必需参数: {', '.join(missing_params)}")
                    sys.exit(1)
                
                # 提取可选参数
                bgp_local_as = int(params.get('bgp_local_as', 100))
                bgp_peer_as = int(params.get('bgp_peer_as', 100))
                
                # 从配置中提取conn_interface值
                conn_interface = params.get('conn_interface')
                # 判断值是否为None、"null"或空字符串
                if conn_interface is None or conn_interface.lower() == "null" or conn_interface.strip() == "":
                    conn_interface = None  # 设置为None，表示不下发命令
                
                # 处理network_advertise参数
                network_advertise = None
                if 'network' in params and 'prefix' in params:
                    network = params.get('network')
                    prefix = params.get('prefix')
                    
                    # 检查network和prefix参数是否为None、"null"或空值
                    is_network_valid = network and network.lower() != "null" and network.strip() != ""
                    is_prefix_valid = prefix and prefix.lower() != "null" and prefix.strip() != ""
                    
                    # 只有当两个参数都有效时才创建network_advertise字典
                    if is_network_valid and is_prefix_valid:
                        network_advertise = {
                            'network': network,
                            'prefix': prefix
                        }
                        print(f"将通告网络: {network}/{prefix}")
                    else:
                        print("网络通告参数无效或未提供，将跳过network命令")
                
                # 调用配置函数
                bgp_config(hostip, username, password, bgp_local_as, peer_ip, bgp_peer_as, conn_interface, address_type, network_advertise)
                
        except Exception as e:
            print(f"配置过程中出错: {str(e)}")
            sys.exit(1)
            
    except Exception as e:
        print(f"参数处理错误: {str(e)}")
        sys.exit(1)