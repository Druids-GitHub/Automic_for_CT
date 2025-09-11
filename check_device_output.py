def check_device_output(output):
    """
    检查设备回显信息是否包含错误信息（不区分大小写）
    Args:
        output (str): 设备的回显信息
    Returns:
        str: 如果包含任何错误提示则返回'Failed'，否则返回'succeed'
    """
    # 定义错误提示列表
    error_messages = [
        "% Wrong parameter",  # 参数错误
        "% Incomplete",    # 命令不完整
        "% Unrecognized",  # 无法识别的命令
        "% Ambiguous",     # 命令有歧义
        "% Invalid",       # 无效的命令
        "% Too many parameters",  # 参数过多
        "Error",         # 命令错误
        "Wrong",         # 错误的命令
        "Failed",        # 命令失败
        "overlaps",         # 重叠
        "Another IS-IS process is already enabled on the interface.",  # IS-IS进程已经在接口上启用
        "already exists",  # 已经存在
        "No such process exists.",  # 没有这样的进程存在
        "No traditional IS-IS is enabled on the interface.",  # 接口上没有启用传统的IS-IS
        "IPv6 is not enabled for the process.",  # 进程未启用IPv6
        "NET Set - System is running. SystemId conflict",  # 系统ID冲突
        "The IP address belongs to the network segment that contains the IP address of",
        "Invalid "
    ]

    # 将输出转换为小写进行比较，这样不区分大小写
    output_lower = output.lower()

    # 检查输出中是否包含任何错误提示（不区分大小写）
    if any(error.lower() in output_lower for error in error_messages):
        return "Failed"

    return "succeed"
