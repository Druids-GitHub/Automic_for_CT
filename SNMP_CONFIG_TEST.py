#写一个配置H3C路由器、交换机SNMP功能的脚本。
#1. 使用现成的login_args.py中的login函数来实现登录认证等功能
#2. 登录成功后，默认下发system-view命令，用来进入系统视图

import sys
import os
import json
import time
import re
from datetime import datetime

# 导入自定义模块
import login_args
import write_log
import get_system_info
import check_device_output

def generate_snmp_config(device_info):
    """生成SNMP配置命令列表，但不默认添加system-view命令"""
    community_read = device_info.get('community_read', 'public')
    community_write = device_info.get('community_write', 'private')
    snmp_version = device_info.get('snmp_version', 'all')
    trap_host = device_info.get('trap_host', '')
    
    # SNMPv3 相关参数
    snmp_user_group = device_info.get('snmp_user_group', '')
    snmp_username = device_info.get('snmp_username', '')
    snmp_sha_key = device_info.get('snmp_sha_key', '')
    snmp_aes_key = device_info.get('snmp_aes_key', '')
    
    # 初始化命令列表
    config_lines = []
    
    # 启用SNMP
    config_lines.append("snmp-agent")
    
    # 添加团体字配置
    config_lines.append(f"snmp-agent community read {community_read}")
    config_lines.append(f"snmp-agent community write {community_write}")
    
    # 添加SNMP版本配置
    if snmp_version == 'all':
        config_lines.append("snmp-agent sys-info version all")
    elif snmp_version in ['v1', 'v2c', 'v3']:
        config_lines.append(f"snmp-agent sys-info version {snmp_version}")
    
    # SNMPv3 特殊配置
    if snmp_version == 'v3' or snmp_version == 'all':
        # 检查必要的v3参数
        if snmp_user_group and snmp_username and snmp_sha_key and snmp_aes_key:
            # 添加用户组
            config_lines.append(f"snmp-agent group v3 {snmp_user_group}")
            
            # 添加用户配置
            config_lines.append(f"snmp-agent usm-user v3 {snmp_username} {snmp_user_group} simple authentication-mode sha {snmp_sha_key} privacy-mode aes128 {snmp_aes_key}")
        elif snmp_version == 'v3':
            # 如果选择了v3但缺少必要参数，给出警告
            print("警告: SNMPv3 需要以下参数: snmp_user_group, snmp_username, snmp_sha_key, snmp_aes_key")
    
    # Trap主机配置
    if trap_host and trap_host.strip():
        config_lines.append("snmp-agent trap enable")
        config_lines.append(f"snmp-agent target-host trap address udp-domain {trap_host.strip()} params securityname {community_read}")
    
    return config_lines

def execute_command(net_connect, command, executed_commands=None, system_info=None, current_prompt=None, device_name=None, log_command=True):
    """高速执行命令，优化网络交互，使用check_device_output模块检查错误"""
    if executed_commands is None:
        executed_commands = []
    
    try:
        # 打印命令（保持UI反馈）
        print(f"{current_prompt}{command}")
        
        # 优化1: 使用更高效的send_command替代send_command_timing
        cmd_output = net_connect.send_command(
            command,
            expect_string=r"[>\]]",  # 通用提示符匹配模式
            delay_factor=0.1,        # 保持较低延迟
            max_loops=50,            # 减少等待循环次数
            strip_command=True,      # 移除输出中的命令
            strip_prompt=True        # 移除输出中的提示符
        )
        
        # 优化2: 更高效的Y/N确认处理
        if "Y/N" in cmd_output or "[Y/N]" in cmd_output:
            net_connect.write_channel("Y\n")
            # 减少等待时间
            time.sleep(0.1)
            cmd_output += net_connect.read_until_pattern(r"[>\]]")
        
        # 优化3: 智能提示符处理 - 不频繁查询设备
        new_prompt = current_prompt  # 默认保持当前提示符
        
        # 优化4: 针对不同命令智能预测提示符变化
        if command == "system-view":
            # system-view命令始终进入系统视图
            if device_name and '<' in current_prompt:
                new_prompt = f"[{device_name}]"  # 直接构造新提示符
            else:
                # 仅在必要时查询
                try:
                    new_prompt = net_connect.find_prompt()
                except:
                    if device_name:
                        new_prompt = f"[{device_name}]"
            
            # 记录命令
            if log_command:
                executed_commands.append(f"{current_prompt}{command}\n{cmd_output.strip()}")
            
            return cmd_output, new_prompt
            
        elif command == "quit":
            # 退出当前视图
            if '[' in current_prompt and '<' not in current_prompt and device_name:
                new_prompt = f"<{device_name}>"  # 退出到用户视图
        
        # 显示输出（保持UI反馈）
        if cmd_output.strip():
            print(cmd_output.strip())
        
        # 记录命令
        if log_command:
            executed_commands.append(f"{current_prompt}{command}\n{cmd_output.strip()}")
        
        # 使用check_device_output模块检查错误
        status = check_device_output.check_device_output(cmd_output)
        if status == "Failed":
            raise Exception(f"执行命令 '{command}' 失败", device_name or "Unknown_Device")
        
        return cmd_output, new_prompt
        
    except Exception as e:
        if len(e.args) >= 2:
            raise e
        else:
            raise Exception(str(e), device_name or "Unknown_Device")

def check_current_view(prompt):
    """判断当前所处的视图 - 增强识别能力"""
    # 增强系统视图的识别，更宽松的匹配
    if '[' in prompt and ']' in prompt:
        return "system_view"  # 系统视图 [设备名]
    # 用户视图识别
    elif '<' in prompt and '>' in prompt:
        return "user_view"  # 用户视图 <设备名>
    else:
        print("未知视图类型")
        return "unknown_view"

def snmp_config(hostip, username, password, community_read, community_write, snmp_version, trap_host, 
                snmp_user_group='', snmp_username='', snmp_sha_key='', snmp_aes_key=''):
    """执行SNMP配置 - 支持SNMPv3参数"""
    device_executed_commands = []
    system_info = ""
    error_msg = ""
    device_name = ""
    
    try:
        # 使用login_args模块进行设备连接
        print(f"正在连接设备 {hostip}...")
        
        try:
            # 尝试通过login_args模块
            net_connect = login_args.login(hostip, username, password)
        except:
            # 如果不支持，直接创建连接
            from netmiko import ConnectHandler
            device = {
                'device_type': 'hp_comware',
                'host': hostip,
                'username': username,
                'password': password,
                'fast_cli': True
            }
            net_connect = ConnectHandler(**device)
        
        if net_connect is None:
            raise Exception(f"设备({hostip})登录失败", hostip)
        
        # 直接获取当前提示符
        current_prompt = net_connect.find_prompt()
        
        # 提取设备名称
        if '<' in current_prompt and '>' in current_prompt:
            device_name = current_prompt.strip('<>')
        elif '[' in current_prompt and ']' in current_prompt:
            device_name = current_prompt.strip('[]')
        else:
            device_name = f"SNMP_Server_{hostip}"

        # 获取真实系统信息
        try:
            system_info = get_system_info.get_system_info(net_connect)
        except Exception as e:
            print(f"获取系统信息时发生错误: {str(e)}")
            system_info = f"Device: {device_name} ({hostip}) - System info unavailable"
        
        # 检查当前视图并切换到系统视图
        current_view = check_current_view(current_prompt)

        if current_view == "user_view":
            cmd_output, current_prompt = execute_command(
                net_connect, 
                "system-view", 
                device_executed_commands, 
                system_info, 
                current_prompt,
                device_name
            )

        else:
            print("已经在系统视图中，无需切换视图")

        # 生成SNMP配置命令
        device_info = {
            "hostip": hostip,
            "community_read": community_read,
            "community_write": community_write,
            "snmp_version": snmp_version,
            "trap_host": trap_host,
            "snmp_user_group": snmp_user_group,
            "snmp_username": snmp_username,
            "snmp_sha_key": snmp_sha_key,
            "snmp_aes_key": snmp_aes_key
        }
        config_lines = generate_snmp_config(device_info)

        # 逐行执行配置命令
        for cmd in config_lines:
            if cmd.strip():
                _, current_prompt = execute_command(
                    net_connect, 
                    cmd.strip(), 
                    device_executed_commands, 
                    system_info, 
                    current_prompt,
                    device_name
                )
                sys.stdout.flush()
        
        # 断开连接
        net_connect.disconnect()
        print(f"\nSNMP配置完成，设备 {device_name} 已断开连接")
        
        return True, device_executed_commands, system_info, "", device_name
        
    except Exception as e:
        error_msg = str(e.args[0]) if e.args else str(e)
        device_key = str(e.args[1]) if len(e.args) >= 2 else device_name or hostip
        print(f"\nSNMP配置失败: {error_msg}")
        
        try:
            if 'net_connect' in locals() and net_connect:
                net_connect.disconnect()
        except:
            pass
        
        return False, device_executed_commands, system_info, error_msg, device_key

def main():
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("使用方法:")
        print(f'python {os.path.basename(__file__)} \'{{参数}}\'')
        print("\n参数格式:")
        print('"hostip":"192.168.1.1,192.168.1.2"')
        print('"username":"admin" (单个值将应用于所有设备)')
        print('"password":"password" (单个值将应用于所有设备)')
        print('"community_read":"public" (读团体字，可选，默认为public)')
        print('"community_write":"private" (写团体字，可选，默认为private)')
        print('"snmp_version":"v2c" (SNMP版本，可选值：v1、v2c、v3、all，默认为v2c)')
        print('"trap_host":"192.168.1.100" (Trap主机，单个IP地址，可选)')
        print('\nSNMPv3 额外参数 (当snmp_version为v3或all时需要):')
        print('"snmp_user_group":"mygroup" (SNMPv3用户组名)')
        print('"snmp_username":"myuser" (SNMPv3用户名)')
        print('"snmp_sha_key":"mysha123" (SHA认证密钥)')
        print('"snmp_aes_key":"myaes123" (AES128加密密钥)')
        
        print("\n完整示例 (v2c):")
        print(f'python {os.path.basename(__file__)} \'{{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","community_read":"public","community_write":"private","snmp_version":"v2c","trap_host":"192.168.1.100"}}\'')
        
        print("\n完整示例 (v3):")
        print(f'python {os.path.basename(__file__)} \'{{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","snmp_version":"v3","snmp_user_group":"admingroup","snmp_username":"admin","snmp_sha_key":"sha123456","snmp_aes_key":"aes123456","trap_host":"192.168.1.100"}}\'')
        sys.exit(1)
    
    # 解析JSON参数
    try:
        json_str = sys.argv[1]
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
        config = json.loads(json_str)
        
        # 在成功解析参数后立即记录Running状态的日志
        write_log.write_log(
            "Running", 
            {}, 
            {}, 
            file_suffix="snmp_config"
        )
        
        # 获取基本参数
        hostips = config.get('hostip', '').split(',')
        usernames = config.get('username', '').split(',')
        passwords = config.get('password', '').split(',')
        community_reads = config.get('community_read', 'public').split(',')
        community_writes = config.get('community_write', 'private').split(',')
        snmp_versions = config.get('snmp_version', 'v2c').split(',')
        trap_host = config.get('trap_host', '')
        
        # SNMPv3 参数
        snmp_user_group = config.get('snmp_user_group', '')
        snmp_username = config.get('snmp_username', '')
        snmp_sha_key = config.get('snmp_sha_key', '')
        snmp_aes_key = config.get('snmp_aes_key', '')
        
        # 扩展单值参数到与设备数量匹配
        if len(usernames) == 1 and len(hostips) > 1:
            usernames = usernames * len(hostips)
        if len(passwords) == 1 and len(hostips) > 1:
            passwords = passwords * len(hostips)
        if len(community_reads) == 1 and len(hostips) > 1:
            community_reads = community_reads * len(hostips)
        if len(community_writes) == 1 and len(hostips) > 1:
            community_writes = community_writes * len(hostips)
        if len(snmp_versions) == 1 and len(hostips) > 1:
            snmp_versions = snmp_versions * len(hostips)
        
        # 创建设备列表
        devices = []
        for i in range(len(hostips)):
            device = {
                'hostip': hostips[i].strip(),
                'username': usernames[i % len(usernames)].strip(),
                'password': passwords[i % len(passwords)].strip(),
                'community_read': community_reads[i % len(community_reads)].strip(),
                'community_write': community_writes[i % len(community_writes)].strip(),
                'snmp_version': snmp_versions[i % len(snmp_versions)].strip(),
                'trap_host': trap_host,
                'snmp_user_group': snmp_user_group,
                'snmp_username': snmp_username,
                'snmp_sha_key': snmp_sha_key,
                'snmp_aes_key': snmp_aes_key
            }
            devices.append(device)
        
        # 初始化结果收集
        all_commands = {}
        all_system_info = {}
        final_status = "succeed"
        result = {"error_message": {}}
        
        # 执行配置
        for i, device in enumerate(devices):
            hostip = device.get('hostip')
            username = device.get('username')
            password = device.get('password')
            community_read = device.get('community_read')
            community_write = device.get('community_write')
            snmp_version = device.get('snmp_version')
            device_trap_host = device.get('trap_host')
            device_snmp_user_group = device.get('snmp_user_group')
            device_snmp_username = device.get('snmp_username')
            device_snmp_sha_key = device.get('snmp_sha_key')
            device_snmp_aes_key = device.get('snmp_aes_key')
            
            # 检查必要参数
            missing = []
            if not hostip:
                missing.append('hostip')
            if not username:
                missing.append('username')
            if not password:
                missing.append('password')
            
            if missing:
                print(f"错误: 设备 {hostip if hostip else i+1} 缺少必要参数: {', '.join(missing)}")
                continue
            
            # 验证snmp_version参数
            if snmp_version not in ['v1', 'v2c', 'v3', 'all']:
                print(f"错误: 设备 {hostip} 的snmp_version参数无效: {snmp_version}")
                print("有效值: v1, v2c, v3, all")
                final_status = "Failed"
                result["error_message"][hostip] = f"无效的snmp_version参数: {snmp_version}"
                continue
            
            # 检查SNMPv3参数
            if snmp_version == 'v3' or snmp_version == 'all':
                v3_missing = []
                if not device_snmp_user_group:
                    v3_missing.append('snmp_user_group')
                if not device_snmp_username:
                    v3_missing.append('snmp_username')
                if not device_snmp_sha_key:
                    v3_missing.append('snmp_sha_key')
                if not device_snmp_aes_key:
                    v3_missing.append('snmp_aes_key')
                
                if v3_missing and snmp_version == 'v3':
                    print(f"错误: 设备 {hostip} 选择SNMPv3但缺少必要参数: {', '.join(v3_missing)}")
                    final_status = "Failed"
                    result["error_message"][hostip] = f"SNMPv3缺少必要参数: {', '.join(v3_missing)}"
                    continue
            
            # 执行SNMP配置
            success, executed_commands, system_info, error_msg, device_name = snmp_config(
                hostip, username, password, community_read, community_write, snmp_version, device_trap_host,
                device_snmp_user_group, device_snmp_username, device_snmp_sha_key, device_snmp_aes_key
            )
            
            # 使用设备名称作为键
            device_key = device_name if device_name else hostip
            
            # 收集设备结果
            all_commands[device_key] = executed_commands
            all_system_info[device_key] = system_info
            
            # 处理错误
            if not success:
                final_status = "Failed"
                if error_msg:
                    result["error_message"][device_key] = error_msg
        
        # 写入日志
        write_log.write_log(
            final_status, 
            all_commands, 
            all_system_info, 
            file_suffix="snmp_config",
            **result
        )
        
    except json.JSONDecodeError as e:
        print(f"JSON参数解析错误: {str(e)}")
        print("请检查参数格式是否正确")
        sys.exit(1)
    except Exception as e:
        print(f"程序执行出错: {str(e)}")
        # 确保即使出错也写入日志
        try:
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="snmp_config",
                error_message={"General": str(e)}
            )
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()