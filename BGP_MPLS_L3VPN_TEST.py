import sys
import json
import re
import time
import os
import netmiko
from netmiko import ConnectHandler
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)
    
import login_args
import write_log
import check_device_output
import get_system_info
import interface_config

def clean_output(output):
    """清理设备输出中的多余换行和格式问题"""
    # 移除末尾的空白字符和换行符
    output = output.rstrip()
    
    # 处理设备提示符与命令之间的多余换行
    output = re.sub(r'(<[A-Za-z0-9\-_]+>)\r?\n', r'\1', output)
    output = re.sub(r'(\[[A-Za-z0-9\-_]+\])\r?\n', r'\1', output)
    
    return output

def find_device_prompt(net_connect, timeout=5):
    """更健壯的提示符检测方法"""
    try:
        # 清空缓冲区
        net_connect.clear_buffer()
        
        # 发送换行，应该会返回当前提示符
        net_connect.write_channel("\n")
        
        # 等待提示符
        start_time = time.time()
        output = ""
        
        while (time.time() - start_time) < timeout:
            time.sleep(0.5)
            output += net_connect.read_channel()
            
            # 检查是否包含常见的提示符模式
            if re.search(r'<[^>]+>$', output) or re.search(r'\[[^\]]+\]$', output):
                # 提取并返回提示符
                lines = output.splitlines()
                for line in reversed(lines):
                    if re.search(r'<[^>]+>$', line) or re.search(r'\[[^\]]+\]$', line):
                        return line.strip()
        
        # 超时，返回可能的提示符或空字符串
        return output.strip()
    except Exception as e:
        print(f"获取提示符时出错: {str(e)}")
        return ""

def generate_config(device_info):
    """生成设备配置命令"""
    role = device_info["role"]
    interfaces = device_info["interfaces"]
    
    if role == "PE1":
        config = f"""
            system-view
            sysname PE1

            isis 100
             network-entity 86.0000.0001.0001.0001.00
             is-level level-2
             cost-style wide
             quit 

            ip vpn-instance vpn1
             route-distinguisher 100:100
             vpn-target 111:111 both
            
            mpls lsr-id 1.1.1.1
            mpls ldp
             quit


            interface loopback 1
             ip address 1.1.1.1 32
             isis enable 100
             quit

            interface {interfaces['PE1_to_P']}
             ip address 10.1.1.1 24
             isis enable 100
             mpls enable
             mpls ldp enable
             quit

            interface {interfaces['PE1_to_CE1']}
             ip binding vpn-instance vpn1
             ip address 172.16.1.1 24
             ipv6 address 2025:1::1 64
             quit

            bgp 100
            peer 3.3.3.3 as-number 100
            peer 3.3.3.3 connect-interface loopback 1
            address-family vpnv4
             peer 3.3.3.3 enable
            address-family vpnv6
             peer 3.3.3.3 enable
            ip vpn-instance vpn1
             peer 172.16.1.2 as 64500
             peer 2025:1::2 as 64500
              address-family ipv4 unicast
               peer 172.16.1.2 enable
               import-route direct
              address-family ipv6 unicast
               peer 2025:1::2 enable
               import-route direct
        """
    elif role == "PE2":
        config = f"""
            system-view
            sysname PE2

            isis 100
             network-entity 86.0000.0003.0003.0003.00
             is-level level-2
             cost-style wide
             quit 

            ip vpn-instance vpn1
             route-distinguisher 200:200
             vpn-target 111:111 both
            
            mpls lsr-id 3.3.3.3
            mpls ldp
             quit


            interface loopback 1
             ip address 3.3.3.3 32
             isis enable 100
             quit

            interface {interfaces['PE2_to_P']}
             ip address 20.1.1.1 24
             isis enable 100
             mpls enable
             mpls ldp enable
             quit

            interface {interfaces['PE2_to_CE2']}
             ip binding vpn-instance vpn1
             ip address 172.16.2.1 24
             ipv6 address 2025:2::1 64
             quit

            bgp 100
             peer 1.1.1.1 as-number 100
             peer 1.1.1.1 connect-interface loopback 1
             address-family vpnv4
              peer 1.1.1.1 enable
             address-family vpnv6
              peer 1.1.1.1 enable
             ip vpn-instance vpn1
              peer 172.16.2.2 as 64510
              peer 2025:2::2 as 64510
               address-family ipv4 unicast
                peer 172.16.2.2 enable
                import-route direct
               address-family ipv6 unicast
                peer 2025:2::2 enable
                import-route direct
        """
    elif role == "P":
        config = f"""
            system-view
            sysname P

            isis 100
             network-entity 86.0000.0002.0002.0002.00
             is-level level-2
             cost-style wide
             quit


            mpls lsr-id 2.2.2.2
            mpls ldp
             quit


            interface loopback 1
             ip address 2.2.2.2 32
             isis enable 100
             quit

            interface {interfaces['P_to_PE1']}
             ip address 10.1.1.2 24
             isis enable 100
             mpls enable
             mpls ldp enable
             quit

            interface {interfaces['P_to_PE2']}
             ip address 20.1.1.2 24
             isis enable 100
             mpls enable
             mpls ldp enable
             quit
        """

    else:
        raise ValueError(f"无效的角色: {role}。角色必须是: PE1, PE2, P中的一个。")

    return config

# 修改函数定义，添加log_command参数（默认为True）
def execute_command(net_connect, command, executed_commands=None, system_info=None, current_prompt=None, device_name=None, log_command=True):
    """执行命令并处理输出"""
    if executed_commands is None:
        executed_commands = []
    
    # 如果没有提供当前提示符，获取当前提示符
    if current_prompt is None:
        try:
            current_prompt = net_connect.find_prompt()
        except:
            net_connect.write_channel('\n')
            time.sleep(0.5)
            current_prompt = net_connect.read_until_pattern(r"[>\]]$").strip()
    
    # 打印当前提示符和命令
    print(f"{current_prompt}{command}")
    
    # 执行命令
    cmd_output = net_connect.send_command(
        command,
        expect_string=r"[>\]]",  # 简化模式匹配
        delay_factor=2,  # 增加延迟因子，给设备更多响应时间
        strip_prompt=False,
        strip_command=True
    )
    
    # 清理输出
    cmd_output = clean_output(cmd_output)
    
    # 分离实际输出和新提示符
    lines = cmd_output.splitlines()
    new_prompt = ""
    
    # 如果输出有内容，尝试提取新提示符
    if lines:
        last_line = lines[-1]
        # 更健壮的提示符检测模式，能够处理系统视图和接口视图
        match = re.search(r'(\[[\w\-]+(?:\-[\w\/]+)?\])$', last_line)
        if match:
            new_prompt = match.group(0)  # 提取完整的匹配项
            # 从输出中移除新提示符
            cmd_output = cmd_output[:cmd_output.rfind(new_prompt)]
    
    # 打印命令的实际输出部分(不包含提示符)
    if cmd_output.strip():
        print(cmd_output.strip())
    
    # 使用简单的文本格式记录命令和输出 - 修复版
    log_output = f"{current_prompt}{command}\n{cmd_output.strip()}"
    
    # 仅在log_command为True时将命令添加到执行记录
    if log_command:
        executed_commands.append(log_output)
    
    # 检查命令是否执行成功
    status = check_device_output.check_device_output(cmd_output + (new_prompt if new_prompt else ""))
    if status == "Failed":
        # 添加设备名称到错误信息中
        error_message = f"执行命令 '{command}' 失败，设备返回了错误信息"

            # 如果没有提供设备名，使用命令作为标识
        if not device_name:
            device_name = "Unknown_Device"
        
        # 抛出异常，将设备错误信息作为异常的一部分
        raise Exception(error_message, device_name)  # 修改这里，直接传递格式化的错误信息
    
    # 返回命令输出和从输出中提取的新提示符(如果有)
    return cmd_output, (new_prompt if new_prompt else current_prompt)

# 修改视图检查逻辑，更准确地判断当前视图
def check_current_view(prompt):
    """判断当前所处的视图"""
    if '<' in prompt and '>' in prompt:
        return "user_view"  # 用户视图 <设备名>
    elif '[' in prompt and ']' in prompt:
        # 使用更精确的模式识别接口视图 - 检查接口类型标识
        interface_patterns = [
            "GigabitEthernet", "Ten-GigabitEthernet", "Twenty-FiveGigE", "HGE", "HundredGigE", "FortyGigE", "WGE",
            "Vlan", "LoopBack", "Serial", "BAGG", "Bridge-Aggregation", "RAGG", "Route-Aggregation"
        ]
        # 检查是否为接口视图的典型模式: [设备名-接口类型]
        if any(intf_type in prompt for intf_type in interface_patterns):
            return "interface_view"  # 接口视图 [设备名-接口名]
        else:
            return "system_view"  # 系统视图 [设备名]
    return "unknown"

def monitor_bgp_neighbor_status(net_connect, device_name, address_type, timeout_minutes=1, check_interval=5):
    """监控BGP邻居状态，直到达到Established状态或超时"""
    print(f"\n开始监控设备 {device_name} 的BGP邻居状态 ({address_type})...")
    print(f"将等待最多 {timeout_minutes} 分钟，检查间隔 {check_interval} 秒")
    
    # 根据地址族类型选择对应的命令
    command = f"display bgp peer {address_type}"
    
    start_time = time.time()
    end_time = start_time + (timeout_minutes * 60)
    
    # 定义状态提取函数
    def extract_bgp_state(output):
        # 第一优先级：匹配表格中的实际状态
        ipv4_table_pattern = r'(\d+\.\d+\.\d+\.\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+:\d+:\d+\s+(\S+)'
        ipv4_match = re.search(ipv4_table_pattern, output)
        if ipv4_match:
            print(f"从表格中提取到BGP状态: {ipv4_match.group(2)} (对等体: {ipv4_match.group(1)})")
            return ipv4_match.group(2)
        
        # 备用策略：查找标准BGP状态词
        for line in output.split('\n'):
            # 跳过包含"peers in"的行
            if "peers in" in line.lower():
                continue
            
            # 查找标准BGP状态词
            bgp_states = ['established', 'connect', 'active', 'idle', 'opensent', 'openconfirm']
            for state in bgp_states:
                # 使用更精确的匹配模式
                if re.search(r'\b' + state + r'\b', line.lower()):
                    print(f"从输出行中找到BGP状态: {state.capitalize()}")
                    return state.capitalize()
        
        return "Unknown"  # 如果所有方法都失败，返回Unknown
    
    while time.time() < end_time:
        try:
            print(f"\n执行命令: {command}")
            output = net_connect.send_command(
                command,
                expect_string=r'[>#\]\[]', 
                delay_factor=2,
                strip_prompt=False,
                strip_command=False
            )
            print("\n命令输出结果:")
            print("-" * 40)
            print(output)
            print("-" * 40)
            
            # 提取状态，再判断是否为Established
            current_status = extract_bgp_state(output)
            
            print(f"\n提取到的BGP状态为: {current_status}")
            
            if current_status.lower() == "established":
                print("\n找到Established状态的BGP邻居")
                return True, "Established"
            else:
                print(f"当前邻居状态: {current_status}，继续等待...")
                
            time.sleep(check_interval)
        except Exception as e:
            print(f"检查BGP邻居状态时出错: {str(e)}")
            time.sleep(check_interval)
    
    # 超时处理部分
    try:
        print("\n监控超时，最后检查一次状态...")
        final_output = net_connect.send_command(
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

def main():
    try:
        # 添加全局结果字典，用于存储BGP状态等信息
        global result
        result = {"error_message": {}}

        # 检查是否提供了命令行参数
        if len(sys.argv) != 2:
            print("使用方法:")
            print(f'python {sys.argv[0]} ' + '\'{"role":"PE1,P,CE1","hostip":"192.168.1.1,192.168.1.2,192.168.1.3","username":"admin","password":"password","interfaces":{"PE1_to_P":"GigabitEthernet1/0/1","PE1_to_CE1":"GigabitEthernet1/0/2","P_to_PE1":"GigabitEthernet1/0/1","P_to_PE2":"GigabitEthernet1/0/2","CE1_to_PE1":"GigabitEthernet1/0/1"}}\'')
            print("\n参数说明:")
            print('role: 设备角色，多个设备用逗号分隔 (可用角色: PE1, PE2, P, CE1, CE2)')
            print('hostip: 设备IP地址，多个设备用逗号分隔，顺序与角色对应')
            print('username: 登录用户名，单值将应用于所有设备')
            print('password: 登录密码，单值将应用于所有设备')
            print('接口标识符: 直接在主对象中列出接口映射，如"PE1_to_P": "GigabitEthernet1/0/1"')
            print("\n配置示例 (可以只提供需要配置的设备):")
            print('{"role":"PE1,P","hostip":"192.168.1.1,192.168.1.2","username":"admin","password":"password","PE1_to_P":"GigabitEthernet1/0/1","PE1_to_CE1":"GigabitEthernet1/0/2","P_to_PE1":"GigabitEthernet1/0/1","P_to_PE2":"GigabitEthernet1/0/2"}')
            sys.exit(1)

        # 解析JSON参数
        try:
            json_str = sys.argv[1]
            if json_str.startswith("'") and json_str.endswith("'"):
                json_str = json_str[1:-1]
            config = json.loads(json_str)
            
            # 解析基本参数
            roles = config.get('role', '').split(',')
            hostips = config.get('hostip', '').split(',')
            usernames = config.get('username', '').split(',')
            passwords = config.get('password', '').split(',')

            # 提取接口信息(从主对象中)
            interfaces = {}
            for key, value in config.items():
                # 如果是接口标识符(包含"_to_"的键)，则添加到接口字典
                if '_to_' in key:
                    interfaces[key] = value
            
            # 验证基本参数
            if not roles or not roles[0]:
                print("错误: 必须提供至少一个设备角色")
                sys.exit(1)
                
            if len(roles) != len(hostips):
                print(f"错误: 角色数量({len(roles)})与IP地址数量({len(hostips)})不匹配")
                sys.exit(1)
                
            # 处理单值用户名和密码
            if len(usernames) == 1:
                usernames = usernames * len(roles)
            elif len(usernames) != len(roles):
                print(f"错误: 用户名数量({len(usernames)})与角色数量({len(roles)})不匹配")
                sys.exit(1)
                
            if len(passwords) == 1:
                passwords = passwords * len(roles)
            elif len(passwords) != len(roles):
                print(f"错误: 密码数量({len(passwords)})与角色数量({len(roles)})不匹配")
                sys.exit(1)
            
            # 将参数组织成设备列表
            devices = []
            for i in range(len(roles)):  # 修复: 使用range()生成可迭代的序列
                if not roles[i].strip():
                    continue
                
                device_info = {
                    "role": roles[i].strip(),
                    "hostip": hostips[i].strip(),
                    "username": usernames[i].strip(),
                    "password": passwords[i].strip(),
                    "interfaces": interfaces.copy()
                }
                devices.append(device_info)
                
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {str(e)}")
            sys.exit(1)
        except Exception as e:
            print(f"参数错误: {str(e)}")
            sys.exit(1)

        # 显示将要配置的设备角色
        roles_to_config = [device.get("role") for device in devices]
        print(f"\n将配置以下角色的设备: {', '.join(roles_to_config)}")

        # 在脚本开始时记录Running状态
        write_log.write_log("Running", [], {})

        # 配置每个设备
        all_commands = {}  # 用于存储所有设备的命令输出
        all_system_info = {}  # 存储系统信息
        final_status = "succeed"  # 默认成功状态

        for device_info in devices:
            role = device_info["role"]
            hostip = device_info["hostip"]
            
            # 在每个设备迭代开始时就初始化命令记录列表，确保设备间数据隔离
            device_executed_commands = []  # 每个设备使用全新的命令记录列表
            device_name = f"{role}_{hostip}"  # 初始化设备名，避免引用未定义变量
            system_info = None  # 初始化system_info
            
            # 检查每个角色所需的特定接口参数
            required_interfaces = []
            
            if role == "PE1":
                required_interfaces = ["PE1_to_P", "PE1_to_CE1"]
            elif role == "PE2":
                required_interfaces = ["PE2_to_P", "PE2_to_CE2"]
            elif role == "P":
                required_interfaces = ["P_to_PE1", "P_to_PE2"]
            elif role == "CE1":
                required_interfaces = ["CE1_to_PE1"]
            elif role == "CE2":
                required_interfaces = ["CE2_to_PE2"]
            else:
                print(f"错误: 不支持的设备角色 '{role}'")
                continue
                
            # 检查是否缺少任何所需的接口
            missing_interfaces = []
            empty_interfaces = []

            for intf in required_interfaces:
                if intf not in interfaces:
                    missing_interfaces.append(intf)
                elif not interfaces[intf]:  # 检查值是否为空
                    empty_interfaces.append(intf)

            # 处理缺失的接口参数
            if missing_interfaces:
                print(f"错误: {role}设备缺少必要的接口参数: {', '.join(missing_interfaces)}")
                continue

            # 处理空值的接口参数
            if empty_interfaces:
                print(f"错误: {role}设备的以下接口参数值为空: {', '.join(empty_interfaces)}")
                continue
                
            username = device_info["username"]
            password = device_info["password"]
            
            try:
                # 使用login_args模块登录设备
                net_connect = login_args.login(hostip, username, password)
                
                # 修改设备登录失败处理部分
                if net_connect is None:
                    error_msg = f"{role}设备({hostip})登录失败"
                    print(f"\n{error_msg}")
                    final_status = "Failed"
                    
                    # 使用字典格式记录错误
                    result["error_message"][f"{role}_{hostip}"] = error_msg
                    continue
                
                print(f"成功登录{role}设备")
                
                # 获取初始提示符和设备名
                device_name = ""
                try:
                    current_prompt = net_connect.find_prompt()
                    # 从提示符中提取设备名
                    if '<' in current_prompt and '>' in current_prompt:
                        device_name = re.search(r'<([^>]+)>', current_prompt).group(1)
                    elif '[' in current_prompt and ']' in current_prompt:
                        device_name = re.search(r'\[([^\]-]+)', current_prompt).group(1)  # 只提取设备名部分，不包括接口名
                    else:
                        device_name = f"{role}_{hostip}"  # 如果无法提取，使用角色_IP作为名称
                except:
                    net_connect.write_channel('\n')
                    time.sleep(0.5)
                    current_prompt = net_connect.read_until_pattern(r"[>\]]$").strip()
                    device_name = f"{role}_{hostip}"  # 备用名称
                
                print(f"提取到的设备名称: {device_name}")
                
                # 获取系统信息并确保是字典类型
                try:
                    system_info = get_system_info.get_system_info(net_connect)
                    
                    # 使用更简单、更可靠的方法清理输出
                    if isinstance(system_info, str):
                        # 1. 先检查是否包含"display version"
                        if "display version" in system_info.lower():
                            # 2. 找到命令在输出中的位置
                            cmd_index = system_info.lower().find("display version")
                            # 3. 查找命令后的第一个换行符
                            nl_index = system_info.find("\n", cmd_index)
                            if nl_index > 0:
                                # 4. 从换行符后开始截取内容
                                system_info = system_info[nl_index + 1:].strip()
                except Exception as e:
                    print(f"获取系统信息时发生错误: {str(e)}")
                    system_info = ""  # 错误时使用空字符串
                
                # 在获取系统信息后、生成配置前添加接口映射代码
                print(f"获取{device_name}设备的接口信息...")

                # 尝试自动映射接口编号为完整接口名称
                try:
                    # 保存原始接口字典
                    original_interfaces = interfaces.copy()
                    
                    # 获取设备所有接口
                    all_interfaces = interface_config.get_device_interfaces(net_connect)
                    print(f"成功获取到{len(all_interfaces)}个接口")
                    
                    # 检查每个接口是否需要映射
                    for intf_key, intf_value in original_interfaces.items():
                        # 只映射与当前设备相关的接口
                        if intf_key.startswith(f"{role}_") or f"_{role}_" in intf_key:
                            # 确保interfaces是字典类型
                            if not isinstance(device_info["interfaces"], dict):
                                print(f"警告: 设备{device_name}的接口不是字典类型，重新初始化")
                                device_info["interfaces"] = original_interfaces.copy()
                                
                            # 如果接口值不为空且不是完整的接口名称
                            if (intf_value and isinstance(intf_value, str) and not intf_value.lower().startswith(("GigabitEthernet", "Ten-GigabitEthernet", "Twenty-FiveGigE", "HGE", "HundredGigE", "FortyGigE", "WGE",
            "Vlan", "LoopBack", "Serial", "BAGG", "Bridge-Aggregation", "RAGG", "Route-Aggregation"))):
                                # 尝试映射接口
                                interfaces_to_map = [intf_value]
                                try:
                                    mapped_interfaces = interface_config.map_interface_number_to_name(all_interfaces, interfaces_to_map, net_connect)
                                    
                                    if isinstance(mapped_interfaces, list) and mapped_interfaces and mapped_interfaces[0]:
                                        # 更新接口字典中的值
                                        print(f"接口映射: {intf_key} = {intf_value} -> {mapped_interfaces[0]}")
                                        device_info["interfaces"][intf_key] = mapped_interfaces[0]  # 直接更新设备的接口字典
                                    else:
                                        print(f"警告: 无法映射接口 '{intf_value}'，将使用原始输入")
                                except Exception as mapping_error:
                                    print(f"映射接口 {intf_value} 时出错: {str(mapping_error)}")
                        else:
                            print(f"跳过接口 {intf_key}，不与当前设备{role}相关")
                    
                except Exception as e:
                    print(f"接口映射过程中出错: {str(e)}")
                    print("将使用原始接口名称")
                
                # 在接口映射完成后，检查接口模式
                print(f"检查并设置{device_name}设备的接口模式...")

                # 初始化命令记录列表(如果未定义)
                if 'device_executed_commands' not in locals() or device_executed_commands is None:
                    device_executed_commands = []

                # 确保有有效的当前提示符
                if 'current_prompt' not in locals() or not current_prompt:
                    try:
                        current_prompt = net_connect.find_prompt()
                    except:
                        net_connect.write_channel('\n')
                        time.sleep(0.5)
                        current_prompt = net_connect.read_until_pattern(r"[>\]]$").strip()
                        print(f"已获取当前提示符: {current_prompt}")

                # 确保在系统视图中
                if '<' in current_prompt and '>' in current_prompt:
                    print("当前处于用户视图，正在切换到系统视图...")
                    cmd_output, current_prompt = execute_command(
                        net_connect, 
                        "system-view", 
                        device_executed_commands, 
                        system_info, 
                        current_prompt,
                        device_name
                    )

                # 修改这部分代码以检查所有相关接口，而不仅仅是required_interfaces
                print("检查设备所有相关接口的链路模式...")

                # 遍历所有接口来检查哪些与当前设备相关
                for intf_key, interface_name in device_info["interfaces"].items():
                    # 更精确的匹配规则：接口键必须以当前角色开头，后跟下划线
                    if intf_key.startswith(f"{role}_") or f"_{role}_" in intf_key:
                        print(f"检查接口 {interface_name} ({intf_key}) 的链路模式...")
                        
                        try:
                            # 确保接口名称不为空且为字符串
                            if not interface_name or not isinstance(interface_name, str):
                                print(f"警告: 接口 {intf_key} 的值无效: '{interface_name}'")
                                continue
                                
                            # 直接进入接口配置模式检查
                            cmd_output, current_prompt = execute_command(
                                net_connect, 
                                f"interface {interface_name}", 
                                device_executed_commands, 
                                system_info, 
                                current_prompt,
                                device_name,
                                log_command=True  # 这个命令需要记录，它是配置的一部分
                            )
                            
                            # 检查当前模式 - 不记录这些诊断命令
                            try:
                                display_output, display_prompt = execute_command(
                                    net_connect, 
                                    "display this", 
                                    device_executed_commands, 
                                    system_info, 
                                    current_prompt,
                                    device_name,
                                    log_command=False  # 不记录这个诊断命令
                                )
                            except Exception as e:
                                print(f"无法获取接口配置: {str(e)}")
                                print("尝试使用基本命令...")
                                # 尝试一个更简单的命令 - 同样不记录
                                display_output, display_prompt = execute_command(
                                    net_connect, 
                                    "display interface brief", 
                                    device_executed_commands, 
                                    system_info, 
                                    current_prompt,
                                    device_name,
                                    log_command=False  # 不记录这个诊断命令
                                )
                            
                            # 打印当前配置供诊断
                            print(f"接口 {interface_name} 当前配置:")
                            print(display_output.strip())
                            
                            # 判断接口模式并切换
                            if "port link-mode bridge" in display_output:
                                print(f"检测到接口 {interface_name} 为bridge模式，正在切换...")
                                
                                # 特殊处理port link-mode route命令，因为它需要确认
                                try:
                                    # 直接发送命令但不等待常规提示符，而是等待确认提示
                                    net_connect.write_channel("port link-mode route\n")
                                    time.sleep(1)
                                    
                                    # 等待确认提示
                                    output = net_connect.read_until_pattern(r"\[Y/N\]:")
                                    print(output.strip())  # 打印确认信息
                                    
                                    # 发送确认
                                    net_connect.write_channel("Y\n")
                                    time.sleep(1)
                                    
                                    # 等待命令完成后的提示符
                                    output = net_connect.read_until_pattern(r"\[.*\]")
                                    print(f"确认结果: {output.strip()}")
                                    
                                    # 更新当前提示符
                                    current_prompt = output.strip()
                                    
                                    # 记录命令和结果
                                    log_text = f"[{device_name}-{interface_name}]port link-mode route\nThe configuration of the interface will be restored to the default. Continue? [Y/N]:Y\n"
                                    device_executed_commands.append(log_text)
                                    
                                    print(f"接口 {interface_name} 已成功切换为route模式")
                                except Exception as e:
                                    print(f"切换接口模式时出错: {str(e)}")
                            else:
                                print(f"接口 {interface_name} 已经是route模式或不需要设置")
                            
                            # 退出接口视图
                            cmd_output, current_prompt = execute_command(
                                net_connect, 
                                "quit", 
                                device_executed_commands, 
                                system_info, 
                                current_prompt,
                                device_name,
                                log_command=True  # 需要记录，因为它是配置会话的一部分
                            )

                            # 重新检测当前视图
                            current_view = check_current_view(current_prompt)
                            print(f"退出接口视图后的当前视图: {current_view}")
                            
                        except Exception as e:
                            print(f"检查/切换接口 {interface_name} 模式时出错: {str(e)}")
                            # 尝试退出接口视图
                            try:
                                execute_command(net_connect, "quit", device_executed_commands, system_info, current_prompt, device_name)
                            except:
                                pass
                
                # 配置前清除缓冲区
                net_connect.clear_buffer()

                # 生成配置命令
                try:
                    config_commands = generate_config(device_info)
                except ValueError as e:
                    print(f"错误: {str(e)}")
                    continue

                # 检查当前视图，决定是否需要执行system-view
                current_view = check_current_view(current_prompt)
                print(f"执行配置前当前视图: {current_view}")

                # 按行分割配置命令
                config_lines = config_commands.strip().split('\n')

                # 处理第一个命令（通常是system-view）
                first_cmd = config_lines[0].strip()
                if first_cmd == "system-view" and current_view == "system_view":
                    print("已经在系统视图中，跳过system-view命令")
                    config_lines = config_lines[1:]  # 移除第一行system-view命令
                elif not first_cmd:
                    config_lines = config_lines[1:]  # 跳过空行

                # 逐行执行配置命令
                for cmd in config_lines:
                    if cmd.strip():  # 跳过空行
                        cmd_output, current_prompt = execute_command(
                            net_connect, 
                            cmd.strip(), 
                            device_executed_commands, 
                            system_info, 
                            current_prompt,
                            device_name
                        )
                
                # 将此设备的命令输出添加到总字典中，使用设备名作为键
                all_commands[device_name] = device_executed_commands
                all_system_info[device_name] = system_info

                print(f"\n{role}配置成功")
                
                if role == "PE2":
                    # 只有当所有设备配置都成功时才进行BGP状态检查
                    if final_status != "Failed":
                        print("\nPE2配置完成，开始检查BGP邻居状态...")
                        
                        # 检查VPNv4地址族邻居状态
                        bgp_status_results = {}
                        
                        print("\n检查VPNv4地址族邻居状态...")
                        vpnv4_status_success, vpnv4_status_result = monitor_bgp_neighbor_status(
                            net_connect, 
                            device_name, 
                            address_type="vpnv4", 
                            timeout_minutes=1,
                            check_interval=5
                        )
                        
                        # 记录VPNv4检查结果
                        bgp_status_results["VPNv4"] = vpnv4_status_result
                        print(f"VPNv4 BGP邻居状态检查结果: {vpnv4_status_result}")
                        
                        # 检查VPNv6地址族邻居状态
                        print("\n检查VPNv6地址族邻居状态...")
                        vpnv6_status_success, vpnv6_status_result = monitor_bgp_neighbor_status(
                            net_connect, 
                            device_name, 
                            address_type="vpnv6", 
                            timeout_minutes=1,
                            check_interval=5
                        )

                        # 记录VPNv6检查结果
                        bgp_status_results["VPNv6"] = vpnv6_status_result
                        print(f"VPNv6 BGP邻居状态检查结果: {vpnv6_status_result}")

                        # 使用单独的result字典存储BGP状态，不影响system_info
                        result["bgp_peer_status"] = bgp_status_results

                        # 更新设备信息字典
                        all_system_info[device_name] = system_info
                        
                        # 汇总显示结果
                        print("\nBGP邻居状态检查汇总:")
                        print(f"VPNv4: {vpnv4_status_result}")
                        print(f"VPNv6: {vpnv6_status_result}")
                    else:
                        print("\n由于有设备配置失败，跳过BGP邻居状态检查")

            except Exception as e:
                # 修改第842行左右的异常处理代码
                # 解析异常参数，获取错误消息和设备名
                if len(e.args) >= 2:
                    # 如果异常包含两个参数（错误消息和设备名）
                    error_msg = str(e.args[0])
                    device_key = str(e.args[1])
                else:
                    # 如果只有错误消息，使用当前设备名
                    error_msg = str(e)
                    device_key = device_name if device_name else f"{role}_{hostip}"
                
                print(f"\n{device_key}: {error_msg}")
                final_status = "Failed"  # 如果任何设备失败，最终状态为失败
                
                # 使用字典格式记录错误
                result["error_message"][device_key] = error_msg

                # 使用当前设备的命令记录，而不是可能从上一个设备继承的列表
                # 如果设备名称已提取，使用设备名，否则使用备用名称
                all_commands[device_key] = device_executed_commands  # 使用当前设备的命令列表
                all_system_info[device_key] = system_info if system_info else None
            
            finally:
                # 断开连接
                if 'net_connect' in locals() and net_connect:
                    net_connect.disconnect()
                    print(f"{role}设备已断开连接\n")

        # 所有设备配置完成后，记录最终状态
        # 无条件传递result字典，确保错误信息始终被记录
        write_log.write_log(
            final_status, 
            all_commands, 
            all_system_info, 
            file_suffix="mpls_l3vpn_status",
            **result  # 无条件传递result字典内容
        )
    
    except Exception as e:
        # 捕获任何未处理的异常，确保记录Failed状态
        print(f"发生未处理的异常: {str(e)}")
        write_log.write_log("Failed", all_commands if 'all_commands' in locals() else [], 
                           all_system_info if 'all_system_info' in locals() else {})
        sys.exit(1)

if __name__ == "__main__":
    main()
    sys.exit(0)