from pcwatch_lib.collectors import add_smart_metrics, parse_smart_output
from pcwatch_lib.config import HostConfig, load_config
from pcwatch_lib.models import Collected
from pcwatch_lib.remote import (
    _parse_disk,
    _parse_failed,
    _parse_mem,
    build_remote_script,
    parse_sections,
)

SAMPLE = """@@META
rpi
Linux rpi 6.6.0 #1 SMP aarch64 GNU/Linux
 10:00:00 up 2 days,  3:04,  1 user,  load average: 0.10, 0.20, 0.30
4

@@DISK
Filesystem     1024-blocks    Used Available Capacity Mounted on
/dev/root         30237696 8000000  21000000      28% /

@@MEM
               total        used        free      shared  buff/cache   available
Mem:             8000        3000        1000         100        4000        4500
Swap:            2000         100        1900

@@FAILED
● test.service loaded failed failed A test service

@@END
"""


def test_build_script():
    script = build_remote_script(HostConfig("rpi", type="ssh", target="pi@rpi", smart=True))
    assert "@@META" in script
    assert "@@SMART" in script
    assert "smartctl --scan" in script


def test_parse_sections():
    sections = parse_sections(SAMPLE)
    assert sections["META"].startswith("rpi")
    assert "rpi" in sections["META"]
    assert "test.service" in sections["FAILED"]


def test_parse_metrics():
    config = load_config("/tmp/does-not-exist-pcwatch.toml")
    sections = parse_sections(SAMPLE)
    collected = Collected(host="rpi", host_type="ssh")
    _parse_disk(config, sections, collected)
    _parse_mem(config, sections, collected)
    _parse_failed(sections, collected)
    assert any(m.key == "disk:/" for m in collected.metrics)
    assert any(m.key == "mem" for m in collected.metrics)
    assert collected.failed_units[0].unit == "test.service"


def test_parse_smart():
    output = """Smartctl open device: /dev/nvme0n1 failed: Permission denied
Model Number:                       Demo NVMe
Serial Number:                      DEMO
Critical Warning:                   0x00
Temperature:                        40 Celsius
Available Spare:                    100%
Percentage Used:                    12%
Media and Data Integrity Errors:    0
"""
    data = parse_smart_output("/dev/nvme0n1", output)
    assert data["temp_c"] == 40
    assert data["used_percent"] == 12
    config = load_config("/tmp/does-not-exist-pcwatch.toml")
    collected = Collected(host="rpi", host_type="ssh")
    add_smart_metrics(config, data, collected)
    assert any(m.key.startswith("smart:/dev/nvme0n1:") for m in collected.metrics)
