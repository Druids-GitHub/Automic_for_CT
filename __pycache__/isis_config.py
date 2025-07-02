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
from check_device_output import check_device_output
from get_system_info import get_system_info
from write_log import write_log

def ssh_system_view(device_params):
    """
    登录设备并执行system-view命令
    Args:
        device_params (dict): 包含设备连接参数的字典
            {
                "ip": "设备IP地址",
                "username": "登录用户名",
                "password": "登录密码"
            }
    """
    # 验证必需的参数
    required_params = ['ip', 'username', 'password']
    if not all(param in device_params for param in required_params):
        print("缺少必需的参数，需要包含：", required_params)
        return
    
    # 调用login_args模块进行设备登录
    ssh = login_args.run_script(device_params)
    
    # 判断是否登录成功
    if ssh:
        try:
            executed_commands = []  # 记录执行的命令
            # 清除缓冲区并获取系统信息
            ssh.clear_buffer()
            system_info = get_system_info(ssh)  # 修改函数调用
            
            # 获取并显示当前视图（设备的第一条回显）
            print(ssh.find_prompt(), end='')
            
            # 进入系统视图
            output = ssh.send_command_timing(
                "system-view",
                strip_prompt=False,
                strip_command=False,
                delay_factor=1
            )
            print(output.rstrip(), end='')
            executed_commands.append({"command": "system-view", "output": output.strip()})
            
            # 检查命令输出
            status = check_device_output(output)  # 修改函数调用
            if status == "Failed":
                write_log(status, executed_commands, system_info)  # 修改函数调用
                return status
            
            # 逐行发送 ISIS 配置命令并实时显示输出
            # 定义默认命令列表
            default_commands = [
                "isis 100",
                "net 49.0001.0000.0000.0001.00",
                "is-level level-2",
                "cost-style wide",
                "end"
            ]
            
            # 从device_params中获取用户自定义命令参数，如果没有则使用默认值
            isis_process_id = device_params.get('isis_process_id', '100')
            isis_net = device_params.get('isis_net', '49.0001.0000.0000.0001.00')
            isis_islevel = device_params.get('isis_islevel', 'level-2')
            isis_coststype = device_params.get('isis_coststype', 'wide')

            # 使用获取的参数构建命令列表
            commands = [
                f"isis {isis_process_id}",
                f"net {isis_net}",
                f"is-level {isis_islevel}",
                f"cost-style {isis_coststype}",
                "quit"
            ]
            
            for cmd in commands:
                # 使用send_command替代send_command_timing以加快速度
                output = ssh.send_command(
                    cmd,
                    strip_prompt=False,
                    strip_command=False,
                    expect_string=r"]"  # 等待提示符出现即可发送下一条命令
                )
                print(output.rstrip(), end='')
                executed_commands.append({"command": cmd, "output": output.strip()})
                
                # 检查每条命令的输出
                status = check_device_output(output)  # 修改函数调用
                if status == "Failed":
                    write_log(status, executed_commands, system_info)  # 修改函数调用
                    return status
            
            # 所有命令执行成功
            write_log("succeed", executed_commands, system_info)  # 修改函数调用
            
            # 持续接收用户输入的命令
            while True:
                try:
                    command = input()
                    if command:  # 只处理非空命令
                        output = ssh.send_command(
                            command,
                            strip_prompt=False,
                            strip_command=False,
                            expect_string=r"]"
                        )
                        print(output.rstrip(), end='')
                except KeyboardInterrupt:
                    print("\n收到退出信号，正在退出程序...")
                    break
                except Exception as e:
                    print(f"\n命令执行错误：{str(e)}")
                    
        except Exception as e:
            print(f"配置执行失败：{str(e)}")
            write_log("Failed", [], f"执行失败：{str(e)}")
            return "Failed"
            
    else:
        print("设备登录失败")
        write_log("Failed", [], "设备登录失败")
        return "Failed"

def main():
    if len(sys.argv) != 2:
        print("使用方法:")
        print('python sys2.py {"ip":"192.168.1.1","username":"admin","password":"h3c.com123",' 
              '"isis_process_id":"进程号ID","isis_net":"xx.xxxx.xxxx.xxxx.xxxx.00",'
              '"isis_islevel":"1或2或者12","isis_coststype":"wide"}')
        print("注意: ISIS参数是可选的。如果不提供，将使用以下默认值：")
        print("- isis_process_id (默认值: 100)")
        print("- isis_net (默认值: 49.0001.0001.0001.0001.00)") 
        print("- isis_islevel (默认值: 2)")
        print("- isis_coststype (默认值: wide)")
        sys.exit(1)
        
    try:
        # 处理输入参数
        json_str = sys.argv[1]

        # 确保JSON字符串格式正确
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
        
        device_params = json.loads(json_str)
        
        # 处理isis_islevel参数转换
        if 'isis_islevel' in device_params:
            islevel = str(device_params['isis_islevel'])
            if islevel == '1':
                device_params['isis_islevel'] = 'level-1'
            elif islevel == '2':
                device_params['isis_islevel'] = 'level-2'
            elif islevel == '12':
                device_params['isis_islevel'] = 'level-1-2'
        
        if not isinstance(device_params, dict):
            print("错误：参数必须是JSON对象格式")
            print("使用方法:")
            print('python sys2.py {"ip":"192.168.1.1","username":"admin","password":"h3c.com123",' 
                  '"isis_process_id":"进程号ID","isis_net":"xx.xxxx.xxxx.xxxx.xxxx.00",'
                  '"isis_islevel":"1或2或者12","isis_coststype":"wide"}')
            print("注意: ISIS参数是可选的。如果不提供，将使用以下默认值：")
            print("- isis_process_id (默认值: 100)")
            print("- isis_net (默认值: 49.0001.0001.0001.0001.00)")
            print("- isis_islevel (默认值: 2)")
            print("- isis_coststype (默认值: wide)")
            sys.exit(1)
            
        ssh_system_view(device_params)
    except json.JSONDecodeError as e:
        print("JSON格式错误，请使用正确的JSON格式")
        print("使用方法:")
        print('python sys2.py {"ip":"192.168.1.1","username":"admin","password":"h3c.com123",' 
              '"isis_process_id":"进程号ID","isis_net":"xx.xxxx.xxxx.xxxx.xxxx.00",'
              '"isis_islevel":"1或2或者12","isis_coststype":"wide"}')
        print("注意: ISIS参数是可选的。如果不提供，将使用以下默认值：")
        print("- isis_process_id (默认值: 100)")
        print("- isis_net (默认值: 49.0001.0001.0001.0001.00)")
        print("- isis_islevel (默认值: 2)")
        print("- isis_coststype (默认值: wide)")
        print(f"错误详情：{str(e)}")
    except Exception as e:
        print(f"执行失败：{str(e)}")

if __name__ == "__main__":
    main()