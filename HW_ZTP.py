#! usr/bin/python
# -*- coding:utf-8 -*-


import comware
from time import strftime, gmtime, sleep
import signal
import os
import string
import commands
import hashlib

##########################################################################
######################## User Definitions ################################
##########################################################################
#
# Transfer information
#
username = ""
password = ""
hostname = "2.2.1.10"
protocol = "tftp"
vrf = ""
# 下载配置文件的超时时间120s
config_download_timeout = 120
image_timeout = 2100
patch_timeout = 600

# Required space to copy configuration file and system image in KB
required_space = 250000

# 文件服务器上需要放置以序列号为名的.cfg文件：
# 210235A1TXH176000281.cfg 

use_identify_file_type = ""


# 文件服务器上需要放置以序列号为名的.cfg文件：
# 210235A1TXH176000281.cfg 
# 
#
#
# 标识文件类型，默认为序列号文件，可选值为SN/MAC/NONE
# MAC: 以设备桥mac作为标识符来获取堆叠信息
# SN: 以设备序列号作为标识符来获取堆叠信息
# NONE: 没有标识文件，没有堆叠环境

use_identify_file_type = ""

# 文件服务器上存放的序列号文件名称，里面存放内容根据标识类型来定如下
# SN类型
# sn.txt:
# ESN                   Stack group  Stack member
# 210235A1TXH176000281  10           1

# MAC类型
# mac.txt:
# MAC                   Statck group Stack member 
# 487a-da77-8f0f        10           1

identify_file_name = "manuinfo.txt"

# 下载标识文件超时时间
identify_download_timeout = 120

# 标识文件所处根目录哪个路径, 默认在根目录下, 如xxx/yyy/zzz/
identify_file_server_path = ""

# 版本文件所在服务器路径, 默认在根目录下
image_file_server_path = ""

# 补丁文件所在服务器路径, 默认在根目录下
patch_file_server_path = ""

# 配置文件所在服务器路径, 默认在根目录下
config_file_server_path = ""


#
# Specify the device type and its image name.
# 
# * device type: type string
# * version: type string, 
# * ipe_name: type string, ipe file name
# * patch_list: type string list, e.g. ['01.bin', '02.bin', '03.bin'] 
#               empty list e.g. []
# * Install_license: True or False
DEVICE_IMAGE_DESCRIPTION = [
    # S9855 image description
    {
        'device_type': 'S9855-48CD8D',     #display version中包含的设备型号，用于判断是哪个型号的设备
        'version': 'Alpha 912005',    #目标版本display version中的版本号
        'ipe_name': 'S9800X.ipe', #目标版本的ipe文件名，与设备型号对应
        'patch_list': [], #目标补丁的补丁文件名,与设备型号对应
    },
        # S9825 image description
    {
        'device_type': 'S9825-64D',     #display version中包含的设备型号，用于判断是哪个型号的设备
        'version': 'ESS 9124',    #目标版本display version中的版本号
        'ipe_name': 'S9800X.ipe', #目标版本的ipe文件名，与设备型号对应
        'patch_list': [], #目标补丁的补丁文件名,与设备型号对应
    },
    # S6850 image description
    {
        'device_type': 'S6850',
        'version': 'Test 7047P01',
        'ipe_name': 's9850-h3c-6555p01.ipe',
        'patch_list': [],
    },
    # S9850 image description
    {
        'device_type': 'S9850',
        'version': 'ESS 6506',
        'ipe_name': 'S9850_S6850-CMW710-E6506.ipe',
        'patch_list': ['S9850_S6850-CMW710-SYSTEM-E6506H03.bin'],
    },
	# S6800 image description
	{
        'device_type': 'S6800',
        'version': 'Release 2612P02',
        'ipe_name': 'S6860-CMW710-R2612P02.ipe',
        'patch_list': ['S6800-CMW710-SYSTEM-R2612P02H01.bin'], 
    },
]
        
##########################################################################
##########################################################################
##########################################################################


def get_device_info():
    global DEVICE_IMAGE_DESCRIPTION, SELF_DEVICE_INFO
    cli = comware.CLI("display version", False)
    device_info = cli.get_output()
    for image_info in DEVICE_IMAGE_DESCRIPTION:
        dev_type = image_info.get('device_type', '')
        for info in device_info:
            if info.find(dev_type) != -1:
                return image_info
    return None

#device image description
SELF_DEVICE_INFO = get_device_info()

NOT_SPECIFY_IPE = "Not specify the ipe name"

def get_self_device_ipe():
    global SELF_DEVICE_INFO
    global NOT_SPECIFY_IPE
    if SELF_DEVICE_INFO is not None:
        return SELF_DEVICE_INFO.get('ipe_name', NOT_SPECIFY_IPE)
    else:
        print "[ERROR] Not supported device type."
        return "Not support"

# IPE name which is used by self.
self_device_ipe_name = get_self_device_ipe()


def get_device_version():
    command = "display version"
    try:
        cli = comware.CLI(command, False)
        version_infos = cli.get_output()
        for info in version_infos:
            if info.find("Version") != -1:
                versions = info.split(",")
                if len(versions) > 2:
                    return versions[2].strip()
        return ""
    except Exception as excp:
        print "[ERROR] Execute command %s failed." %  command
        return ""

#两种配置文件命名方式，静态名称以及SN号命名
#- 'python_static'
#- 'python_serial_number'
python_config_file_mode = "python_static"

#Loacl File path
local_path = "flash:/"

#Local config name  设备本地使用的配置文件名
config_local_name = "startup.cfg"

#Server config name 文件服务器端静态命名的配置文件名，如果存在
config_server_name = "0607.cfg"

#Local boot name
boot_local_name = self_device_ipe_name

#Server boot name
boot_server_name = self_device_ipe_name

python_log_name = ""


# def write2Log(info):
    # global python_log_name, local_path
    # if python_log_name == "":
        # try:
            # comware.CLI('mkdir ZTP_log', False)
        # except Exception as SystemError:
            # print ('[INFO] The directory ZTP_log already exists.')
        # try:
            # python_log_name = "%sZTP_log/%s_python_%s_script.log" % (local_path,
                                                             # strftime("%Y%m%d%H%M%S", gmtime()),
                                                             # os.getpid())
        # except Exception as inst:
            # print inst
    # fd = open(python_log_name, "a")
    # fd.write(info)
    # fd.flush()
    # fd.close()


def getPath(chassisID, slotID):
    # get path according to the Chassis and Slot
    global local_path
    obj = comware.get_self_slot()
    if obj[0] == chassisID and obj[1] == slotID:
        return local_path

    path = ""
    if chassisID != -1:
        path = "chassis%d#" % chassisID
    if slotID != -1:
        path = "%sslot%d#%s" %(path, slotID, local_path)
    return path


def removeFile(filename):
    try:
        os.remove(filename)
    except os.error:
        pass


def cleanDeviceFiles(str, oDevNode):
    #Cleanup one device temp files
    global config_local_name, boot_local_name, identify_file_name
    sFilePath = getPath(oDevNode[0], oDevNode[1])
    if str == "error" and config_local_name.strip() != "":
        removeFile("%s%s" % (sFilePath, config_local_name))
    if boot_local_name.strip() != "":
        removeFile("%s%s" % (sFilePath, boot_local_name))
        removeFile("%s%s.md5" % (sFilePath, boot_local_name))
    if identify_file_name.strip() != "":
        removeFile("%s%s" % (sFilePath, identify_file_name))
        removeFile("%s%s.md5" % (sFilePath, identify_file_name))
    if config_local_name.strip() != "":
        removeFile("%s%s.md5" % (sFilePath, config_local_name))
    #write2Log("\n[INFO] delete %s all files\n" % sFilePath)
    print "[INFO] Delete %s all files" % sFilePath


def cleanupFiles(str):
    slot_range = []
    if "get_standby_slot" in dir(comware):
        slot_range = slot_range + comware.get_standby_slot()
    slot_range.append(comware.get_self_slot())

    for i in range(0, len(slot_range)):
        if slot_range[i] is not None:
            cleanDeviceFiles(str, slot_range[i])


def verifyfreespace(path):
    #Verify if free space is available to download config, boot-loader image
    global required_space
    try:
        s = os.statvfs(path)
        freespace = (s.f_bavail * s.f_frsize) /1024
        #write2Log("\n[DEBUG] The %s free space is %s" %(path, freespace))
        print "[DEBUG] The %s free space is %s" %(path, freespace)
        if required_space > freespace:
            #write2Log("\n[ERROR] The %s space is not enough" % path)
            print "[ERROR] The %s space is not enough." % path
            return False
    except Exception as inst:
        #write2Log("\n[ERROR] Verify %s free space exception: %s" % (path, inst))
        print "[ERROR] Verify %s free space exception: %s" % (path, inst)
        return False
    return True


def verifyDeviceFree(obj):
    path = getPath(obj[0], obj[1])
    if not verifyfreespace(path):
        return False
    return True
  

def verifyAllFreeSpace():
    #check all mpu free space
    slot_range = []
    if "get_standby_slot" in dir(comware):
        slot_range = slot_range + comware.get_standby_slot()

    slot_range.append(comware.get_self_slot())
    is_all_enough = True
    for i in range(0, len(slot_range)):
        if slot_range[i] is not None and not verifyDeviceFree(slot_range[i]):
            is_all_enough = False
    return is_all_enough


def doExit(str):
    if str == "success":
        #write2Log("\n[INFO] The script is running success!")
        print "[INFO] The script is running success!"
        cleanupFiles("success")
        cmd = "reboot force"
        comware.CLI(cmd, False)
        exit(0)
    elif str == "error":
        #write2Log("\n[ERROR] The script is running failed!")
        print "[ERROR] The script is running failed!"
        cleanupFiles("error")
        exit(1)
    else:
        exit(0)


def getChassisSlot(style):
    obj = None
    if style == "master":
        obj = comware.get_self_slot()
    if obj is None or len(obj) <= 0:
        #write2Log("\n[ERROR] Get %s chassis and slot failed" % style)
        print "[ERROR] Get %s chassis and slot failed." % style
        return None
    return obj


def sig_handler_no_exit(signum, function):
    #write2Log("\n[INFO] SIGTERM Handler while configuring boot-loader variables")
    print "\n[INFO] SIGTERM Handler while configuring boot-loader variables."


def sigterm_handler(signum, function):
    #write2Log("\n[DEBUG] SIGTERM Handler")
    print "\n[DEBUG] SIGTERM Handler"
    cleanupFiles("error")
    doExit("error")
  

def doCopyFile(src = "", des = "", login_timeout = 10):
    global username, password, hostname, protocol, vrf
    print "[INFO] Starting Copy of %s" % src
    try:
        removeFile(des)
        obj = comware.Transfer(protocol, hostname, src, des, vrf, login_timeout, username, password)
        if obj.get_error() != None:
            #write2Log("\n[WARN] Copy %s failed: %s" % (src, obj.get_error()))
            print "[WARN] Copy %s failed: %s" % (src, obj.get_error())
            return False
    except Exception as inst:
        #write2Log("\n[ERROR] copy %s exception: %s" % (src, inst))
        print "[ERROR] copy %s exception: %s" % (src, inst)
        return False
    #write2Log("\n[INFO] Copy file %s to %s success" % (src, des))
    print "[INFO] Copy %s done." % src
    return True


#Get config file according to the mode
def getCfgFileName():
  global config_server_name
  if (python_config_file_mode == "python_serial_number") and (os.environ.has_key('DEV_SERIAL')):    
    config_server_name = "%s.cfg" % os.environ['DEV_SERIAL']
    return config_server_name
  else:
    return config_server_name


#copy file to all standby slot
def syncFileToStandby(sSrcFile, sFileName):
  try:
    aSlotRange = []
    if ("get_standby_slot" in dir(comware)):
      aSlotRange = aSlotRange + comware.get_standby_slot()
          
    i = 0
    while i < len(aSlotRange):
      if(aSlotRange[i] != None):
        sDestFile = "%s%s" %(getPath(aSlotRange[i][0], aSlotRange[i][1]), sFileName)
        removeFile(sDestFile)
        open(sDestFile,"wb").write(open(sSrcFile,"rb").read())
        #write2Log("\n[INFO] Sync file to standby %s" % (sDestFile))
        print "[INFO] Sync file to standby %s" % (sDestFile)
      i = i + 1
  except Exception as inst:
    #write2Log("\n[ERROR] Sync file to standby %s exception: %s" % (sSrcFile, inst))
    print "[ERROR] Sync file to standby %s exception: %s####" % (sSrcFile, inst)
    


# split the Chassis and Slot  
def splitChassisSlot(chassisID, slotID):
  chassis_slot = ""
  if chassisID != -1:
    chassis_slot = " chassis %d"  % chassisID
  if slotID != -1:
    chassis_slot = "%s slot %d" %(chassis_slot, slotID)
  return chassis_slot

def copyBootImage():
  global image_timeout, local_path, boot_server_name, boot_local_name
  global image_file_server_path
  image_in_server = "%s%s" % (image_file_server_path, boot_server_name)
  image_in_flash = "%s%s" % (local_path, boot_local_name)
  if doCopyFile(image_in_server, image_in_flash, image_timeout):
      print '[INFO] Copy image file %s success.' % boot_server_name
      return True
  else:
      print "[ERROR] Failed to download image file %s." % boot_server_name
      return False


def copyCfgFile():
  global config_download_timeout, local_path, config_local_name,config_server_name
  global config_file_server_path 
  config_in_server = "%s%s" % (config_file_server_path, getCfgFileName())
  config_in_device = "%s%s" % (local_path, config_server_name)

  if doCopyFile(config_in_server, config_in_device, config_download_timeout):
      return True
  else:
      print "[ERROR] Download config file %s failed."  % config_in_server
      return False

def copyPatches(patch_list):
    global patch_timeout
    global local_path
    global patch_file_server_path
    patch_status = {}
    for patch in patch_list:
        patch_in_server = "%s%s" % (patch_file_server_path, patch)
        patch_in_device = "%s%s" % (local_path, patch)
        if doCopyFile(patch_in_server, patch_in_device, patch_timeout):
            patch_status[patch] = True
        else:
            patch_status[patch] = False
            print "[ERROR] Copy patch % failed, please check." % patch
    return patch_status


def installPatches(patch_list, patch_status):
    slots = comware.get_self_slot()
    commands = ""
    for patch in patch_list:
        if patch_status[patch]: 
            commands += "install activate patch flash:/%s slot %s ; " % (patch, slots[1])
    commands += " install commit"
    print ('[INFO] Install patch on slot ' + str(slots[1]) + '......')
    try:
        comware.CLI(commands, False)
        #write2Log("\n[INFO] Install patch on slot %s done." % slots[1])
        print ('[INFO] Install patch on slot %s done.' % slots[1])
    except SystemError:
        #write2Log("\n[ERROR] Install patch on slot %s failed." % slots[1])
        print ('[ERROR] Install patch on slot %s failed.' % slots[1])

# Procedure to Install Boot Image  
def installBoot(chassis_slot, sFile, style):
  result = None
  #write2Log("\n[INFO] Install %s " % sFile)
  print "[INFO] Install %s . Please Wait..." % sFile
  comd = "boot-loader file %s%s%s" % (sFile, chassis_slot, style)
  try:
    result = comware.CLI(comd, False) 
    if result == None:
      #write2Log("\n[WARN] boot-loader file %s%s%s failed" % (sFile, chassis_slot, style))
      print "[WARN] boot-loader file %s%s%s failed####" % (sFile, chassis_slot, style)
      return False
  except Exception as inst:
    #write2Log("\n[ERROR] boot-loader %s exception: %s" % (sFile, inst))
    print "\[ERROR] boot-loader %s exception: %s####" % (sFile, inst)
    return False  
  return True

#Procedure to install boot image
def installBootImage():
  global boot_local_name
  aSlotRange = [comware.get_self_slot()]
  if ("get_standby_slot" in dir(comware)):
    aSlotRange = aSlotRange + comware.get_standby_slot()
  bInstallOk = True
  i = 0
  while i < len(aSlotRange):
    sFile = "%s%s" %(getPath(aSlotRange[0][0], aSlotRange[0][1]), boot_local_name)
    if False == installBoot(splitChassisSlot(aSlotRange[i][0], aSlotRange[i][1]), sFile, " main"):
      bInstallOk = False
    i = i + 1
  return bInstallOk

def startupCfg():
  global local_path, config_local_name, config_server_name
  result = None
  dest = "%s%s" %(local_path, config_server_name)
  #write2Log("\n[INFO] startup saved-configuration %s begin" %dest)
  print "[INFO] startup saved-configuration %s begin" %dest
  comd = "startup saved-configuration %s main" % dest
  try:
    result = comware.CLI(comd, False)
    if result == None:
      #write2Log("\n[ERROR] startup saved-configuration %s failed." % dest)
      print "[ERROR] startup saved-configuration %s failed." % dest
      return False
  except Exception as inst:
    #write2Log("\n[ERROR] startup %s exception: %s" % (dest, inst))
    print "[ERROR] startup %s exception: %s" % (dest, inst)
    return False
  #write2Log("\n[INFO] startup saved-configuration %s success" % dest)
  print "[INFO] Startup Saved-configuration %s done." % dest
  return True

def copyIdentifyFile(type):
  global identify_download_timeout, local_path, identify_file_name
  if type.lower() == "none":
      return True
  identify_in_server = "%s%s" % (identify_file_server_path, identify_file_name)
  identify_in_device = "%s%s" % (local_path, identify_file_name)
  if doCopyFile(identify_in_server, identify_in_device, identify_download_timeout):
      return True
  else:
      print '[ERROR] Failed to download identify file %s from server.' % identify_file_name
      return False

def getIrfCfg(line, num):    
  line = line.split()
  number = None
  if 3 == len(line):
    number = line[num]
  else :
    number = None
  return number  

def getMemberID():
  aMemId = comware.get_self_slot()
  memId = None
  if aMemId[0] == -1 :
    memId = aMemId[1]
  else :
    memId = aMemId[0]
  return memId


def getNewMemberID(identify):
    global identify_file_name, local_path, env
    filename = "%s%s" %(local_path, identify_file_name)
    try:
        with open(filename, "r") as file:
            for line in file:
                if identify == getIrfCfg(line, 0):
                    return getIrfCfg(line, 2)
    except Exception as inst:
        #write2Log("\n[ERROR] Get renumberID exception: %s" % inst)
        print "[ERROR] Get renumberID exception: %s." % inst
    #write2Log("\n[ERROR] Get %s renumberID failed" % filename)
    print "[ERROR] Get %s renumberID failed." % filename
    return None

def isIRF(identify):
    global identify_file_name, local_path, env
    filename = "%s%s" %(local_path, identify_file_name)
    try:
        with open(filename, "r") as file:
            for line in file:
                if identify == getIrfCfg(line, 0):
                    return getIrfCfg(line, 1)
    except Exception as inst:
        #write2Log("\n[ERROR] Get renumberID exception: %s" % inst)
        print "[ERROR] Get renumberID exception: %s." % inst
    #write2Log("\n[ERROR] Get %s renumberID failed" % filename)
    print "[ERROR] Get %s renumberID failed." % filename
    return None


def isIrfDevice():
  try: 
    result = comware.CLI("display irf", False) 
    if result == None: 
      return False
  except Exception as inst: 
    return False
  return True


def getIrfComd(identify):
    newMemberID = getNewMemberID(identify)
    if newMemberID is None:
        return None
    if False == isIrfDevice():
        command = "system-view ; irf member %s ; chassis convert mode irf" % newMemberID
    else:
        command = "system-view ; irf member %s renumber %s" % (getMemberID(), newMemberID)
    return command 

def get_self_sn():
    global env
    sn = os.environ.get('DEV_SERIAL', None) 
    if not sn:
        #write2Log("\n[INFO] Environ variable 'DEV_SERIAL' is not found!")
        print "[INFO] Environ variable 'DEV_SERIAL' is not set."  
    return sn


def get_self_mac():
    """通过display lacp system-id来获取桥mac"""
    try:
        cli = comware.CLI("display lacp system-id", False)
        result = cli.get_output()
        if len(result) > 0:
            mac = result[-1].split(',')[-1].strip()
            return mac
    except:
        print '[ERROR] Get system-id failed'
    return None


def get_identify(type):
    identify = None
    if type.lower() == "sn":
        identify = get_self_sn()
    elif type.lower() == "mac":
        identify = get_self_mac()
    return identify


def stackIrfCfg(type):
    identify = get_identify(type)
    if identify is None: 
        print "[INFO] use_identify_file_type is NONE.Skip IRF configuration step."
        return True

    command = getIrfComd(identify)
    if command is None:
        return False

    #write2Log("\n[INFO] startup stack irf begin")
    print "[INFO] Startup stack irf Start"
    try:
        result = comware.CLI(command, False)
        if result == None:
            #write2Log("\n[WARN] Startup stack irf failed: %s" % command)
            print "[WARN] Startup stack irf failed: %s." %command
            return False
    except Exception as inst: 
        #write2Log("\n[ERROR] startup stack irf exception: %s command: %s" % (inst, command))
        print "[ERROR] Startup stack irf exception: %s command: %s." % (inst, command)
        return False

    #write2Log("\n[INFO] Startup stack irf success")
    print "[INFO] Startup stack IRF completed ."
    return True



def ifAllStandbyReady():
    if "get_slot_range" not in dir(comware):
        return True

    slot_range = comware.get_slot_range()
    is_all_ready = True
    for i in range(slot_range["MinSlot"], slot_range["MaxSlot"]):
        slot_info = comware.get_slot_info(i)
        if (slot_info != None) and (slot_info["Role"] == "Standby") and (slot_info["Status"] == "Fail"):
            is_all_ready = False
            #write2Log("\n[INFO] Slot %s is not ready!" % i)
            print "[INFO] Slot %s is not ready." % i
    return is_all_ready


def waitStandbyReady():
    #if have any standby slot was not ready sleep for waiting
    while not ifAllStandbyReady():
        sleep(10)


def get_current_patch_list():
    cmd = "display install active"
    patch_list = []
    try:
        cli = comware.CLI(cmd, False)
        result = cli.get_output()
        for row in result:
            patches = row.split(':/')
            if len(patches) > 1:
                patch_list.append(patches[-1])
    except:
        print "[WARN] Get active patch list failed."
    return patch_list

def main():
    global SELF_DEVICE_INFO
    global use_identify_file_type

    if SELF_DEVICE_INFO is None:
        print "[ERROR] Device is not supported."
        exit(1)

    waitStandbyReady()
    signal.signal(signal.SIGTERM, sigterm_handler)
    image_version = SELF_DEVICE_INFO.get('version')
    #write2Log("\n[INFO] Target version: %s" % image_version)
    print "[INFO] Target version: %s" % image_version
    device_version = get_device_version()
    #write2Log("\n[INFO] Current version: %s" % device_version)
    print "[INFO] Current version: %s" % device_version
    patch_list = SELF_DEVICE_INFO.get('patch_list', [])
    #write2Log("\n[INFO] Install patch_list: %s" % patch_list)
    print "[INFO] Install patch_list: %s" % patch_list
    current_patch_list = get_current_patch_list()
    filter_patch_list = filter(lambda x: x not in current_patch_list, patch_list)
    
    if device_version.lower() != image_version.lower() and image_version.strip() != '':
        if not verifyAllFreeSpace():
            exit(1)
        if self_device_ipe_name != NOT_SPECIFY_IPE and copyBootImage():
            signal.signal(signal.SIGTERM, sig_handler_no_exit)
            installBootImage()
        if filter_patch_list:
            doExit("success")
        else:
            pass
    else:
        if filter_patch_list:
            patch_status = copyPatches(filter_patch_list)
            signal.signal(signal.SIGTERM, sig_handler_no_exit)
            installPatches(filter_patch_list, patch_status)
    signal.signal(signal.SIGTERM, sig_handler_no_exit)
    
    if copyCfgFile() and startupCfg():
        if copyIdentifyFile(use_identify_file_type) and stackIrfCfg(use_identify_file_type):
            doExit("success")
        else:
            doExit("error")
    else:
        doExit("error")


if __name__ == "__main__":
    main()
