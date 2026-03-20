# helper file of droidbot
# it parses command arguments and send the options to droidbot
import argparse
import subprocess
import tempfile
from pathlib import Path
from droidbot import input_manager
from droidbot import input_policy
from droidbot import env_manager
from droidbot import DroidBot
from droidbot.droidmaster import DroidMaster


def _adb_cmd(device_serial: str | None, *args: str) -> list[str]:
    cmd = ["adb"]
    if device_serial:
        cmd += ["-s", device_serial]
    cmd += list(args)
    return cmd


def _run_cmd(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"命令执行失败: {' '.join(cmd)}\n{p.stderr.strip()}")
    return p.stdout


def pull_installed_base_apk(device_serial: str | None, package_name: str) -> str:
    """
    从已安装应用拉取 base.apk 到本地临时目录，返回本地 apk 路径。
    """
    out = _run_cmd(_adb_cmd(device_serial, "shell", "pm", "path", package_name))
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("package:")]
    if not lines:
        raise RuntimeError(f"设备上未找到已安装应用: {package_name}")

    remote_apks = [ln.replace("package:", "", 1).strip() for ln in lines]
    base_apk = next((p for p in remote_apks if p.endswith("/base.apk") or p.endswith("base.apk")), remote_apks[0])

    tmp_dir = Path(tempfile.mkdtemp(prefix="droidbot_installed_apk_"))
    local_apk = tmp_dir / f"{package_name}.apk"
    _run_cmd(_adb_cmd(device_serial, "pull", base_apk, str(local_apk)))

    if not local_apk.exists():
        raise RuntimeError(f"拉取 APK 失败: {local_apk}")
    return str(local_apk)


def parse_args():
    """
    parse command line input
    generate options including host name, port number
    """
    parser = argparse.ArgumentParser(description="Start DroidBot to test an Android app.",
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-d", action="store", dest="device_serial", required=False,
                        help="The serial number of target device (use `adb devices` to find)")
    parser.add_argument("-a", action="store", dest="apk_path", required=False,
                        help="The file path to target APK")
    parser.add_argument("--use-installed-app", action="store_true", dest="use_installed_app",
                        help="从设备已安装应用拉取 APK（仍用 androguard 分析），并跳过安装步骤")
    parser.add_argument("--app-package", action="store", dest="app_package",
                        help="已安装应用包名，如 com.baidu.netdisk")
    parser.add_argument("-o", action="store", dest="output_dir",
                        help="directory of output")
    # parser.add_argument("-env", action="store", dest="env_policy",
    #                     help="policy to set up environment. Supported policies:\n"
    #                          "none\tno environment will be set. App will run in default environment of device; \n"
    #                          "dummy\tadd some fake contacts, SMS log, call log; \n"
    #                          "static\tset environment based on static analysis result; \n"
    #                          "<file>\tget environment policy from a json file.\n")
    parser.add_argument("-policy", action="store", dest="input_policy", default=input_manager.DEFAULT_POLICY,
                        help='Policy to use for test input generation. '
                             'Default: %s.\nSupported policies:\n' % input_manager.DEFAULT_POLICY +
                             '  \"%s\" -- No event will be sent, user should interact manually with device; \n'
                             '  \"%s\" -- Use "adb shell monkey" to send events; \n'
                             '  \"%s\" -- Explore UI using a naive depth-first strategy;\n'
                             '  \"%s\" -- Explore UI using a greedy depth-first strategy;\n'
                             '  \"%s\" -- Explore UI using a naive breadth-first strategy;\n'
                             '  \"%s\" -- Explore UI using a greedy breadth-first strategy;\n'
                             %
                             (
                                 input_policy.POLICY_NONE,
                                 input_policy.POLICY_MONKEY,
                                 input_policy.POLICY_NAIVE_DFS,
                                 input_policy.POLICY_GREEDY_DFS,
                                 input_policy.POLICY_NAIVE_BFS,
                                 input_policy.POLICY_GREEDY_BFS,
                             ))

    # for distributed DroidBot
    parser.add_argument("-distributed", action="store", dest="distributed", choices=["master", "worker"],
                        help="Start DroidBot in distributed mode.")
    parser.add_argument("-master", action="store", dest="master",
                        help="DroidMaster's RPC address")
    parser.add_argument("-qemu_hda", action="store", dest="qemu_hda",
                        help="The QEMU's hda image")
    parser.add_argument("-qemu_no_graphic", action="store_true", dest="qemu_no_graphic",
                        help="Run QEMU with -nograpihc parameter")

    parser.add_argument("-script", action="store", dest="script_path",
                        help="Use a script to customize input for certain states.")
    parser.add_argument("-count", action="store", dest="count", default=input_manager.DEFAULT_EVENT_COUNT, type=int,
                        help="Number of events to generate in total. Default: %d" % input_manager.DEFAULT_EVENT_COUNT)
    parser.add_argument("-interval", action="store", dest="interval", default=input_manager.DEFAULT_EVENT_INTERVAL,
                        type=int,
                        help="Interval in seconds between each two events. Default: %d" % input_manager.DEFAULT_EVENT_INTERVAL)
    parser.add_argument("-timeout", action="store", dest="timeout", default=input_manager.DEFAULT_TIMEOUT, type=int,
                        help="Timeout in seconds, -1 means unlimited. Default: %d" % input_manager.DEFAULT_TIMEOUT)
    parser.add_argument("-cv", action="store_true", dest="cv_mode",
                        help="Use OpenCV (instead of UIAutomator) to identify UI components. CV mode requires opencv-python installed.")
    parser.add_argument("-debug", action="store_true", dest="debug_mode",
                        help="Run in debug mode (dump debug messages).")
    parser.add_argument("-random", action="store_true", dest="random_input",
                        help="Add randomness to input events.")
    parser.add_argument("-keep_app", action="store_true", dest="keep_app",
                        help="Keep the app on the device after testing.")
    parser.add_argument("-keep_env", action="store_true", dest="keep_env",
                        help="Keep the test environment (eg. minicap and accessibility service) after testing.")
    parser.add_argument("-use_method_profiling", action="store", dest="profiling_method",
                        help="Record method trace for each event. can be \"full\" or a sampling rate.")
    parser.add_argument("-grant_perm", action="store_true", dest="grant_perm",
                        help="Grant all permissions while installing. Useful for Android 6.0+.")
    parser.add_argument("-is_emulator", action="store_true", dest="is_emulator",
                        help="Declare the target device to be an emulator, which would be treated specially by DroidBot.")
    parser.add_argument("-accessibility_auto", action="store_true", dest="enable_accessibility_hard",
                        help="Enable the accessibility service automatically even though it might require device restart\n(can be useful for Android API level < 23).")
    parser.add_argument("-humanoid", action="store", dest="humanoid",
                        help="Connect to a Humanoid service (addr:port) for more human-like behaviors.")
    parser.add_argument("-ignore_ad", action="store_true", dest="ignore_ad",
                        help="Ignore Ad views by checking resource_id.")
    parser.add_argument("-replay_output", action="store", dest="replay_output",
                        help="The droidbot output directory being replayed.")
    options = parser.parse_args()
    # print options
    return options


def main():
    """
    the main function
    it starts a droidbot according to the arguments given in cmd line
    """
    opts = parse_args()
    import os

    if not opts.apk_path and not opts.use_installed_app:
        print("请提供 -a <apk>，或使用 --use-installed-app --app-package <pkg>")
        return

    if opts.use_installed_app:
        if not opts.app_package:
            print("使用 --use-installed-app 时必须提供 --app-package")
            return
        try:
            opts.apk_path = pull_installed_base_apk(opts.device_serial, opts.app_package)
            print(f"[INFO] 已拉取 APK: {opts.apk_path}")
        except Exception as e:
            print(f"[ERROR] {e}")
            return
    else:
        if not os.path.exists(opts.apk_path):
            print("APK does not exist.")
            return

    if not opts.output_dir and opts.cv_mode:
        print("To run in CV mode, you need to specify an output dir (using -o option).")

    if opts.distributed:
        if opts.distributed == "master":
            start_mode = "master"
        else:
            start_mode = "worker"
    else:
        start_mode = "normal"

    if start_mode == "master":
        if opts.use_installed_app:
            print("当前补丁仅支持 normal 模式的已安装应用流程，master 模式请使用 -a。")
            return
        droidmaster = DroidMaster(
            app_path=opts.apk_path,
            is_emulator=opts.is_emulator,
            output_dir=opts.output_dir,
            # env_policy=opts.env_policy,
            env_policy=env_manager.POLICY_NONE,
            policy_name=opts.input_policy,
            random_input=opts.random_input,
            script_path=opts.script_path,
            event_interval=opts.interval,
            timeout=opts.timeout,
            event_count=opts.count,
            cv_mode=opts.cv_mode,
            debug_mode=opts.debug_mode,
            keep_app=opts.keep_app,
            keep_env=opts.keep_env,
            profiling_method=opts.profiling_method,
            grant_perm=opts.grant_perm,
            enable_accessibility_hard=opts.enable_accessibility_hard,
            qemu_hda=opts.qemu_hda,
            qemu_no_graphic=opts.qemu_no_graphic,
            humanoid=opts.humanoid,
            ignore_ad=opts.ignore_ad,
            replay_output=opts.replay_output)
        droidmaster.start()
    else:
        droidbot = DroidBot(
            app_path=opts.apk_path,
            device_serial=opts.device_serial,
            is_emulator=opts.is_emulator,
            output_dir=opts.output_dir,
            # env_policy=opts.env_policy,
            env_policy=env_manager.POLICY_NONE,
            policy_name=opts.input_policy,
            random_input=opts.random_input,
            script_path=opts.script_path,
            event_interval=opts.interval,
            timeout=opts.timeout,
            event_count=opts.count,
            cv_mode=opts.cv_mode,
            debug_mode=opts.debug_mode,
            keep_app=opts.keep_app,
            keep_env=opts.keep_env,
            profiling_method=opts.profiling_method,
            grant_perm=opts.grant_perm,
            enable_accessibility_hard=opts.enable_accessibility_hard,
            master=opts.master,
            humanoid=opts.humanoid,
            ignore_ad=opts.ignore_ad,
            replay_output=opts.replay_output,
            skip_install=opts.use_installed_app)
        droidbot.start()
    return


if __name__ == "__main__":
    main()
