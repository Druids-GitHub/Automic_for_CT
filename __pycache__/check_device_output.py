def check_device_output(output):
    """
    检查设备回显信息是否包含错误信息
    Args:
        output (str): 设备的回显信息
    Returns:
        str: 'Failed' 如果包含错误信息，否则返回 'succeed'
    """
    error_messages = [
        "% Incomplete",
        "% Unrecognized",
        "% Ambiguous"
    ]
    
    for error in error_messages:
        if error in output:
            return "Failed"
    return "succeed"