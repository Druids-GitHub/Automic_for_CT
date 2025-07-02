def get_system_info(ssh_connection, delay_factor=5):
    """
    获取设备版本信息
    Args:
        ssh: netmiko连接对象
    Returns:
        str: 设备版本信息
    """
    try:
        # 使用更长的延迟因子执行display version命令
        output = ssh_connection.send_command_timing(
            "display version",
            strip_prompt=True,
            strip_command=True,
            delay_factor=delay_factor
        )
        return output
    except Exception as e:
        return f"获取系统信息失败: {str(e)}"