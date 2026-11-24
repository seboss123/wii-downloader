#!/usr/bin/env python3
"""
Format a USB drive to FAT32 with 32KB clusters for Wii USB loaders.

Uses fmifs.dll FormatEx API (same API Windows uses internally).
Wii requirements: FAT32, 32KB clusters, MBR partition table.

Usage: python format_wii_usb.py D:
"""

import ctypes
from ctypes import wintypes
import sys
import time

fmifs = ctypes.windll.fmifs

# FMIFS_CALLBACK signature:
# BOOLEAN NTAPI PfmifsCallback(
#   IN CALLBACKCOMMAND Command,
#   IN ULONG SubAction,
#   IN PVOID ActionInfo
# )
# Returns TRUE to continue, FALSE to cancel
FMT_CB_FUNC = ctypes.WINFUNCTYPE(ctypes.c_byte, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p)

# FMIFS_MEDIA_FLAG values
FMIFS_MEDIA_FLAG_FLOPPY = 0
FMIFS_MEDIA_FLAG_HARDDISK = 1
FMIFS_MEDIA_FLAG_REMOVABLE = 2


class FormatProgress:
    """Tracks format progress from callback commands."""
    CALLBACK_FORMATTING = 9
    CALLBACK_COMPLETE = 11

    def __init__(self):
        self.last_command = None
        self.done = False
        self.success = False

    def __call__(self, command, subaction, action_info):
        self.last_command = command
        if command == self.CALLBACK_COMPLETE:
            self.done = True
            self.success = True
            print(f"  Format complete! (command={command})")
        elif command == self.CALLBACK_FORMATTING:
            print(f"  Formatting... (command={command}, subaction={subaction})")
        else:
            print(f"  Callback: command={command}, subaction={subaction}, info={action_info}")
        return 1  # TRUE = continue


def format_drive(drive_letter: str, cluster_size: int = 32768, label: str = "WII") -> bool:
    """
    Format a drive using fmifs.dll FormatEx.
    
    Args:
        drive_letter: Drive letter (e.g., 'D' or 'D:')
        cluster_size: Cluster size in bytes (32768 for Wii)
        label: Volume label
    
    Returns:
        True if format succeeded
    """
    # Normalize drive letter to root path format 'D:\\'
    drive_letter = drive_letter.upper().rstrip(':')
    drive_root = f'{drive_letter}:\\'

    progress = FormatProgress()
    callback_func = FMT_CB_FUNC(progress)

    FormatEx = fmifs.FormatEx
    FormatEx.restype = ctypes.c_ulong
    FormatEx.argtypes = [
        ctypes.c_wchar_p,   # DriveRoot (e.g., 'D:\\')
        ctypes.c_ulong,     # MediaFlag
        ctypes.c_wchar_p,   # Format (e.g., 'FAT32')
        ctypes.c_wchar_p,   # Label (e.g., 'WII')
        ctypes.c_byte,      # QuickFormat (BOOLEAN)
        ctypes.c_ulong,     # ClusterSize in bytes
        FMT_CB_FUNC,        # Callback
    ]

    print(f"Formatting {drive_root} as FAT32 with {cluster_size} byte clusters...")
    print(f"Volume label: {label}")
    print("This will ERASE ALL DATA on the drive!")
    print()

    result = FormatEx(
        drive_root,
        FMIFS_MEDIA_FLAG_HARDDISK,  # Media flag
        'FAT32',                     # File system
        label,                       # Volume label
        True,                        # Quick format
        cluster_size,                # Cluster size (32KB = 32768)
        callback_func,               # Callback
    )

    print(f"\nFormatEx return code: {result}")
    print(f"Progress done: {progress.done}, success: {progress.success}")
    print(f"Last callback command: {progress.last_command}")

    # FormatEx returns 0 on success in some implementations, or NTSTATUS
    # ReactOS returns VOID, but Windows FMIFS may return error codes
    if result == 0 or progress.success:
        print("\n✓ Format succeeded!")
        return True
    else:
        print(f"\n✗ Format may have failed (code: {result})")
        return False


def verify_drive(drive_letter: str) -> None:
    """Verify drive format after formatting."""
    import subprocess
    result = subprocess.run(
        ['powershell', '-Command',
         f"Get-CimInstance -ClassName Win32_Volume -Filter \"DriveLetter='{drive_letter}:'\" | Select-Object BlockSize, FileSystem, DriveLabel"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(f"Errors: {result.stderr}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python format_wii_usb.py <drive_letter> [cluster_size_bytes] [label]")
        print("Example: python format_wii_usb.py D: 32768 WII")
        print()
        print("WARNING: This will ERASE ALL DATA on the drive!")
        sys.exit(1)

    drive = sys.argv[1]
    cluster_size = int(sys.argv[2]) if len(sys.argv) > 2 else 32768
    label = sys.argv[3] if len(sys.argv) > 3 else "WII"

    print("=" * 60)
    print("Wii USB Drive Formatter")
    print("=" * 60)
    print(f"Drive: {drive}")
    print(f"File system: FAT32")
    print(f"Cluster size: {cluster_size} bytes ({cluster_size // 1024} KB)")
    print(f"Volume label: {label}")
    print("=" * 60)
    print()

    confirm = sys.argv[4].lower() if len(sys.argv) > 4 else input("This will ERASE ALL DATA on the drive. Continue? (yes/no): ")
    if confirm != 'yes':
        print("Cancelled.")
        sys.exit(0)

    success = format_drive(drive, cluster_size, label)

    if success:
        print("\nVerifying format...")
        time.sleep(2)
        verify_drive(drive)
        print("\nDrive is ready for Wii games!")
        print("Copy .wbfs files to: D:\\wbfs\\Game Name [GAMEID]\\GAMEID.wbfs")
    else:
        print("\nFormat failed. You may need to use GUIFormat or another tool.")
        sys.exit(1)


if __name__ == "__main__":
    main()