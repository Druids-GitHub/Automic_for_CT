def get_system_info(ssh):
    """
    获取设备版本信息
    Args:
        ssh: netmiko连接对象
    Returns:
        str: 设备版本信息
    """
    output = ssh.send_command("display version", strip_command=False)
    return output.strip() if output else ""